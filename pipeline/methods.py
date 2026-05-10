"""
Incremental method extraction using GLiNER.

Supports two input modes:
  - Live extension: structured turn list that grows over time.
    Extraction runs only on NEW turns since last call (delta processing).
  - Batch upload: flat full_text string with [HUMAN]/[ASSISTANT] markers.
    Parsed into turns first, then processed the same way.

Output per extraction call:
  - new_spans:  spans extracted from the new turns only (for live animation)
  - all_spans:  full deduplicated span list across all turns so far
  - state:      opaque dict to pass back on next call (tracks progress)

Usage (batch):
    python -m pipeline.methods
    python -m pipeline.methods --limit 5 --compare

Usage (live, from code):
    from pipeline.methods import IncrementalMethodExtractor
    extractor = IncrementalMethodExtractor()

    # First message arrives
    result = extractor.process_turn({"role": "human", "text": "I am using NMF..."})
    print(result["new_spans"])

    # Assistant responds
    result = extractor.process_turn({"role": "assistant", "text": "NMF with auto..."})
    print(result["new_spans"])

    # Get full state at any point
    print(extractor.all_spans)
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GLINER_LABELS = [
    "tool or product",       # NMF, sklearn, cast iron pan, Mr. Clean, Excel
    "technique or action",   # steaming, close reading, elbow method, marinating
    "process or workflow",   # batch processing, meal prepping, topic modeling
]

THRESHOLD      = 0.7   # confidence cutoff
MIN_SPAN_CHARS = 3     # filter single characters and noise


# ---------------------------------------------------------------------------
# Model loader — cached globally, loads once per process
# ---------------------------------------------------------------------------

_model = None
_lemmatizer = None

def _get_model():
    global _model
    if _model is None:
        try:
            from gliner import GLiNER
        except ImportError:
            raise RuntimeError("GLiNER not installed. Run: pip install gliner")
        print("  [GLiNER] loading model...")
        _model = GLiNER.from_pretrained("urchade/gliner_small-v2.1")
        print("  [GLiNER] model ready")
    return _model


def _get_lemmatizer():
    """
    Load NLTK WordNet lemmatizer once per process.
    Falls back gracefully if nltk/wordnet not available.
    """
    global _lemmatizer
    if _lemmatizer is None:
        try:
            from nltk.stem import WordNetLemmatizer
            import nltk
            # Download silently if not present
            nltk.download("wordnet", quiet=True)
            nltk.download("omw-1.4", quiet=True)
            _lemmatizer = WordNetLemmatizer()
        except Exception:
            _lemmatizer = None  # graceful degradation — just use lowercase
    return _lemmatizer


def _normalize_span(span: str) -> str:
    """
    Produce a canonical dedup key for a span.

    Strategy:
    - Acronyms (all-caps, ≤5 chars): keep uppercase, e.g. NMF, PCA, LLM
    - Multi-word spans: lowercase only, skip lemmatization to preserve meaning
    - Single common words: lemmatize as verb to collapse morphological variants
      e.g. Normalizing / normalize / normalization → normalize
    """
    # Acronym: all uppercase letters, short
    if span.isupper() and len(span) <= 5:
        return span  # keep NMF, PCA as-is

    # Multi-word: just lowercase
    if " " in span:
        return span.lower()

    # Single word: lemmatize as verb
    lemmatizer = _get_lemmatizer()
    if lemmatizer:
        return lemmatizer.lemmatize(span.lower(), pos="v")

    return span.lower()


# ---------------------------------------------------------------------------
# Turn parsing — handles both input formats
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(r"\[(HUMAN|ASSISTANT)\]\s*", re.IGNORECASE)

def parse_turns(source: str | list[dict]) -> list[dict]:
    """
    Normalise input into a list of {role, text} dicts.

    Accepts:
      - list of {role, text} dicts (live extension format)
      - flat string with [HUMAN]/[ASSISTANT] markers (batch upload format)
    """
    if isinstance(source, list):
        turns = []
        for t in source:
            role = t.get("role", "human").lower()
            role = "assistant" if role in ("assistant", "ai", "model") else "human"
            turns.append({"role": role, "text": t.get("text", "").strip()})
        return [t for t in turns if t["text"]]

    # Flat string — split on markers
    parts = _MARKER_RE.split(source)
    turns = []
    i = 1
    while i + 1 < len(parts):
        role_raw = parts[i].strip().lower()
        text     = parts[i + 1].strip()
        role     = "assistant" if role_raw == "assistant" else "human"
        if text:
            turns.append({"role": role, "text": text})
        i += 2
    return turns


# ---------------------------------------------------------------------------
# Span extraction for a single turn
# ---------------------------------------------------------------------------

def _strip_code_blocks(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`]+`", " ", text)
    return text


def _extract_from_text(text: str) -> list[dict]:
    """
    Run GLiNER on a single text block.
    Strips code blocks first, then chunks if needed to respect 384-token limit.
    Uses lemma-based dedup keys to collapse morphological variants.
    """
    MAX_WORDS = 260
    OVERLAP   = 50

    text = _strip_code_blocks(text)

    words = text.split()
    if len(words) <= MAX_WORDS:
        chunks = [text]
    else:
        chunks = []
        i = 0
        while i < len(words):
            chunks.append(" ".join(words[i : i + MAX_WORDS]))
            i += MAX_WORDS - OVERLAP

    model = _get_model()
    # key: normalized lemma → value: best span object seen so far
    seen: dict[str, dict] = {}

    for chunk in chunks:
        try:
            entities = model.predict_entities(chunk, GLINER_LABELS, threshold=THRESHOLD)
        except Exception as e:
            print(f"  [GLiNER] error: {e}")
            continue

        for ent in entities:
            span  = ent["text"].strip()
            score = round(ent["score"], 3)

            if len(span) < MIN_SPAN_CHARS:
                continue

            key = _normalize_span(span)   # lemma-based canonical key

            if key not in seen or score > seen[key]["score"]:
                seen[key] = {
                    "span":  span,         # original surface form
                    "key":   key,          # normalized key (useful for viz grouping)
                    "label": ent["label"],
                    "score": score,
                }

    return list(seen.values())


# ---------------------------------------------------------------------------
# Span merging
# ---------------------------------------------------------------------------

def _merge(existing: dict[str, dict], new_spans: list[dict]) -> dict[str, dict]:
    """
    Merge new_spans into existing accumulator (keyed by normalized lemma).
    Keeps highest confidence score per unique key.
    """
    for s in new_spans:
        key = s.get("key") or _normalize_span(s["span"])
        if key not in existing or s["score"] > existing[key]["score"]:
            existing[key] = {**s, "key": key}
    return existing


def _to_sorted_list(span_dict: dict[str, dict]) -> list[dict]:
    return sorted(span_dict.values(), key=lambda x: x["score"], reverse=True)


# ---------------------------------------------------------------------------
# Incremental extractor class (live extension use case)
# ---------------------------------------------------------------------------

class IncrementalMethodExtractor:
    """
    Stateful extractor for live extension use.

    Maintains a running span accumulator and processes only new turns
    on each call. Designed to be instantiated once per conversation.

    Example:
        extractor = IncrementalMethodExtractor(conv_id="abc123")

        # Turn 1 arrives
        result = extractor.process_turn({"role": "human", "text": "..."})
        # result["new_spans"]  → spans from this turn only
        # result["all_spans"]  → all spans so far

        # Turn 2 arrives
        result = extractor.process_turn({"role": "assistant", "text": "..."})
    """

    def __init__(self, conv_id: str = ""):
        self.conv_id           = conv_id
        self._accumulated:     dict[str, dict] = {}
        self._processed_turns: list[dict]      = []
        self._turn_index       = 0

    def process_turn(self, turn: dict) -> dict:
        """
        Process a single new turn and return extraction delta.

        Args:
            turn: {role: str, text: str}

        Returns:
            {
                "turn_index": int,
                "role":       str,
                "new_spans":  list[dict],   # spans found in THIS turn only
                "all_spans":  list[dict],   # all spans accumulated so far
            }
        """
        role = turn.get("role", "human")
        text = turn.get("text", "").strip()

        new_raw   = _extract_from_text(text) if text else []
        new_spans = []

        for s in new_raw:
            key    = s.get("key") or _normalize_span(s["span"])
            is_new = key not in self._accumulated
            s_with_prov = {
                **s,
                "key":        key,
                "turn_index": self._turn_index,
                "turn_role":  role,
            }
            if is_new:
                new_spans.append(s_with_prov)
            self._accumulated = _merge(self._accumulated, [s_with_prov])

        self._processed_turns.append({"role": role, "text": text})
        self._turn_index += 1

        return {
            "turn_index": self._turn_index - 1,
            "role":       role,
            "new_spans":  new_spans,
            "all_spans":  _to_sorted_list(self._accumulated),
        }

    def process_turns(self, turns: list[dict]) -> dict:
        """Process multiple new turns, return combined delta."""
        all_new: list[dict] = []
        for turn in turns:
            result = self.process_turn(turn)
            all_new.extend(result["new_spans"])
        return {
            "new_spans": all_new,
            "all_spans": _to_sorted_list(self._accumulated),
        }

    @property
    def all_spans(self) -> list[dict]:
        return _to_sorted_list(self._accumulated)

    def to_state(self) -> dict:
        """Serialise state for persistence (e.g. chrome.storage)."""
        return {
            "conv_id":         self.conv_id,
            "accumulated":     self._accumulated,
            "processed_turns": self._processed_turns,
            "turn_index":      self._turn_index,
        }

    @classmethod
    def from_state(cls, state: dict) -> "IncrementalMethodExtractor":
        """Restore extractor from persisted state."""
        obj = cls(conv_id=state.get("conv_id", ""))
        obj._accumulated     = state.get("accumulated", {})
        obj._processed_turns = state.get("processed_turns", [])
        obj._turn_index      = state.get("turn_index", 0)
        return obj


# ---------------------------------------------------------------------------
# Batch pipeline runner
# ---------------------------------------------------------------------------

def run_batch(
    conversations_path: str = "processed/conversations.json",
    out_path:           str = "processed/layer_method.json",
    limit:              int | None = None,
    compare:            bool = False,
) -> None:
    with open(conversations_path, encoding="utf-8") as f:
        conversations: list[dict] = json.load(f)

    eligible = [
        c for c in conversations
        if c.get("human_turn_count", 0) > 0
        and len((c.get("full_text") or c.get("human_text", "")).strip()) > 30
    ]
    if limit:
        eligible = eligible[:limit]

    print(f"Extracting methods from {len(eligible)} conversations "
          f"(skipped {len(conversations) - len(eligible)})")

    results: list[dict] = []

    for i, conv in enumerate(eligible):
        title = conv.get("title", "")[:60]
        print(f"\n  [{i+1}/{len(eligible)}] {title}")

        raw_turns = conv.get("turns")
        if raw_turns:
            turns = parse_turns(raw_turns)
        else:
            full_text = conv.get("full_text") or conv.get("human_text", "")
            turns = parse_turns(full_text)

        print(f"    {len(turns)} turns to process")

        extractor = IncrementalMethodExtractor(conv_id=conv["id"])

        t0 = time.perf_counter()
        for j, turn in enumerate(turns):
            result = extractor.process_turn(turn)
            if result["new_spans"]:
                new_labels = [s["span"] for s in result["new_spans"]]
                print(f"    turn {j} [{turn['role'][:1].upper()}]: +{new_labels}")
        elapsed = time.perf_counter() - t0

        all_spans = extractor.all_spans
        keywords  = [s["span"] for s in all_spans]

        print(f"    → {len(all_spans)} total spans in {elapsed:.2f}s")

        if compare:
            old_kw = conv.get("method_keywords", [])
            print(f"    OLD: {old_kw}")
            print(f"    NEW: {keywords}")

        results.append({
            "id":               conv["id"],
            "title":            conv.get("title", ""),
            "date":             conv.get("date") or (conv.get("created_at", "")[:10] if conv.get("created_at") else None),
            "duration_minutes": conv.get("duration_minutes"),
            "human_turn_count": conv.get("human_turn_count"),
            "method_keywords":  keywords,
            "method_spans":     all_spans,
            "workflow_summary": conv.get("workflow_summary"),
        })

    all_spans_flat = [s for r in results for s in r["method_spans"]]
    label_counts: dict[str, int] = {}
    for s in all_spans_flat:
        label_counts[s["label"]] = label_counts.get(s["label"], 0) + 1

    output = {
        "conversations": results,
        "stats": {
            "conversations_processed":    len(results),
            "total_spans":                len(all_spans_flat),
            "label_counts":               label_counts,
            "avg_spans_per_conversation": round(len(all_spans_flat) / max(len(results), 1), 1),
        },
    }

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {out}  ({out.stat().st_size // 1024} KB)")
    print(f"Total spans:              {len(all_spans_flat)}")
    print(f"Label breakdown:          {label_counts}")
    print(f"Avg spans/conversation:   {output['stats']['avg_spans_per_conversation']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversations", default="processed/conversations.json")
    parser.add_argument("--out",           default="processed/layer_method.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--compare", action="store_true",
                        help="Print side-by-side vs existing method_keywords")
    args = parser.parse_args()
    run_batch(args.conversations, args.out, args.limit, args.compare)
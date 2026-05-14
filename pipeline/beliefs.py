"""
Extract belief networks from conversations using Claude.

For each conversation, identifies:
- Nodes = meaningful reasoning units (claim, evidence, conclusion, other)
- Edges = logical relationships between nodes
          (supports, contradicts, elaborates, causes, alternatives)

Processes the full conversation (human + AI turns) in a single flat-batch call per
conversation. Speaker provenance and reception are tracked per node.

Node schema:
  type       — claim | evidence | conclusion | other
  origin     — user | model | co-constructed
  text_long  — atomic proposition, max 15 words
  text_short — compressed UI label, max 4 words
  text       — alias for text_long (consumed by frontend)

Outputs processed/layer_belief.json with:
  - per_conversation: list of {id, title, nodes, edges}
  - global: merged flat node/edge lists across all conversations
  - stats: node/edge type counts using the actual schema enums

Usage:
    python -m pipeline.beliefs
    python -m pipeline.beliefs --limit 3      # test on first 3 conversations
    python -m pipeline.beliefs --sample data/sample.json  # run on a custom JSON file
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import anthropic

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 8192  # raised: 40 nodes × ~150 tok each = ~6k tok before edges
# ~40k transcript tokens leaves room for system prompt (~1.5k) + tool def (~0.5k) + response
MAX_TRANSCRIPT_CHARS = 160_000
# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a reasoning structure extraction system.

Your task is to analyse a conversation between a USER and an AI ASSISTANT and
extract a reasoning graph consisting of:
- Nodes  = meaningful reasoning units
- Edges  = logical relationships between nodes

NODES:
- Each node must be an atomic belief proposition (max 15 words).
- Beliefs must be specific and non-trivial — skip greetings, filler, and obvious facts.
- Assign every node an `origin` field:
    "user"           — first raised by the human
    "model"          — first raised by the AI assistant
    "co-constructed" — built jointly across turns
- For each node, record `turn_indices`: the list of 0-based turn numbers (as shown in
  the transcript labels) where this belief is explicitly referenced or built upon.
  A belief counts as appearing in a turn even if it is only implicitly built upon —
  if the turn's reasoning relies on it, include that turn index.

Node types (ONLY these are allowed):
    claim       — an assertion, position, or belief stated or implied
    evidence    — an observation, result, or fact used to support reasoning
    constraint  — a requirement, limitation, or goal that shapes the reasoning
    conclusion  — a decision or synthesis reached through reasoning

EDGES:
Extract an edge when you can point to a specific moment in the conversation
where the relationship between two nodes was established, used, or implied.

Do NOT draw edges based on topical similarity alone — two nodes being
about the same subject is not sufficient. The conversation must have
actually treated one as related to the other in a specific way.

Isolated nodes are acceptable and expected — not every belief connects
to another in a given conversation.

Target: 1-2 edges per node on average. Well-formed graphs have connected clusters and (potentially) isolated nodes.

Edge relations (ONLY these are allowed):
    supports  — source provides a reason, evidence, or justification for target
    tension   — source conflicts with, undermines, or pulls against target;
                covers the range from direct contradiction to normative or
                value-level friction where the two cannot comfortably coexist

Edge attributes (optional, applied where identifiable):
    scheme (on supports edges) — the pattern of inference linking source to target:
        causal       — source is presented as producing or bringing about target
        evidential   — source is offered as data or observation backing target
        expert       — source appeals to an authority or expertise to back target
        analogical   — source draws a parallel case to back target
        consequence  — source cites an outcome of target to back (or motivate) it
        example      — source is an instance illustrating target
        other        — support is clear but does not fit the above
    attack_type (on tension edges):
        rebutting    — source conflicts with the content of target directly
        undercutting — source attacks the inference or grounds linking to target,
                       rather than target itself
"""

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

TOOL_DEF = {
    "name": "save_belief_network",
    "description": "Save the extracted reasoning belief network for this conversation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "description": "Reasoning nodes representing atomic belief units.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique node id within this conversation, e.g. n1, n2"
                        },
                        "type": {
                            "type": "string",
                            "enum": ["claim", "evidence", "conclusion", "constraint"],
                            "description": "Role of the belief in reasoning structure: claim=assertion/position, evidence=data/observation/method, conclusion=derived inference, constraint=requirement/limitation/goal"
                        },
                        "origin": {
                            "type": "string",
                            "enum": ["user", "model", "co-constructed"],
                            "description": "Who introduced this idea"
                        },
                        "text_long": {
                            "type": "string",
                            "description": "Atomic proposition (max 15 words)"
                        },
                        "text_short": {
                            "type": "string",
                            "description": "Compressed label for UI display (max 4 words)"
                        },
                        "turn_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "0-based indices of turns (as labelled in the transcript) where this belief is referenced or built upon. Include both the turn where it first appears and any later turns that rely on it."
                        }
                    },
                    "required": ["id", "type", "origin", "text_long", "text_short", "turn_indices"]
                }
            },
            "edges": {
                "type": "array",
                "description": "Argumentative relationships between belief nodes.",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "Source node id"
                        },
                        "target": {
                            "type": "string",
                            "description": "Target node id"
                        },
                        "relation": {
                            "type": "string",
                            "enum": ["supports", "tension"],
                            "description": "Argumentative relationship: supports=source provides reason, evidence, or justification for target; tension=source conflicts with, undermines, or pulls against target, covering the range from direct contradiction to normative or value-level friction"
                        },
                        "scheme": {
                            "type": "string",
                            "enum": ["causal", "evidential", "expert", "analogical", "consequence", "example", "other"],
                            "description": "Optional. Applies only to 'supports' edges. Pattern of inference linking source to target: causal=source produces or brings about target; evidential=source is data or observation backing target; expert=source appeals to authority or expertise; analogical=source draws a parallel case; consequence=source cites an outcome of target; example=source is an instance illustrating target; other=support is clear but does not fit the above. Omit if not identifiable."
                        },
                        "attack_type": {
                            "type": "string",
                            "enum": ["rebutting", "undercutting"],
                            "description": "Optional. Applies only to 'tension' edges. rebutting=source conflicts with the content of target directly; undercutting=source attacks the inference or grounds linking to target rather than target itself. Omit if not identifiable."
                        }
                    },
                    "required": ["source", "target", "relation"]
                }
            },
        },
        "required": ["nodes", "edges"]
    }
}

# Enum values used in stats — single source of truth
NODE_TYPES      = ("claim", "evidence", "conclusion", "constraint")
EDGE_RELATIONS  = ("supports", "tension")
EDGE_SCHEMES    = ("causal", "evidential", "expert", "analogical", "consequence", "example", "other")
EDGE_ATTACK_TYPES = ("rebutting", "undercutting")
ORIGINS         = ("user", "model", "co-constructed")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_turns(turns: list[dict]) -> str:
    """
    Format a list of {role, text} turn dicts into a numbered transcript.
    Each message gets a [Turn N] prefix so Claude can report turn_indices accurately.
    Pre-formatted single-entry transcripts are split on [HUMAN]/[ASSISTANT] markers
    and re-numbered so turn indices remain consistent.
    """
    if len(turns) == 1:
        text = turns[0].get("text", "")
        if "[HUMAN]" in text or "[ASSISTANT]" in text:
            import re
            parts = re.split(r'(\[HUMAN\]|\[ASSISTANT\])', text)
            messages = []
            i = 1
            while i < len(parts) - 1:
                marker = parts[i].strip()
                content = parts[i + 1].strip() if i + 1 < len(parts) else ""
                role = "USER" if marker == "[HUMAN]" else "ASSISTANT"
                messages.append({"role": role, "text": content})
                i += 2
            if messages:
                turns = messages
    lines = []
    for idx, t in enumerate(turns):
        speaker = "USER" if t.get("role") == "human" or t.get("role") == "USER" else "ASSISTANT"
        lines.append(f"[Turn {idx}] [{speaker}] {t['text'].strip()}")
    return "\n\n".join(lines)

def _prefix_ids(network: dict, conv_id: str) -> dict:
    """Namespace node ids with conversation id to avoid collisions in the global graph."""
    prefix = conv_id[:8]

    # Drop malformed entries (e.g. strings instead of dicts)
    raw_nodes = [n for n in network.get("nodes", []) if isinstance(n, dict)]
    raw_edges = [e for e in network.get("edges", []) if isinstance(e, dict)]
    network = {"nodes": raw_nodes, "edges": raw_edges}

    # Assign synthetic ids to any nodes that came back without one
    for i, node in enumerate(network["nodes"]):
        if not node.get("id"):
            node["id"] = f"n{i+1}"

    # Drop nodes still missing required fields after recovery
    valid_nodes = [
        n for n in network["nodes"]
        if n.get("id") and n.get("text_long")
    ]

    id_map = {n["id"]: f"{prefix}_{n['id']}" for n in valid_nodes}
    nodes = [
        {
            **n,
            "id": id_map[n["id"]],
            "text": n.get("text_long", n.get("text", "")),
            "turn_indices": n.get("turn_indices") or [],
        }
        for n in valid_nodes
    ]

    edges = []
    for e in network["edges"]:
        if e.get("source") not in id_map or e.get("target") not in id_map:
            continue
        edge = {
            **e,
            "source": id_map[e["source"]],
            "target": id_map[e["target"]],
        }
        # Strip scheme/attack_type if they don't match the relation
        # (defensive: model shouldn't produce these, but be safe)
        if edge.get("relation") != "supports":
            edge.pop("scheme", None)
        if edge.get("relation") != "tension":
            edge.pop("attack_type", None)
        edges.append(edge)

    return {"nodes": nodes, "edges": edges}

# ---------------------------------------------------------------------------
# Per-conversation summary generation (separate from belief extraction)
# ---------------------------------------------------------------------------

_SUMMARY_BATCH = 5        # conversations per summary API call
_SUMMARY_HEAD  = 400      # chars from first user message
_SUMMARY_TAIL  = 400      # chars from last assistant message

import re as _re
_JSON_RE = _re.compile(r'\{[\s\S]*\}', _re.MULTILINE)


def _parse_summary_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def _make_summary_brief(conv: dict, turns: list[dict], short_id: str) -> dict:
    first_user, last_asst = "", ""
    for t in turns:
        role = t.get("role", "")
        text = (t.get("text") or "").strip()
        if role == "human" and not first_user:
            first_user = text[:_SUMMARY_HEAD]
        if role != "human" and text:
            last_asst = text[-_SUMMARY_TAIL:]
    return {
        "id":    short_id,
        "title": (conv.get("title") or "")[:120],
        "first_user":      first_user,
        "last_assistant":  last_asst,
    }


def generate_summaries(
    client: anthropic.Anthropic,
    conversations: list[dict],
    all_turns:     dict[str, list[dict]],
    model: str = DEFAULT_MODEL,
) -> dict[str, dict]:
    """
    Batch-generate short_title (3-4 words) + short_summary (≤15 words) for each
    conversation.  Returns {conv_id: {short_title, short_summary}}.
    Runs completely separately from belief extraction so it does not affect edge quality.
    """
    results: dict[str, dict] = {}
    n = len(conversations)
    n_batches = (n + _SUMMARY_BATCH - 1) // _SUMMARY_BATCH
    print(f"  Generating summaries for {n} conversations ({n_batches} batches)...")

    for bi in range(n_batches):
        batch    = conversations[bi * _SUMMARY_BATCH : (bi + 1) * _SUMMARY_BATCH]
        id_map   = {}
        briefs   = []
        for idx, conv in enumerate(batch):
            short_id = f"c{idx + 1}"
            turns    = all_turns.get(conv["id"], [])
            briefs.append(_make_summary_brief(conv, turns, short_id))
            id_map[short_id] = conv["id"]

        prompt = (
            f"For each of the {len(batch)} conversations below, output:\n"
            "- short_title: 3-4 English words, Title Case "
            "(e.g. 'React Dashboard Build', 'Resume Bullet Rewrite')\n"
            "- short_summary: ≤15 English words, 1 factual sentence describing "
            "what the user worked on and the rough outcome\n\n"
            "Output ONLY a JSON object (no markdown):\n"
            '{"results": [{"id": "c1", "short_title": "...", "short_summary": "..."}, ...]}\n\n'
            "Conversation data:\n"
            + json.dumps(briefs, ensure_ascii=False)
        )

        for attempt in range(3):
            try:
                resp   = client.messages.create(
                    model=model,
                    max_tokens=600,
                    messages=[{"role": "user", "content": prompt}],
                )
                parsed = _parse_summary_json(resp.content[0].text)
                for item in parsed.get("results", []):
                    cid = id_map.get(item.get("id"))
                    if cid:
                        results[cid] = {
                            "short_title":   (item.get("short_title")   or "").strip(),
                            "short_summary": (item.get("short_summary") or "").strip(),
                        }
                break
            except Exception as e:
                print(f"    [retry {attempt+1}/3] summary batch {bi+1}/{n_batches}: {e}")
                time.sleep(10 * (attempt + 1))

        print(f"  Summary batch {bi+1}/{n_batches} done")

    return results


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

_RETRY_WAITS = [60, 120, 240]  # seconds between retries on rate limit


def extract_one(
    client: anthropic.Anthropic,
    conv_id: str,
    title: str,
    turns: list[dict],
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict:
    """
    Call Claude to extract a belief network from one conversation.

    `turns` is a list of {role: 'human'|'assistant', text: str} dicts
    in chronological order.  Retries up to len(_RETRY_WAITS) times on
    rate-limit errors with increasing back-off.
    """
    transcript = _format_turns(turns)

    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        # Keep first 1/3 (context) + last 2/3 (reasoning/conclusions)
        head = MAX_TRANSCRIPT_CHARS // 3
        tail = MAX_TRANSCRIPT_CHARS - head
        transcript = (
            transcript[:head]
            + f"\n\n[... transcript truncated: {len(transcript):,} chars → {MAX_TRANSCRIPT_CHARS:,} chars ...]\n\n"
            + transcript[-tail:]
        )
        print(f"    ⚠ transcript truncated to {MAX_TRANSCRIPT_CHARS:,} chars")

    user_msg = (
        f"Conversation title: {title}\n\n"
        f"Transcript:\n{transcript}"
    )

    for attempt, wait in enumerate([0] + _RETRY_WAITS):
        if wait:
            print(f"    rate limit — waiting {wait}s (retry {attempt}/{len(_RETRY_WAITS)})…")
            time.sleep(wait)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=0,
                system=SYSTEM_PROMPT,
                tools=[TOOL_DEF],
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": user_msg}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "save_belief_network":
                    return block.input
            return {"nodes": [], "edges": []}
        except anthropic.RateLimitError:
            if attempt == len(_RETRY_WAITS):
                raise  # exhausted all retries

    return {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run(
    conversations_path: str = "processed/conversations.json",
    out_path: str = "processed/layer_belief.json",
    limit: int | None = None,
    timing_log_path: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    sample_size: int | None = None,
    sample_seed: int = 42,
) -> None:
    with open(conversations_path, encoding="utf-8") as f:
        conversations: list[dict] = json.load(f)

    # A conversation is eligible if the human actually said something meaningful
    def has_content(c: dict) -> bool:
        # Skip conversations where the human never typed anything
        if c.get("human_turn_count", 1) == 0:
            return False
        turns = c.get("turns", [])
        if turns:
            return any(t.get("text", "").strip() for t in turns)
        # Prefer full_text (both sides) over human_text alone
        full = c.get("full_text", "").strip()
        if full:
            return len(full) > 100
        return len(c.get("human_text", "").strip()) > 30

    eligible = [c for c in conversations if has_content(c)]
    if sample_size and sample_size < len(eligible):
        rng = random.Random(sample_seed)
        eligible = sorted(rng.sample(eligible, sample_size), key=lambda c: c.get("created_at") or "")
        print(f"  (random sample of {sample_size} conversations, seed={sample_seed})")
    elif limit:
        eligible = eligible[:limit]

    print(
        f"Extracting beliefs from {len(eligible)} conversations "
        f"(skipped {len(conversations) - len(eligible)} with no content)"
    )

    client = anthropic.Anthropic()

    per_conversation: list[dict] = []
    global_nodes:     list[dict] = []
    global_edges:     list[dict] = []
    timing_records:   list[dict] = []

    run_started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    total_start = time.perf_counter()
    conv_times: list[float] = []

    for i, conv in enumerate(eligible):
        print(f"  [{i+1}/{len(eligible)}] {conv['title'][:60]}")

        # Support turn-based, full_text transcript, or legacy human_text-only format
        turns = (
            conv.get("turns")
            or [{"role": "human", "text": conv.get("full_text") or conv.get("human_text", "")}]
        )

        # Conversation characteristics
        total_chars = sum(len(t.get("text", "")) for t in turns)
        human_turn_count = conv.get("human_turn_count") or sum(
            1 for t in turns if t.get("role") == "human"
        )
        ai_turn_count = conv.get("ai_turn_count") or sum(
            1 for t in turns if t.get("role") != "human"
        )

        t0 = time.perf_counter()
        error_msg = None
        try:
            raw = extract_one(client, conv["id"], conv["title"], turns, model, max_tokens)
        except Exception as e:
            error_msg = str(e)
            print(f"    ERROR: {e}")
            raw = {"nodes": [], "edges": []}
        elapsed = time.perf_counter() - t0
        conv_times.append(elapsed)

        namespaced = _prefix_ids(raw, conv["id"])

        date = conv["created_at"][:10] if conv.get("created_at") else None
        for node in namespaced["nodes"]:
            node["conversation_id"]    = conv["id"]
            node["conversation_title"] = conv["title"]
            node["date"]               = date
        for edge in namespaced["edges"]:
            edge["conversation_id"] = conv["id"]

        per_conversation.append({
            "id":    conv["id"],
            "title": conv["title"],
            "date":  date,
            "nodes": namespaced["nodes"],
            "edges": namespaced["edges"],
        })
        global_nodes.extend(namespaced["nodes"])
        global_edges.extend(namespaced["edges"])

        timing_records.append({
            "index":              i + 1,
            "conversation_id":    conv["id"],
            "title":              conv["title"],
            "date":               date,
            "project_name":       conv.get("project_name"),
            "human_turn_count":   human_turn_count,
            "ai_turn_count":      ai_turn_count,
            "total_turn_count":   human_turn_count + ai_turn_count,
            "total_chars":        total_chars,
            "approx_tokens":      total_chars // 4,
            "truncated":          total_chars > MAX_TRANSCRIPT_CHARS,
            "duration_minutes":   conv.get("duration_minutes"),
            "nodes_extracted":    len(namespaced["nodes"]),
            "edges_extracted":    len(namespaced["edges"]),
            "processing_time_s":  round(elapsed, 2),
            "error":              error_msg,
        })

        print(
            f"    → {len(namespaced['nodes'])} nodes, "
            f"{len(namespaced['edges'])} edges  "
            f"({elapsed:.1f}s)"
        )

        if i < len(eligible) - 1:
            # Pace ourselves: budget 50k input tokens/min.
            # Rough estimate: (transcript chars / 4) + system prompt overhead (~800 tok).
            # Sleep enough that at 50k tok/min we don't exceed the limit.
            estimated_tokens = total_chars // 4 + 800
            min_gap = max(2.0, estimated_tokens / (50_000 / 60))
            time.sleep(min_gap)

    total_elapsed = time.perf_counter() - total_start
    avg = sum(conv_times) / len(conv_times) if conv_times else 0.0
    print(
        f"\nTiming: total={total_elapsed:.1f}s  "
        f"avg/conv={avg:.1f}s  "
        f"min={min(conv_times, default=0):.1f}s  "
        f"max={max(conv_times, default=0):.1f}s"
    )

    # ── Separate summary generation (does NOT touch belief extraction) ────────
    print("\nGenerating per-conversation summaries (separate pass)...")
    turns_by_id = {}
    for conv in eligible:
        turns_by_id[conv["id"]] = (
            conv.get("turns")
            or [{"role": "human", "text": conv.get("full_text") or conv.get("human_text", "")}]
        )
    summaries = generate_summaries(client, eligible, turns_by_id, model)
    for entry in per_conversation:
        s = summaries.get(entry["id"], {})
        entry["short_title"]   = s.get("short_title",   "")
        entry["short_summary"] = s.get("short_summary", "")

    # Write timing log
    log_path = Path(timing_log_path) if timing_log_path else Path(out_path).with_name(
        Path(out_path).stem + "_timing.json"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timing_log = {
        "run": {
            "started_at":                  run_started_at,
            "model":                       model,
            "max_tokens":                  max_tokens,
            "sample_size":                 sample_size,
            "sample_seed":                 sample_seed if sample_size else None,
            "conversations_source":        conversations_path,
            "conversations_processed":     len(per_conversation),
            "conversations_skipped":       len(conversations) - len(eligible),
            "total_time_s":                round(total_elapsed, 2),
            "avg_time_per_conv_s":         round(avg, 2),
            "min_time_s":                  round(min(conv_times, default=0), 2),
            "max_time_s":                  round(max(conv_times, default=0), 2),
        },
        "conversations": timing_records,
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(timing_log, f, indent=2, ensure_ascii=False)
    print(f"Wrote timing log → {log_path}")

    result = {
        "per_conversation": per_conversation,
        "global": {
            "nodes": global_nodes,
            "edges": global_edges,
        },
        "stats": {
            "conversations_processed": len(per_conversation),
            "total_nodes": len(global_nodes),
            "total_edges": len(global_edges),
            "node_type_counts": {
                t: sum(1 for n in global_nodes if n.get("type") == t)
                for t in NODE_TYPES
            },
            "edge_relation_counts": {
                r: sum(1 for e in global_edges if e.get("relation") == r)
                for r in EDGE_RELATIONS
            },
            "edge_scheme_counts": {
                s: sum(
                    1 for e in global_edges
                    if e.get("relation") == "supports" and e.get("scheme") == s
                )
                for s in EDGE_SCHEMES
            },
            "edge_scheme_unspecified": sum(
                1 for e in global_edges
                if e.get("relation") == "supports" and not e.get("scheme")
            ),
            "edge_attack_type_counts": {
                a: sum(
                    1 for e in global_edges
                    if e.get("relation") == "tension" and e.get("attack_type") == a
                )
                for a in EDGE_ATTACK_TYPES
            },
            "edge_attack_type_unspecified": sum(
                1 for e in global_edges
                if e.get("relation") == "tension" and not e.get("attack_type")
            ),
            "origin_counts": {
                o: sum(1 for n in global_nodes if n.get("origin") == o)
                for o in ORIGINS
            },
        },
    }

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    stats = result["stats"]
    print(f"\nWrote {out}  ({out.stat().st_size // 1024} KB)")
    print(f"Total nodes: {len(global_nodes)}, edges: {len(global_edges)}")
    print(f"Node types:    {stats['node_type_counts']}")
    print(f"Edge relations: {stats['edge_relation_counts']}")
    print(f"  supports schemes:    {stats['edge_scheme_counts']}")
    print(f"  supports unscheme'd: {stats['edge_scheme_unspecified']}")
    print(f"  tension attacks:     {stats['edge_attack_type_counts']}")
    print(f"  tension untyped:     {stats['edge_attack_type_unspecified']}")
    print(f"Origins:       {stats['origin_counts']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversations", default="processed/conversations.json")
    parser.add_argument("--out",           default="processed/layer_belief.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N conversations (for testing)")
    parser.add_argument("--timing-log", default=None,
                        help="Path for the timing/characteristics log JSON "
                             "(default: <out-stem>_timing.json beside the output file)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Claude model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        help=f"Max output tokens per request (default: {DEFAULT_MAX_TOKENS})")
    parser.add_argument("--sample-size", type=int, default=None,
                        help="Randomly sample N conversations (reproducible via --sample-seed)")
    parser.add_argument("--sample-seed", type=int, default=42,
                        help="Random seed for --sample-size (default: 42)")
    args = parser.parse_args()
    run(args.conversations, args.out, args.limit, args.timing_log,
        args.model, args.max_tokens, args.sample_size, args.sample_seed)
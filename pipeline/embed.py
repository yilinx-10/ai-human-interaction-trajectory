"""
Populate layer_topic.json with embeddings, UMAP positions, and a hierarchical
cluster tree.  Also names each conversation and cluster node.

Outputs layer_topic.json as:
  {
    "conversations": [ { id, title, short_title, short_summary, x, y,
                         embedding, root_cluster_idx, date, ... } ],
    "tree": { recursive Ward cluster tree with short_title + short_summary }
  }

Prerequisites:
  - processed/layer_topic.json   (scaffold from pipeline.run)
  - processed/layer_belief.json  (optional, for short_title/short_summary per conv)

Usage:
    python -m pipeline.embed
    python -m pipeline.embed --no-labels
    python -m pipeline.embed --in processed/layer_topic.json --belief processed/layer_belief.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time as time_module
from pathlib import Path

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
MAX_BRANCHING  = 8     # max children per internal tree node
LAMBDA_TIME    = 0.05  # time perturbation weight in Ward distance
BATCH_NAMES    = 8     # internal nodes named per LLM call
JSON_RE        = re.compile(r'\{[\s\S]*\}', re.MULTILINE)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

OPENAI_EMBED_MODEL = "text-embedding-3-large"
OPENAI_EMBED_DIMS  = 3072
LOCAL_EMBED_MODEL  = "all-MiniLM-L6-v2"
LOCAL_EMBED_DIMS   = 384


def _embed_local(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer
    print(f"  Loading local model ({LOCAL_EMBED_MODEL}, {LOCAL_EMBED_DIMS}-dim)...")
    model = SentenceTransformer(LOCAL_EMBED_MODEL)
    print(f"  Encoding {len(texts)} conversations...")
    vecs = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)
    return vecs.tolist()


OPENAI_MAX_TOKENS_PER_ITEM    = 8000   # hard limit is 8192; stay slightly under
OPENAI_MAX_TOKENS_PER_BATCH   = 250_000  # hard limit is 300k


def _truncate_to_tokens(text: str, enc, max_tokens: int) -> str:
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return enc.decode(tokens[:max_tokens])


def _make_token_batches(texts: list[str], enc) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for t in texts:
        n = len(enc.encode(t))
        if current and current_tokens + n > OPENAI_MAX_TOKENS_PER_BATCH:
            batches.append(current)
            current, current_tokens = [], 0
        current.append(t)
        current_tokens += n
    if current:
        batches.append(current)
    return batches


def _embed_openai(texts: list[str], api_key: str) -> list[list[float]]:
    import tiktoken
    from openai import OpenAI
    enc    = tiktoken.get_encoding("cl100k_base")
    client = OpenAI(api_key=api_key)

    texts     = [_truncate_to_tokens(t, enc, OPENAI_MAX_TOKENS_PER_ITEM) for t in texts]
    truncated = sum(1 for orig, t in zip(texts, texts) if len(orig) != len(t))
    batches   = _make_token_batches(texts, enc)
    print(f"  Using OpenAI {OPENAI_EMBED_MODEL} ({OPENAI_EMBED_DIMS}-dim), {len(batches)} batch(es)"
          + (f", {truncated} texts truncated to {OPENAI_MAX_TOKENS_PER_ITEM} tokens" if truncated else ""))

    results: list[list[float]] = []
    for i, batch in enumerate(batches):
        resp = client.embeddings.create(
            model      = OPENAI_EMBED_MODEL,
            input      = batch,
            dimensions = OPENAI_EMBED_DIMS,
        )
        results.extend(item.embedding for item in sorted(resp.data, key=lambda x: x.index))
        print(f"  Batch {i+1}/{len(batches)} done ({len(results)}/{len(texts)})")
    return results


def embed_texts(
    texts: list[str],
    embedder: str = "local",
    openai_api_key: str | None = None,
) -> list[list[float]]:
    """Return normalized embeddings.  embedder='local' or 'openai'."""
    if embedder == "openai":
        key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            sys.exit("OPENAI_API_KEY must be set (or pass --openai-key) for --embedder openai")
        return _embed_openai(texts, key)
    return _embed_local(texts)


# ---------------------------------------------------------------------------
# UMAP
# ---------------------------------------------------------------------------

def reduce_umap(
    embeddings: list[list[float]],
    n_neighbors: int = 5,
    min_dist: float = 0.3,
) -> list[tuple[float, float]]:
    import numpy as np
    import umap

    print("  Running UMAP (2D projection)...")
    reducer = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        n_components=2,
        random_state=42,
        metric="cosine",
    )
    coords = reducer.fit_transform(np.array(embeddings))
    return [(float(x), float(y)) for x, y in coords]


# ---------------------------------------------------------------------------
# Hierarchical Ward clustering
# ---------------------------------------------------------------------------

def _parse_ts(s: str) -> float:
    import datetime as dt
    if not s:
        return 0.0
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _augment_time(emb: "np.ndarray", timestamps: list[float], lam: float) -> "np.ndarray":
    import numpy as np
    t = np.array(timestamps, dtype=float)
    valid = t > 0
    if valid.sum() < 2:
        return emb
    t_min, t_max = t[valid].min(), t[valid].max()
    if t_max == t_min:
        return emb
    t_norm = np.where(valid, (t - t_min) / (t_max - t_min), 0.5)
    scale = np.sqrt(2.0 * lam)
    return np.hstack([emb, (t_norm * scale)[:, None]]).astype(np.float32)


def _node_id(ids: list[str], depth: int) -> str:
    h = hashlib.sha256(",".join(sorted(ids)).encode()).hexdigest()[:12]
    return f"d{depth}_{h}"


def _collect_leaves(node: dict) -> list[str]:
    if node.get("is_leaf"):
        return [node["id"]]
    out: list[str] = []
    for c in node.get("children", []):
        out.extend(_collect_leaves(c))
    return out


def build_hierarchical_tree(
    records: list[dict],
    embeddings: list[list[float]],
    max_branching: int = MAX_BRANCHING,
    lambda_time: float = LAMBDA_TIME,
) -> dict:
    """Build a recursive Ward cluster tree.  Leaves are conversation ids."""
    import numpy as np
    from scipy.cluster.hierarchy import fcluster, linkage

    conv_ids   = [r["id"] for r in records]
    emb        = np.array(embeddings, dtype=np.float32)
    timestamps = [_parse_ts(r.get("timestamp", "")) for r in records]

    def recurse(ids: list[str], emb_sub: "np.ndarray", ts_sub: list[float], depth: int) -> dict:
        n = len(ids)
        if n == 1:
            return {"id": ids[0], "is_leaf": True, "depth": depth, "size": 1, "leaves": [ids[0]]}

        if n <= max_branching:
            children = [
                {"id": u, "is_leaf": True, "depth": depth + 1, "size": 1, "leaves": [u]}
                for u in ids
            ]
            return {
                "id": _node_id(ids, depth),
                "is_leaf": False,
                "depth": depth,
                "size": n,
                "leaves": list(ids),
                "children": children,
            }

        aug = _augment_time(emb_sub, ts_sub, lambda_time)
        Z   = linkage(aug, method="ward")
        labels = fcluster(Z, t=max_branching, criterion="maxclust")

        children = []
        for label in sorted(set(labels.tolist())):
            mask    = [i for i, lb in enumerate(labels) if lb == label]
            sub_ids = [ids[i] for i in mask]
            sub_emb = emb_sub[mask]
            sub_ts  = [ts_sub[i] for i in mask]
            children.append(recurse(sub_ids, sub_emb, sub_ts, depth + 1))

        return {
            "id":       _node_id(ids, depth),
            "is_leaf":  False,
            "depth":    depth,
            "size":     n,
            "leaves":   list(ids),
            "children": children,
        }

    print(f"  Building hierarchical tree (MAX_BRANCHING={max_branching}, LAMBDA_TIME={lambda_time})...")
    tree = recurse(conv_ids, emb, timestamps, depth=0)
    n_internal = sum(1 for _ in _iter_internal(tree))
    print(f"  Tree: {len(conv_ids)} leaves, {n_internal} internal nodes")
    return tree


def _iter_internal(node: dict):
    """Yield all non-leaf nodes (including root) in post-order."""
    if not node.get("is_leaf"):
        for c in node.get("children", []):
            yield from _iter_internal(c)
        yield node


# ---------------------------------------------------------------------------
# Assign root-cluster indices (for color)
# ---------------------------------------------------------------------------

def assign_root_clusters(tree: dict, conv_by_id: dict) -> None:
    """Write root_cluster_idx onto each conv record."""
    root_children = tree.get("children", [])
    for idx, child in enumerate(root_children):
        for leaf_id in _collect_leaves(child):
            conv = conv_by_id.get(leaf_id)
            if conv is not None:
                conv["root_cluster_idx"] = idx
                conv["cluster_id"]       = idx   # backward compat


# ---------------------------------------------------------------------------
# LLM-based node naming (bottom-up)
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def _child_summaries(node: dict, conv_by_id: dict) -> list[dict]:
    """Short title + summary for each immediate child."""
    result = []
    for child in node.get("children", []):
        if child.get("is_leaf"):
            conv = conv_by_id.get(child["id"], {})
            result.append({
                "short_title":   conv.get("short_title") or conv.get("title", "")[:40],
                "short_summary": conv.get("short_summary", ""),
            })
        else:
            result.append({
                "short_title":   child.get("short_title", ""),
                "short_summary": child.get("short_summary", ""),
            })
    return result


def name_tree_nodes(
    tree: dict,
    conv_by_id: dict,
    api_key: str,
    batch_size: int = BATCH_NAMES,
) -> None:
    """
    Name all internal tree nodes in post-order (deepest first) so that each
    level can use the already-named children's summaries.
    Modifies tree in place.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    # Collect internal nodes in post-order (children before parents)
    nodes_to_name: list[dict] = []

    def collect(node: dict) -> None:
        if node.get("is_leaf"):
            return
        for c in node.get("children", []):
            collect(c)
        if node.get("depth", 0) >= 1:   # skip root (depth 0)
            nodes_to_name.append(node)

    collect(tree)
    print(f"  Naming {len(nodes_to_name)} internal cluster nodes (batch={batch_size})...")

    def make_prompt(briefs: list[dict]) -> str:
        return (
            "Name each group of conversations.\n"
            "For each node output:\n"
            "- short_title: 3-4 English words, Title Case. "
            "Name the dominant or most salient theme — even if not every conversation fits. "
            "Never use generic words like 'Conversations', 'Topics', 'Various', 'Mixed', 'General', 'Assistance', 'Data'.\n"
            "- short_summary: ≤15 English words, 1 sentence on what the majority share.\n\n"
            "Output ONLY a JSON object (no markdown):\n"
            '{"results": [{"id": "n1", "short_title": "...", "short_summary": "..."}, ...]}\n\n'
            "Node data:\n"
            + json.dumps(briefs, ensure_ascii=False)
        )

    n_batches = (len(nodes_to_name) + batch_size - 1) // batch_size
    for bi in range(n_batches):
        batch   = nodes_to_name[bi * batch_size : (bi + 1) * batch_size]
        id_map  = {}
        briefs  = []
        for idx, node in enumerate(batch):
            short_id = f"n{idx + 1}"
            id_map[short_id] = node
            briefs.append({
                "id":              short_id,
                "size":            node["size"],
                "child_summaries": _child_summaries(node, conv_by_id)[:8],
            })

        prompt = make_prompt(briefs)
        for attempt in range(3):
            try:
                resp   = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=800,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                parsed = _parse_json(resp.content[0].text)
                for item in parsed.get("results", []):
                    node = id_map.get(item.get("id"))
                    if node and item.get("short_title"):
                        node["short_title"]   = item["short_title"].strip()
                        node["short_summary"] = (item.get("short_summary") or "").strip()
                break
            except Exception as e:
                print(f"    [retry {attempt+1}/3] batch {bi+1}/{n_batches}: {e}")
                time_module.sleep(5 * (attempt + 1))

        print(f"  Batch {bi+1}/{n_batches} done")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(
    in_path: str  = "processed/layer_topic.json",
    out_path: str = "processed/layer_topic.json",
    belief_path: str | None = None,
    do_labels: bool = True,
    restrict_to_belief: bool = False,
    embedder: str = "local",
    openai_api_key: str | None = None,
) -> None:
    # ── Load scaffold ────────────────────────────────────────────────────────
    with open(in_path, encoding="utf-8") as f:
        raw = json.load(f)

    # Handle both old (flat array) and new (wrapper object) formats
    if isinstance(raw, list):
        records: list[dict] = raw
    else:
        records = raw.get("conversations", [])

    active = [r for r in records if r.get("full_text")]
    print(f"[1/5] Loaded {len(active)} conversations with text")

    # ── Load summaries from beliefs output ───────────────────────────────────
    belief_src = belief_path or "processed/layer_belief.json"
    conv_summaries: dict[str, dict] = {}
    belief_ids: set[str] = set()
    if Path(belief_src).exists():
        with open(belief_src, encoding="utf-8") as f:
            belief_data = json.load(f)
        for entry in belief_data.get("per_conversation", []):
            cid = entry.get("id")
            if not cid:
                continue
            belief_ids.add(cid)
            st  = (entry.get("short_title")   or "").strip()
            ss  = (entry.get("short_summary") or "").strip()
            if st or ss:
                conv_summaries[cid] = {"short_title": st, "short_summary": ss}
        print(f"  Loaded summaries for {len(conv_summaries)} conversations from {belief_src}")
    else:
        print(f"  {belief_src} not found — proceeding without pre-generated summaries")

    # ── Restrict to the belief sample if requested ───────────────────────────
    if restrict_to_belief:
        if not belief_ids:
            print("  WARNING: --restrict-to-belief set but no belief IDs found; using all conversations")
        else:
            before = len(active)
            active = [r for r in active if r["id"] in belief_ids]
            print(f"  Restricted to {len(active)} conversations present in belief layer (was {before})")

    # Attach summaries to records
    for r in active:
        sums = conv_summaries.get(r["id"], {})
        r["short_title"]   = sums.get("short_title",   "")
        r["short_summary"] = sums.get("short_summary", "")

    # ── Embeddings ───────────────────────────────────────────────────────────
    print(f"[2/5] Embedding conversations (embedder={embedder})")
    texts      = [r["full_text"] for r in active]
    embeddings = embed_texts(texts, embedder=embedder, openai_api_key=openai_api_key)
    for r, emb in zip(active, embeddings):
        r["embedding"] = emb

    # ── UMAP ────────────────────────────────────────────────────────────────
    print("[3/5] UMAP 2D projection")
    coords = reduce_umap(embeddings)
    for r, (x, y) in zip(active, coords):
        r["x"] = x
        r["y"] = y

    # ── Hierarchical clustering ──────────────────────────────────────────────
    print("[4/5] Hierarchical Ward clustering")
    tree = build_hierarchical_tree(active, embeddings)

    conv_by_id = {r["id"]: r for r in active}
    assign_root_clusters(tree, conv_by_id)

    # ── Label tree nodes ─────────────────────────────────────────────────────
    if do_labels:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("[5/5] Skipping LLM labels (ANTHROPIC_API_KEY not set)")
        else:
            print("[5/5] Labeling cluster nodes with Claude (bottom-up)")
            name_tree_nodes(tree, conv_by_id, api_key)
            # Propagate root-level cluster short_title as topic_label for compat
            for child in tree.get("children", []):
                for leaf_id in _collect_leaves(child):
                    conv = conv_by_id.get(leaf_id)
                    if conv is not None:
                        conv["topic_label"] = child.get("short_title", "")
    else:
        print("[5/5] Skipping LLM labels (--no-labels)")

    # ── Write output ─────────────────────────────────────────────────────────
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    output = {"conversations": active, "tree": tree}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out}  ({out.stat().st_size // 1024} KB)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--in",      dest="in_path",    default="processed/layer_topic.json")
    parser.add_argument("--out",     dest="out_path",   default="processed/layer_topic.json")
    parser.add_argument("--belief",  dest="belief_path", default=None,
                        help="Path to layer_belief.json (default: processed/layer_belief.json)")
    parser.add_argument("--no-labels", action="store_true")
    parser.add_argument("--restrict-to-belief", action="store_true",
                        help="Only embed conversations present in the belief layer output "
                             "(useful when beliefs.py was run with --sample-size)")
    parser.add_argument(
        "--embedder",
        choices=["local", "openai"],
        default="openai",
        help=(
            "local  — all-MiniLM-L6-v2 via sentence-transformers (384-dim, no API key needed)\n"
            "openai — text-embedding-3-large via OpenAI API (3072-dim, requires OPENAI_API_KEY)"
        ),
    )
    parser.add_argument("--openai-key", dest="openai_api_key", default=None,
                        help="OpenAI API key (falls back to OPENAI_API_KEY env var)")
    args = parser.parse_args()
    run(args.in_path, args.out_path, args.belief_path,
        do_labels=not args.no_labels,
        restrict_to_belief=args.restrict_to_belief,
        embedder=args.embedder,
        openai_api_key=args.openai_api_key)

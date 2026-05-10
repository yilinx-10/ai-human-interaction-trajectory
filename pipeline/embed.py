"""
Populate layer_topic.json with:
  - embedding: 384-dim sentence embedding vector
  - x, y: 2D UMAP projection for scatter plot
  - cluster_id: HDBSCAN cluster assignment (-1 = noise/outlier)
  - topic_label: short label from Claude

Usage:
    python -m pipeline.embed                         # uses ANTHROPIC_API_KEY env var
    python -m pipeline.embed --no-labels             # skip LLM labeling step
    python -m pipeline.embed --in processed/layer_topic.json --out processed/layer_topic.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def embed_texts(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer
    print("  Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print(f"  Encoding {len(texts)} conversations...")
    vecs = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)
    return vecs.tolist()


def reduce_umap(embeddings: list[list[float]], n_neighbors: int = 5, min_dist: float = 0.3) -> list[tuple[float, float]]:
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


def cluster_hdbscan(embeddings: list[list[float]], min_cluster_size: int = 2) -> list[int]:
    import numpy as np
    from sklearn.cluster import HDBSCAN

    print("  Running HDBSCAN clustering...")
    clusterer = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean")
    labels = clusterer.fit_predict(np.array(embeddings))
    n_clusters = len(set(labels) - {-1})
    n_noise = sum(1 for l in labels if l == -1)
    print(f"  Found {n_clusters} clusters, {n_noise} noise points")
    return [int(l) for l in labels]


def label_clusters(
    records: list[dict],
    api_key: str,
) -> dict[int, str]:
    """
    For each cluster, collect the conversation titles and ask Claude
    for a short 3-5 word topic label.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Group by cluster
    from collections import defaultdict
    clusters: dict[int, list[str]] = defaultdict(list)
    for r in records:
        cid = r.get("cluster_id", -1)
        if cid != -1:
            clusters[cid].append(r["title"])

    labels: dict[int, str] = {}
    for cid, titles in sorted(clusters.items()):
        titles_str = "\n".join(f"- {t}" for t in titles)
        prompt = (
            "Given these conversation titles from a user's AI chat history, "
            "give a single 3-5 word topic label that best summarizes the cluster. "
            "Reply with ONLY the label, nothing else.\n\n"
            f"Conversations:\n{titles_str}"
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        label = response.content[0].text.strip()
        labels[cid] = label
        print(f"  Cluster {cid}: {label}  ({len(titles)} convs)")

    return labels


def run(
    in_path: str = "processed/layer_topic.json",
    out_path: str = "processed/layer_topic.json",
    do_labels: bool = True,
) -> None:
    with open(in_path, encoding="utf-8") as f:
        records: list[dict] = json.load(f)

    # Only process records that have text
    active = [r for r in records if r.get("full_text")]
    print(f"[1/4] Embedding {len(active)} conversations")
    texts = [r["full_text"] for r in active]
    embeddings = embed_texts(texts)

    for r, emb in zip(active, embeddings):
        r["embedding"] = emb

    print("[2/4] UMAP 2D projection")
    coords = reduce_umap(embeddings)
    for r, (x, y) in zip(active, coords):
        r["x"] = x
        r["y"] = y

    print("[3/4] HDBSCAN clustering")
    cluster_ids = cluster_hdbscan(embeddings)
    for r, cid in zip(active, cluster_ids):
        r["cluster_id"] = cid

    if do_labels:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("[4/4] Skipping LLM labels (ANTHROPIC_API_KEY not set)")
        else:
            print("[4/4] Labeling clusters with Claude")
            cluster_labels = label_clusters(active, api_key)
            for r in active:
                cid = r.get("cluster_id", -1)
                r["topic_label"] = cluster_labels.get(cid, "Unclustered")
    else:
        print("[4/4] Skipping LLM labels (--no-labels)")

    # Write output
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", default="processed/layer_topic.json")
    parser.add_argument("--out", dest="out_path", default="processed/layer_topic.json")
    parser.add_argument("--no-labels", action="store_true")
    args = parser.parse_args()
    run(args.in_path, args.out_path, do_labels=not args.no_labels)

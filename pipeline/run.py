"""
Main pipeline entry point.

Usage:
    python -m pipeline.run
    python -m pipeline.run --data-dir test_data --out-dir processed
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .parse import load_export
from .normalize import normalize_conversations, normalize_projects
from .extract import (
    enrich_all,
    build_topic_layer,
    build_method_layer,
    build_message_layer,
    build_summary,
)


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  wrote {path}  ({path.stat().st_size // 1024} KB)")


def run(data_dir: str = "test_data", out_dir: str = "processed") -> None:
    data_path = Path(data_dir)
    out_path = Path(out_dir)

    print(f"[1/4] Loading export from {data_path}/")
    raw = load_export(data_path)

    print(f"[2/4] Normalizing {len(raw['conversations'])} conversations, "
          f"{len(raw['projects'])} projects")
    projects = normalize_projects(raw["projects"])
    conversations = normalize_conversations(raw["conversations"], projects)

    print("[3/4] Enriching conversations (text, stats)")
    conversations = enrich_all(conversations)

    print(f"[4/4] Writing outputs to {out_path}/")

    # Conversations with full text (for embedding / LLM extraction steps)
    write_json(out_path / "conversations.json",
               [c.to_dict(include_messages=False) for c in conversations])

    # Messages flat list (fine-grained timeline)
    write_json(out_path / "messages.json", build_message_layer(conversations))

    # Projects
    write_json(out_path / "projects.json", [p.to_dict() for p in projects])

    # Viz-layer scaffolds (embedding/LLM fields left as null for next steps)
    write_json(out_path / "layer_topic.json", build_topic_layer(conversations))
    write_json(out_path / "layer_method.json", build_method_layer(conversations))

    # Summary stats
    summary = build_summary(conversations)
    write_json(out_path / "summary.json", summary)

    print("\nDone. Summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI-Human interaction trajectory pipeline")
    parser.add_argument("--data-dir", default="test_data")
    parser.add_argument("--out-dir", default="processed")
    args = parser.parse_args()
    run(args.data_dir, args.out_dir)

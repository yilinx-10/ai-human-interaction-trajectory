"""
Convert Claude Code session JSON files into a processed/conversations.json
that beliefs.py (and the rest of the pipeline) can consume directly.

Claude Code exports one JSON file per conversation, organised in
project-named subdirectories.  Each file has the same chat_messages
schema as a standard Claude export, plus extra fields (source_type,
cwd, git_branch) that are preserved as metadata.

Usage:
    python -m pipeline.convert_claude_code \\
        --data-dir teammate-data/claude_code \\
        --out-dir  processed_teammate/claude_code

    # Only include "main" sessions (skip agent sub-sessions):
    python -m pipeline.convert_claude_code \\
        --data-dir teammate-data/claude_code \\
        --skip-agents

    # Include agent sub-sessions too:
    python -m pipeline.convert_claude_code \\
        --data-dir teammate-data/claude_code \\
        --include-agents
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_dt(s: str | None) -> str | None:
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.isoformat()
    except ValueError:
        return s


def _extract_text(content: Any) -> str:
    """Pull plain text from a message's content field (string or list of blocks)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    # tool results are noise for belief extraction — skip
                    pass
        return "\n".join(parts).strip()
    return ""


def _build_title(raw: dict, project_name: str, filename: str) -> str:
    name = (raw.get("name") or "").strip()
    if name:
        return name
    summary = (raw.get("summary") or "").strip()
    if summary:
        return summary[:80]
    return f"[{project_name}] {filename}"


def convert_file(path: Path, project_name: str) -> dict | None:
    """Convert a single Claude Code session JSON to a conversations.json record."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    conv_id = raw.get("uuid", path.stem)
    turns: list[dict] = []
    human_parts: list[str] = []
    ai_parts: list[str] = []

    for msg in raw.get("chat_messages", []):
        sender = msg.get("sender", "")
        text = msg.get("text") or _extract_text(msg.get("content") or [])
        text = text.strip()
        if not text:
            continue

        role = "human" if sender == "human" else "assistant"
        turns.append({"role": role, "text": text})
        if role == "human":
            human_parts.append(text)
        else:
            ai_parts.append(text)

    if not turns:
        return None

    human_turn_count = sum(1 for t in turns if t["role"] == "human")
    ai_turn_count    = sum(1 for t in turns if t["role"] == "assistant")

    # Estimate duration from first/last message timestamps
    msgs = raw.get("chat_messages", [])
    timestamps = [m.get("created_at") for m in msgs if m.get("created_at")]
    duration_minutes = 0.0
    if len(timestamps) >= 2:
        try:
            def _to_dt(s: str) -> datetime:
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                return datetime.fromisoformat(s)
            t0 = _to_dt(timestamps[0])
            t1 = _to_dt(timestamps[-1])
            duration_minutes = round(abs((t1 - t0).total_seconds()) / 60, 2)
        except Exception:
            pass

    interleaved = []
    for t in turns:
        prefix = "[HUMAN]" if t["role"] == "human" else "[ASSISTANT]"
        interleaved.append(f"{prefix} {t['text']}")

    return {
        "id":               conv_id,
        "title":            _build_title(raw, project_name, path.stem),
        "created_at":       _parse_dt(raw.get("created_at")),
        "updated_at":       _parse_dt(raw.get("updated_at")),
        "account_id":       None,
        "project_id":       None,
        "project_name":     project_name,
        "source_type":      raw.get("source_type"),
        "cwd":              raw.get("cwd"),
        "git_branch":       raw.get("git_branch"),
        "human_turn_count": human_turn_count,
        "ai_turn_count":    ai_turn_count,
        "total_turn_count": human_turn_count + ai_turn_count,
        "duration_minutes": duration_minutes,
        "human_text":       "\n\n".join(human_parts),
        "ai_text":          "\n\n".join(ai_parts),
        "full_text":        "\n\n".join(interleaved),
        "turns":            turns,
    }


def convert_directory(
    data_dir: Path,
    include_agents: bool = False,
) -> list[dict]:
    """Walk all project subdirectories and convert every eligible session file."""
    conversations: list[dict] = []

    for project_dir in sorted(data_dir.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        project_name = project_dir.name

        for json_file in sorted(project_dir.glob("*.json")):
            is_agent = "__agent" in json_file.stem
            if is_agent and not include_agents:
                continue

            record = convert_file(json_file, project_name)
            if record is None:
                print(f"  skip (no messages): {json_file.name}")
                continue
            conversations.append(record)

    # Sort chronologically
    conversations.sort(key=lambda c: c.get("created_at") or "")
    return conversations


def run(
    data_dir: str = "teammate-data/claude_code",
    out_dir: str  = "processed_teammate/claude_code",
    include_agents: bool = False,
) -> None:
    src = Path(data_dir)
    dst = Path(out_dir)
    dst.mkdir(parents=True, exist_ok=True)

    print(f"Converting Claude Code sessions from {src}/")
    conversations = convert_directory(src, include_agents=include_agents)

    out_path = dst / "conversations.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(conversations, f, indent=2, ensure_ascii=False)

    by_project: dict[str, int] = {}
    for c in conversations:
        p = c.get("project_name", "unknown")
        by_project[p] = by_project.get(p, 0) + 1

    print(f"\nWrote {out_path}  ({out_path.stat().st_size // 1024} KB)")
    print(f"Total conversations: {len(conversations)}")
    print("By project:")
    for proj, count in sorted(by_project.items()):
        print(f"  {proj}: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="teammate-data/claude_code")
    parser.add_argument("--out-dir",  default="processed_teammate/claude_code")
    parser.add_argument("--include-agents", action="store_true",
                        help="Also include agent sub-session files (default: skip)")
    args = parser.parse_args()
    run(args.data_dir, args.out_dir, args.include_agents)

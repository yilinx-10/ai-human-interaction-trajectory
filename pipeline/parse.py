"""
Load and validate raw Claude conversation export JSON files.
"""
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_projects(data_dir: Path) -> list[dict]:
    """Load projects from either projects.json or a projects/ directory."""
    flat_file = data_dir / "projects.json"
    if flat_file.exists():
        return load_json(flat_file)
    projects_dir = data_dir / "projects"
    if projects_dir.is_dir():
        records = []
        for p in sorted(projects_dir.iterdir()):
            if p.suffix == ".json":
                records.append(load_json(p))
        return records
    return []


def load_export(data_dir: str | Path) -> dict[str, Any]:
    """Load all four export files and return as a dict of raw records."""
    data_dir = Path(data_dir)
    raw: dict[str, Any] = {}

    for key, filename in [("conversations", "conversations.json"),
                          ("users", "users.json"),
                          ("memories", "memories.json")]:
        path = data_dir / filename
        if not path.exists():
            # Allow missing users/memories with empty fallback
            if key == "conversations":
                raise FileNotFoundError(f"Expected export file not found: {path}")
            raw[key] = []
            continue
        raw[key] = load_json(path)

    raw["projects"] = _load_projects(data_dir)

    # Basic shape validation
    assert isinstance(raw["conversations"], list), "conversations.json must be a list"
    assert isinstance(raw["users"], list), "users.json must be a list"
    assert isinstance(raw["memories"], list), "memories.json must be a list"
    assert isinstance(raw["projects"], list), "projects must be a list"

    return raw

"""
Load and validate raw Claude conversation export JSON files.
"""
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_export(data_dir: str | Path) -> dict[str, Any]:
    """Load all four export files and return as a dict of raw records."""
    data_dir = Path(data_dir)
    files = {
        "conversations": "conversations.json",
        "users": "users.json",
        "memories": "memories.json",
        "projects": "projects.json",
    }
    raw: dict[str, Any] = {}
    for key, filename in files.items():
        path = data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Expected export file not found: {path}")
        raw[key] = load_json(path)

    # Basic shape validation
    assert isinstance(raw["conversations"], list), "conversations.json must be a list"
    assert isinstance(raw["users"], list), "users.json must be a list"
    assert isinstance(raw["memories"], list), "memories.json must be a list"
    assert isinstance(raw["projects"], list), "projects.json must be a list"

    return raw

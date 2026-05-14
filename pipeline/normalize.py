"""
Normalize raw Claude export records into clean, typed dataclasses.

ConversationRecord  — one per conversation
MessageRecord       — one per chat message
ProjectRecord       — one per project
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    # Normalize both "...Z" and "...+00:00" to a form fromisoformat accepts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _extract_text(content: list[dict]) -> str:
    """Pull plain text out of a message's content array."""
    parts: list[str] = []
    for block in content:
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_result":
            # tool_result content can be a string or a nested content array
            inner = block.get("content", "")
            if isinstance(inner, str):
                parts.append(inner)
            elif isinstance(inner, list):
                parts.append(_extract_text(inner))
    return "\n".join(parts).strip()


@dataclass
class MessageRecord:
    id: str
    conversation_id: str
    sender: str                  # "human" | "assistant"
    text: str
    created_at: datetime | None
    turn_index: int              # 0-based position in the conversation
    parent_message_id: str | None
    has_attachments: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "sender": self.sender,
            "text": self.text,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "turn_index": self.turn_index,
            "parent_message_id": self.parent_message_id,
            "has_attachments": self.has_attachments,
        }


@dataclass
class ConversationRecord:
    id: str
    title: str
    created_at: datetime | None
    updated_at: datetime | None
    account_id: str | None
    project_id: str | None        # matched from projects list if possible
    messages: list[MessageRecord] = field(default_factory=list)

    # Derived fields populated by extract.py
    human_text: str = ""          # concatenated human turns
    ai_text: str = ""             # concatenated assistant turns
    full_text: str = ""           # all turns interleaved
    duration_minutes: float = 0.0
    human_turn_count: int = 0
    ai_turn_count: int = 0

    def to_dict(self, include_messages: bool = False) -> dict:
        d = {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "account_id": self.account_id,
            "project_id": self.project_id,
            "human_turn_count": self.human_turn_count,
            "ai_turn_count": self.ai_turn_count,
            "total_turn_count": self.human_turn_count + self.ai_turn_count,
            "duration_minutes": round(self.duration_minutes, 2),
            "human_text": self.human_text,
            "ai_text": self.ai_text,
            "full_text": self.full_text,
            "turns": [
                {"role": m.sender, "text": m.text}
                for m in self.messages
                if m.text.strip()
            ],
        }
        if include_messages:
            d["messages"] = [m.to_dict() for m in self.messages]
        return d


@dataclass
class ProjectRecord:
    id: str
    name: str
    description: str
    created_at: datetime | None
    updated_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def normalize_projects(raw_projects: list[dict]) -> list[ProjectRecord]:
    records = []
    for p in raw_projects:
        records.append(ProjectRecord(
            id=p.get("uuid", ""),
            name=p.get("name", ""),
            description=p.get("description") or "",
            created_at=_parse_dt(p.get("created_at")),
            updated_at=_parse_dt(p.get("updated_at")),
        ))
    return records


def normalize_conversations(
    raw_conversations: list[dict],
    projects: list[ProjectRecord] | None = None,
) -> list[ConversationRecord]:
    """Convert raw conversation dicts to ConversationRecord objects."""
    project_names_by_id = {p.id: p.name for p in (projects or [])}

    records: list[ConversationRecord] = []
    for raw in raw_conversations:
        conv_id = raw.get("uuid", "")
        account_id = (raw.get("account") or {}).get("uuid")

        messages: list[MessageRecord] = []
        for idx, msg in enumerate(raw.get("chat_messages", [])):
            # Prefer pre-flattened text field; fall back to content blocks
            text = msg.get("text") or _extract_text(msg.get("content") or [])
            messages.append(MessageRecord(
                id=msg.get("uuid", ""),
                conversation_id=conv_id,
                sender=msg.get("sender", ""),
                text=text,
                created_at=_parse_dt(msg.get("created_at")),
                turn_index=idx,
                parent_message_id=msg.get("parent_message_uuid"),
                has_attachments=bool(msg.get("attachments") or msg.get("files")),
            ))

        record = ConversationRecord(
            id=conv_id,
            title=raw.get("name", "").strip() or "(untitled)",
            created_at=_parse_dt(raw.get("created_at")),
            updated_at=_parse_dt(raw.get("updated_at")),
            account_id=account_id,
            project_id=None,  # Claude export doesn't link conversations → projects directly
            messages=messages,
        )
        records.append(record)

    # Sort chronologically
    records.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc))
    return records

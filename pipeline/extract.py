"""
Derive per-conversation features from normalized records.

Populates:
  - human_text / ai_text / full_text
  - duration_minutes, human_turn_count, ai_turn_count
  - Produces viz-ready output dicts for each visualization layer

Three output structures (one per proposal layer):

  topic_layer     — one record per conversation for embedding/scatter plot
  method_layer    — timeline records (one per conversation)
  message_layer   — flat message records for fine-grained timeline
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .normalize import ConversationRecord, MessageRecord


# ---------------------------------------------------------------------------
# Feature derivation
# ---------------------------------------------------------------------------

def enrich_conversation(conv: ConversationRecord) -> ConversationRecord:
    """Fill derived text and stat fields in-place."""
    human_parts: list[str] = []
    ai_parts: list[str] = []
    full_parts: list[str] = []

    for msg in conv.messages:
        text = msg.text.strip()
        if not text:
            continue
        prefix = f"[{msg.sender.upper()}]"
        full_parts.append(f"{prefix} {text}")
        if msg.sender == "human":
            human_parts.append(text)
        else:
            ai_parts.append(text)

    conv.human_text = "\n\n".join(human_parts)
    conv.ai_text = "\n\n".join(ai_parts)
    conv.full_text = "\n\n".join(full_parts)
    conv.human_turn_count = sum(1 for m in conv.messages if m.sender == "human")
    conv.ai_turn_count = sum(1 for m in conv.messages if m.sender == "assistant")

    # Duration: time between first and last message
    timestamps = [m.created_at for m in conv.messages if m.created_at]
    if len(timestamps) >= 2:
        delta = max(timestamps) - min(timestamps)
        conv.duration_minutes = delta.total_seconds() / 60.0

    return conv


def enrich_all(conversations: list[ConversationRecord]) -> list[ConversationRecord]:
    return [enrich_conversation(c) for c in conversations]


# ---------------------------------------------------------------------------
# Viz-layer output builders
# ---------------------------------------------------------------------------

def build_topic_layer(conversations: list[ConversationRecord]) -> list[dict]:
    """
    One record per conversation.
    Used for the Topic scatter plot (embedding-based).
    The `full_text` field is what gets fed to the embedding model.
    Fields left null here are populated downstream:
      - short_title, short_summary  ← pipeline.beliefs → pipeline.embed
      - embedding, x, y             ← pipeline.embed (UMAP)
      - topic_label, cluster_id, root_cluster_idx ← pipeline.embed (Ward tree)
    """
    records = []
    for c in conversations:
        if not c.full_text:
            continue
        records.append({
            "id": c.id,
            "title": c.title,
            "date": c.created_at.date().isoformat() if c.created_at else None,
            "timestamp": c.created_at.isoformat() if c.created_at else None,
            "human_turn_count": c.human_turn_count,
            "ai_turn_count": c.ai_turn_count,
            "duration_minutes": c.duration_minutes,
            # Populated by pipeline.beliefs + pipeline.embed
            "short_title": None,
            "short_summary": None,
            # Populated by pipeline.embed
            "embedding": None,
            "topic_label": None,
            "cluster_id": None,
            "root_cluster_idx": None,
            "x": None,
            "y": None,
            # Text inputs for LLM / embedding steps
            "full_text": c.full_text,
            "human_text": c.human_text,
        })
    return records


def build_message_layer(conversations: list[ConversationRecord]) -> list[dict]:
    """
    Flat list of all messages across all conversations.
    Enables fine-grained timeline and turn-level analysis.
    """
    records = []
    for c in conversations:
        for msg in c.messages:
            records.append({
                **msg.to_dict(),
                "conversation_title": c.title,
                "conversation_date": c.created_at.date().isoformat() if c.created_at else None,
            })
    return records


def build_summary(conversations: list[ConversationRecord]) -> dict:
    """Aggregate stats across all conversations."""
    dates = [c.created_at.date() for c in conversations if c.created_at]
    total_msgs = sum(c.human_turn_count + c.ai_turn_count for c in conversations)
    return {
        "total_conversations": len(conversations),
        "total_messages": total_msgs,
        "date_range": {
            "start": min(dates).isoformat() if dates else None,
            "end": max(dates).isoformat() if dates else None,
        },
        "avg_turns_per_conversation": round(total_msgs / len(conversations), 1) if conversations else 0,
        "avg_duration_minutes": round(
            sum(c.duration_minutes for c in conversations) / len(conversations), 1
        ) if conversations else 0,
        "conversations_with_no_messages": sum(
            1 for c in conversations if c.human_turn_count + c.ai_turn_count == 0
        ),
    }

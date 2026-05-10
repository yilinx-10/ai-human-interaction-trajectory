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
import time
from pathlib import Path

import anthropic

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
    supports     — source provides evidence or justification for target
    contradicts  — source conflicts with or undermines target
    elaborates   — source qualifies or refines target
    causes       — source produces target as an outcome or consequence
    alternatives — source and target are competing options for the same goal
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
                        }
                    },
                    "required": ["id", "type", "origin", "text_long", "text_short"]
                }
            },
            "edges": {
                "type": "array",
                "description": "Logical relationships between belief nodes.",
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
                            "enum": ["supports", "contradicts", "elaborates", "causes", "alternatives"],
                            "description": "Logical relationship: supports=justifies target, contradicts=conflicts with target, elaborates=qualifies/refines target, causes=produces target as outcome, alternatives=competing options for same goal"
                        }
                    },
                    "required": ["source", "target", "relation"]
                }
            }
        },
        "required": ["nodes", "edges"]
    }
}

# Enum values used in stats — single source of truth
NODE_TYPES      = ("claim", "evidence", "conclusion", "constraint")
EDGE_RELATIONS  = ("supports", "contradicts", "elaborates", "causes", "alternatives")
ORIGINS         = ("user", "model", "co-constructed")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_turns(turns: list[dict]) -> str:
    """
    Format a list of {role, text} turn dicts into a labelled transcript.
    If a single-entry turn already contains a pre-formatted transcript
    (i.e. full_text with [HUMAN]/[ASSISTANT] markers), pass it through as-is.
    """
    if len(turns) == 1:
        text = turns[0].get("text", "")
        if "[HUMAN]" in text or "[ASSISTANT]" in text:
            return text
    lines = []
    for t in turns:
        speaker = "USER" if t["role"] == "human" else "ASSISTANT"
        lines.append(f"[{speaker}] {t['text'].strip()}")
    return "\n\n".join(lines)


def _prefix_ids(network: dict, conv_id: str) -> dict:
    """Namespace node ids with conversation id to avoid collisions in the global graph."""
    prefix = conv_id[:8]

    # Assign synthetic ids to any nodes that came back without one
    for i, node in enumerate(network.get("nodes", [])):
        if not node.get("id"):
            node["id"] = f"n{i+1}"

    # Drop nodes still missing required fields after recovery
    valid_nodes = [
        n for n in network.get("nodes", [])
        if n.get("id") and n.get("text_long")
    ]

    id_map = {n["id"]: f"{prefix}_{n['id']}" for n in valid_nodes}
    nodes = [
        {**n, "id": id_map[n["id"]], "text": n.get("text_long", n.get("text", ""))}
        for n in valid_nodes
    ]

    edges = [
        {
            **e,
            "source": id_map.get(e["source"], e["source"]),
            "target": id_map.get(e["target"], e["target"]),
        }
        for e in network.get("edges", [])
        if e.get("source") in id_map and e.get("target") in id_map
    ]
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_one(
    client: anthropic.Anthropic,
    conv_id: str,
    title: str,
    turns: list[dict],
) -> dict:
    """
    Call Claude to extract a belief network from one conversation.

    `turns` is a list of {role: 'human'|'assistant', text: str} dicts
    in chronological order.
    """
    transcript = _format_turns(turns)
    user_msg = (
        f"Conversation title: {title}\n\n"
        f"Transcript:\n{transcript}"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
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


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run(
    conversations_path: str = "processed/conversations.json",
    out_path: str = "processed/layer_belief.json",
    limit: int | None = None,
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
    if limit:
        eligible = eligible[:limit]

    print(
        f"Extracting beliefs from {len(eligible)} conversations "
        f"(skipped {len(conversations) - len(eligible)} with no content)"
    )

    client = anthropic.Anthropic()

    per_conversation: list[dict] = []
    global_nodes:     list[dict] = []
    global_edges:     list[dict] = []

    for i, conv in enumerate(eligible):
        print(f"  [{i+1}/{len(eligible)}] {conv['title'][:60]}")

        # Support turn-based, full_text transcript, or legacy human_text-only format
        turns = (
            conv.get("turns")
            or [{"role": "human", "text": conv.get("full_text") or conv.get("human_text", "")}]
        )

        try:
            raw = extract_one(client, conv["id"], conv["title"], turns)
        except Exception as e:
            print(f"    ERROR: {e}")
            raw = {"nodes": [], "edges": []}

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

        print(
            f"    → {len(namespaced['nodes'])} nodes, "
            f"{len(namespaced['edges'])} edges"
        )

        if i < len(eligible) - 1:
            time.sleep(0.3)

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
            # Use actual schema enums — no stale keys
            "node_type_counts": {
                t: sum(1 for n in global_nodes if n.get("type") == t)
                for t in NODE_TYPES
            },
            "edge_relation_counts": {
                r: sum(1 for e in global_edges if e.get("relation") == r)
                for r in EDGE_RELATIONS
            },
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
    print(f"Node types:  {stats['node_type_counts']}")
    print(f"Edge types:  {stats['edge_relation_counts']}")
    print(f"Origins:     {stats['origin_counts']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversations", default="processed/conversations.json")
    parser.add_argument("--out",           default="processed/layer_belief.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N conversations (for testing)")
    args = parser.parse_args()
    run(args.conversations, args.out, args.limit)
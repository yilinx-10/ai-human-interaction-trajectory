#!/usr/bin/env bash
# Run the full ChatTrajectory pipeline and copy outputs to the frontend.
#
# Usage:
#   ./pipeline.sh                          # full run (all conversations)
#   ./pipeline.sh --data-dir my_export     # custom input folder
#   ./pipeline.sh --no-labels              # skip LLM cluster naming
#   ./pipeline.sh --limit 10              # beliefs extraction on first 10 convs only
#   ./pipeline.sh --sample-size 50         # randomly sample 50 convs for beliefs
#
# Requires:
#   ANTHROPIC_API_KEY, OPENAI_API_KEY in environment (used by pipeline.beliefs and pipeline.embed)
#   Python packages: sentence-transformers, umap-learn, scipy, anthropic

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
DATA_DIR="test_data"
OUT_DIR="processed"
FRONTEND_DATA="frontend/public/data"
NO_LABELS=""
LIMIT=""
SAMPLE_SIZE=""

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir)    DATA_DIR="$2";    shift 2 ;;
    --out-dir)     OUT_DIR="$2";     shift 2 ;;
    --no-labels)   NO_LABELS="--no-labels"; shift ;;
    --limit)       LIMIT="--limit $2"; shift 2 ;;
    --sample-size) SAMPLE_SIZE="--sample-size $2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
step() { echo; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "  $*"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }

# ── API key ───────────────────────────────────────────────────────────────────
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  read -rsp "Anthropic API key: " ANTHROPIC_API_KEY
  echo
  export ANTHROPIC_API_KEY
fi

# ── Step 1: parse / normalize / extract ──────────────────────────────────────
step "Step 1/3  parse → normalize → extract  (pipeline.run)"
python -m pipeline.run --data-dir "$DATA_DIR" --out-dir "$OUT_DIR"

# ── Step 2: belief network extraction ────────────────────────────────────────
step "Step 2/3  belief network extraction  (pipeline.beliefs)"
# shellcheck disable=SC2086
python -m pipeline.beliefs \
  --conversations "$OUT_DIR/conversations.json" \
  --out "$OUT_DIR/layer_belief.json" \
  $LIMIT \
  $SAMPLE_SIZE

# ── Step 3: embeddings + UMAP + Ward clustering ───────────────────────────────
step "Step 3/3  embed → UMAP → cluster → label  (pipeline.embed)"
# shellcheck disable=SC2086
python -m pipeline.embed \
  --in  "$OUT_DIR/layer_topic.json" \
  --out "$OUT_DIR/layer_topic.json" \
  --belief "$OUT_DIR/layer_belief.json" \
  $NO_LABELS

# ── Copy to frontend ──────────────────────────────────────────────────────────
step "Copying outputs → $FRONTEND_DATA/"
mkdir -p "$FRONTEND_DATA"
cp "$OUT_DIR/layer_topic.json"  "$FRONTEND_DATA/"
cp "$OUT_DIR/layer_belief.json" "$FRONTEND_DATA/"
cp "$OUT_DIR/summary.json"      "$FRONTEND_DATA/"

echo
echo "Done. Files in $FRONTEND_DATA/:"
ls -lh "$FRONTEND_DATA/"

#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DIST_DIR="$PROJECT_DIR/dist"
STAGE_DIR="$DIST_DIR/paper-research-agents-v0.1.0"
ARCHIVE="$DIST_DIR/paper-research-agents-v0.1.0.zip"

rm -rf "$STAGE_DIR"
rm -f "$ARCHIVE"
mkdir -p "$STAGE_DIR/data"

rsync -a \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '*.egg-info/' \
  --exclude 'data/' \
  --exclude 'dist/' \
  --exclude 'package/' \
  --exclude '包/' \
  "$PROJECT_DIR/" "$STAGE_DIR/"

cp "$PROJECT_DIR/data/README.md" "$STAGE_DIR/data/README.md"
(cd "$DIST_DIR" && zip -qr "$(basename "$ARCHIVE")" "$(basename "$STAGE_DIR")")

printf '%s\n' "已生成：$ARCHIVE"

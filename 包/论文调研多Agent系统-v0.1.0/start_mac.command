#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -e '.[ui]'
export GRADIO_SERVER_NAME=127.0.0.1
export GRADIO_SERVER_PORT=7860
.venv/bin/paper-agents-ui

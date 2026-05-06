#!/bin/sh
# Purpose: Create experiment/tool/.venv and install experiment/tool/requirements.txt
# (matplotlib stack and mypy). Plot rules in the top-level Makefile invoke python3 on the host.
# Interface: run from repository root: sh experiment/tool/setup_venv.sh

set -eu

TOOL_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
VENV="${TOOL_DIR}/.venv"
REQ="${TOOL_DIR}/requirements.txt"

python3 -m venv "${VENV}"
"${VENV}/bin/pip" install -r "${REQ}"

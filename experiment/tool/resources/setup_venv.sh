#!/bin/sh
# Purpose: Create experiment/tool/.venv and install requirements.txt in this directory.
# Plot rules in the top-level Makefile invoke python3 on the host.
# Interface: run from repository root: sh experiment/tool/resources/setup_venv.sh

set -eu

RES_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
VENV="$(CDPATH= cd -- "${RES_DIR}/.." && pwd)/.venv"
REQ="${RES_DIR}/requirements.txt"

python3 -m venv "${VENV}"
"${VENV}/bin/pip" install -r "${REQ}"

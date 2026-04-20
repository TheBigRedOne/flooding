#!/bin/sh

# Purpose: Run one experiment collection workflow and validate the resulting
# host-side directory structure for downstream analysis.
# Interface: PROVIDER=<provider> [MOBILITY_LOG_NODES="<nodes>"]
# [CLEAR_LOCAL_RESULTS=1] [NLSR_HELLO_INTERVAL=<seconds>]
# [NLSR_ADJ_LSA_BUILD_INTERVAL=<seconds>]
# [NLSR_ROUTING_CALC_INTERVAL=<seconds>] [NLSR_TUNING_PROFILE=<name>]
# sh scripts/run-result-collection.sh <vagrant_dir> <host_alias> <ssh_config>
# <box_env_name> <box_path> <source_dir> <remote_dir> <experiment_subdir>
# <local_results_dir> [--require-params]

set -eu

if [ $# -lt 9 ] || [ $# -gt 10 ]; then
  echo "Usage: $0 <vagrant_dir> <host_alias> <ssh_config> <box_env_name> <box_path> <source_dir> <remote_dir> <experiment_subdir> <local_results_dir> [--require-params]"
  exit 1
fi

VAGRANT_DIR=$1
HOST_ALIAS=$2
SSH_CONFIG=$3
BOX_ENV_NAME=$4
BOX_PATH=$5
SOURCE_DIR=$6
REMOTE_DIR=$7
EXPERIMENT_SUBDIR=$8
LOCAL_RESULTS_DIR=$9
REQUIRE_PARAMS=${10:-}

sh scripts/run-experiment-vm.sh \
  "$VAGRANT_DIR" \
  "$HOST_ALIAS" \
  "$SSH_CONFIG" \
  "$BOX_ENV_NAME" \
  "$BOX_PATH" \
  "$SOURCE_DIR" \
  "$REMOTE_DIR" \
  "$EXPERIMENT_SUBDIR" \
  "$LOCAL_RESULTS_DIR"

if [ "$REQUIRE_PARAMS" = "--require-params" ]; then
  python3 scripts/validate_result_dir.py --result-dir "$LOCAL_RESULTS_DIR" --require-params
else
  python3 scripts/validate_result_dir.py --result-dir "$LOCAL_RESULTS_DIR"
fi

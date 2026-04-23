#!/bin/sh

# Purpose: Run one experiment collection workflow and validate the resulting
# host-side directory structure for downstream analysis.
# Interface: PROVIDER=<provider> [MOBILITY_LOG_NODES="<nodes>"]
# [CLEAR_LOCAL_RESULTS=1] [NLSR_HELLO_INTERVAL=<seconds>]
# [NLSR_ADJ_LSA_BUILD_INTERVAL=<seconds>]
# [NLSR_ROUTING_CALC_INTERVAL=<seconds>] [NLSR_TUNING_PROFILE=<name>]
# sh scripts/run-result-collection.sh <vagrant_dir> <host_alias> <ssh_config>
# <box_env_name> <box_path> <source_dir> <remote_dir> <experiment_subdir>
# <local_results_dir> [--mode <raw|derived>] [--pcap-nodes <comma-separated-nodes>]
# [--require-params]

set -eu

if [ $# -lt 9 ]; then
  echo "Usage: $0 <vagrant_dir> <host_alias> <ssh_config> <box_env_name> <box_path> <source_dir> <remote_dir> <experiment_subdir> <local_results_dir> [--mode <raw|derived>] [--pcap-nodes <comma-separated-nodes>] [--require-params]"
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
shift 9

VALIDATION_MODE=raw
PCAP_NODES=
REQUIRE_PARAMS=

while [ $# -gt 0 ]; do
  case "$1" in
    --mode)
      VALIDATION_MODE=$2
      shift 2
      ;;
    --pcap-nodes)
      PCAP_NODES=$2
      shift 2
      ;;
    --require-params)
      REQUIRE_PARAMS=--require-params
      shift 1
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

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

set -- --mode "$VALIDATION_MODE" --result-dir "$LOCAL_RESULTS_DIR"
if [ -n "$PCAP_NODES" ]; then
  set -- "$@" --pcap-nodes "$PCAP_NODES"
fi
if [ "$REQUIRE_PARAMS" = "--require-params" ]; then
  set -- "$@" --require-params
fi

python3 scripts/validate_result_dir.py "$@"

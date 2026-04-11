#!/bin/sh

# Purpose: Run one experiment workflow in a Vagrant VM and synchronise inputs
# and outputs between the host repository and the guest working directory.
# Interface: PROVIDER=<provider> [MOBILITY_LOG_NODES="<nodes>"]
# [CLEAR_LOCAL_RESULTS=1] [NLSR_HELLO_INTERVAL=<seconds>]
# [NLSR_ADJ_LSA_BUILD_INTERVAL=<seconds>]
# [NLSR_ROUTING_CALC_INTERVAL=<seconds>] [NLSR_TUNING_PROFILE=<name>]
# sh scripts/run-experiment-vm.sh <vagrant_dir> <host_alias> <ssh_config>
# <box_env_name> <box_path> <source_dir> <remote_dir> <experiment_subdir>
# <local_results_dir>

set -eu

if [ $# != 9 ]; then
  echo "Usage: $0 <vagrant_dir> <host_alias> <ssh_config> <box_env_name> <box_path> <source_dir> <remote_dir> <experiment_subdir> <local_results_dir>"
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

if [ x"${PROVIDER:-}" = x ]; then
  echo "Cannot run experiment VM workflow: provider is not set"
  exit 1
fi

run_vagrant() {
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$VAGRANT_DIR vagrant "$@"
}

if [ -n "${NLSR_TUNING_PROFILE:-}" ]; then
  : "${NLSR_HELLO_INTERVAL:?NLSR_HELLO_INTERVAL is not set}"
  : "${NLSR_ADJ_LSA_BUILD_INTERVAL:?NLSR_ADJ_LSA_BUILD_INTERVAL is not set}"
  : "${NLSR_ROUTING_CALC_INTERVAL:?NLSR_ROUTING_CALC_INTERVAL is not set}"
  REMOTE_MAKE_CMD="NLSR_HELLO_INTERVAL=$NLSR_HELLO_INTERVAL NLSR_ADJ_LSA_BUILD_INTERVAL=$NLSR_ADJ_LSA_BUILD_INTERVAL NLSR_ROUTING_CALC_INTERVAL=$NLSR_ROUTING_CALC_INTERVAL NLSR_TUNING_PROFILE=$NLSR_TUNING_PROFILE make all"
else
  REMOTE_MAKE_CMD="make all"
fi

echo "*** Running experiment VM workflow: $EXPERIMENT_SUBDIR ($PROVIDER, dir=$VAGRANT_DIR)"

env "$BOX_ENV_NAME=$BOX_PATH" \
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER \
  VAGRANT_CWD=$VAGRANT_DIR \
  vagrant up --provision

run_vagrant ssh-config --host "$HOST_ALIAS" > "$SSH_CONFIG"

rsync -avH -e "ssh -F $SSH_CONFIG" \
  --exclude .git \
  --exclude .vagrant \
  --exclude results \
  --exclude paper/bin \
  "$SOURCE_DIR" "$HOST_ALIAS:$REMOTE_DIR/"

if [ x"${CLEAR_LOCAL_RESULTS:-}" = x1 ]; then
  rm -rf "$LOCAL_RESULTS_DIR"/*
fi

run_vagrant ssh -c "set -e; \
cd $REMOTE_DIR/$EXPERIMENT_SUBDIR && make clean && $REMOTE_MAKE_CMD; \
mkdir -p results/minindn-logs; \
if [ -d /tmp/minindn ]; then \
  for name in ${MOBILITY_LOG_NODES:-}; do \
    node=/tmp/minindn/\$name; \
    if [ -d \"\$node/log\" ]; then \
      mkdir -p \"results/minindn-logs/\$name\"; \
      cp -f \"\$node/log/nfd.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; \
      cp -f \"\$node/log/nlsr.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; \
    fi; \
  done; \
fi"

rsync -avH -e "ssh -F $SSH_CONFIG" \
  "$HOST_ALIAS:$REMOTE_DIR/$EXPERIMENT_SUBDIR/results/." "$LOCAL_RESULTS_DIR/"

run_vagrant halt -f || true

echo ""
echo "*** Finished experiment VM workflow: $EXPERIMENT_SUBDIR ($PROVIDER, dir=$VAGRANT_DIR)"
echo ""

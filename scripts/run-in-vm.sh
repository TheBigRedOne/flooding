#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
  echo "usage: sh scripts/run-in-vm.sh <box> [make-dependencies...] <target>" >&2
  exit 2
fi

box_path=$1
shift

target_output=
for arg in "$@"; do
  target_output=$arg
done

result_dir=$(dirname "$target_output")
if [ "$(basename "$result_dir")" = "pcap_nodes" ]; then
  result_dir=$(dirname "$result_dir")
fi

provider=${PROVIDER:-virtualbox}
remote_dir=${REMOTE_DIR:-/home/vagrant/flooding}
mobility_log_nodes=${MOBILITY_LOG_NODES:-"core agg1 agg2 acc1 acc2 acc3 acc4 acc5 acc6 producer consumer"}

case "$box_path" in
  */box/solution/*|box/solution/*)
    experiment=solution
    host_alias=solution
    vagrant_dir=experiment/solution
    box_env_name=ACTUAL_SOLUTION_BOX_PATH
    remote_subdir=experiment/solution
    remote_make=${RUN_IN_VM_REMOTE_MAKE:-"make all"}
    ;;
  */box/baseline/*|box/baseline/*)
    experiment=baseline
    host_alias=baseline
    vagrant_dir=experiment/baseline
    box_env_name=ACTUAL_BASELINE_BOX_PATH
    remote_subdir=experiment/baseline
    remote_make=${RUN_IN_VM_REMOTE_MAKE:?RUN_IN_VM_REMOTE_MAKE is required for baseline runs}
    ;;
  *)
    echo "unsupported experiment box: $box_path" >&2
    exit 2
    ;;
esac

ssh_config=${RUN_IN_VM_SSH_CONFIG:-.ssh_config_${experiment}}

echo "*** Running experiment VM workflow: $remote_subdir ($provider, dir=$vagrant_dir)"

env "$box_env_name=$box_path" VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant up --provision
VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant ssh-config --host "$host_alias" > "$ssh_config"

# Inject SSH keepalive so long, output-quiet remote runs survive NAT/conntrack idle drops and remote sshd ClientAlive timeouts.
{
  echo "    ServerAliveInterval 30"
  echo "    ServerAliveCountMax 120"
  echo "    TCPKeepAlive yes"
} >> "$ssh_config"
rsync -avH -e "ssh -F $ssh_config" --exclude .git --exclude .vagrant --exclude results --exclude paper/bin ./ "$host_alias:$remote_dir/"

mkdir -p "$result_dir"
if [ "${RUN_IN_VM_CLEAR_LOCAL:-}" = "1" ]; then
  rm -rf "$result_dir"/*
fi

# Use ssh -F directly so the keepalive options appended to $ssh_config above take effect on the long-running command.
ssh -F "$ssh_config" "$host_alias" "set -e; cd $remote_dir/$remote_subdir && make clean && $remote_make; mkdir -p results/minindn-logs; if [ -d /tmp/minindn ]; then for name in $mobility_log_nodes; do node=/tmp/minindn/\$name; if [ -d \"\$node/log\" ]; then mkdir -p \"results/minindn-logs/\$name\"; cp -f \"\$node/log/nfd.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; cp -f \"\$node/log/nlsr.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; fi; done; fi"

rsync -avH -e "ssh -F $ssh_config" "$host_alias:$remote_dir/$remote_subdir/results/." "$result_dir/"
VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant halt -f || true

echo ""
echo "*** Finished experiment VM workflow: $remote_subdir ($provider, dir=$vagrant_dir)"
echo ""

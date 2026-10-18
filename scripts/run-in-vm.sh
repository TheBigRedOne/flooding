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
profile=${RUN_IN_VM_PROFILE:-}

if [ "$profile" = "exp2" ]; then
  experiment=exp2
  host_alias=exp2
  vagrant_dir=experiment/extended/exp2
  box_env_name=ACTUAL_SOLUTION_BOX_PATH
  remote_subdir=experiment/extended/exp2
  remote_make=${RUN_IN_VM_REMOTE_MAKE:?RUN_IN_VM_REMOTE_MAKE is required for exp2}
elif [ "$profile" = "exp3" ]; then
  experiment=exp3
  host_alias=exp3
  vagrant_dir=experiment/extended/exp3
  box_env_name=ACTUAL_SOLUTION_BOX_PATH
  remote_subdir=experiment/extended/exp3
  remote_make=${RUN_IN_VM_REMOTE_MAKE:?RUN_IN_VM_REMOTE_MAKE is required for exp3}
elif [ -n "$profile" ]; then
  echo "unsupported RUN_IN_VM_PROFILE: $profile" >&2
  exit 2
else
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
fi

ssh_config=${RUN_IN_VM_SSH_CONFIG:-.ssh_config_${experiment}}

if [ "$experiment" = "exp2" ]; then
  if [ -d "$result_dir" ]; then
    for entry in "$result_dir"/*; do
      if [ -e "$entry" ] || [ -L "$entry" ]; then
        echo "refusing to replace existing Exp2 results: $result_dir" >&2
        echo "choose a new run directory or remove this one explicitly" >&2
        exit 1
      fi
    done
  fi
  exp2_lock=${RUN_IN_VM_LOCK:-.exp2-vm.lock}
  if ! mkdir "$exp2_lock" 2>/dev/null; then
    echo "Exp2 VM is already in use ($exp2_lock)" >&2
    exit 1
  fi
  trap 'rc=$?; VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant halt -f >/dev/null 2>&1 || true; rmdir "$exp2_lock" 2>/dev/null || true; exit "$rc"' EXIT
elif [ "$experiment" = "exp3" ]; then
  if [ -d "$result_dir" ]; then
    for entry in "$result_dir"/*; do
      if [ -e "$entry" ] || [ -L "$entry" ]; then
        echo "refusing to replace existing Exp3 results: $result_dir" >&2
        echo "choose a new run directory or remove this one explicitly" >&2
        exit 1
      fi
    done
  fi
  exp3_lock=${RUN_IN_VM_LOCK:-.exp3-vm.lock}
  if ! mkdir "$exp3_lock" 2>/dev/null; then
    echo "Exp3 VM is already in use ($exp3_lock)" >&2
    exit 1
  fi
  trap 'rc=$?; VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant halt -f >/dev/null 2>&1 || true; rmdir "$exp3_lock" 2>/dev/null || true; exit "$rc"' EXIT
fi

echo "*** Running experiment VM workflow: $remote_subdir ($provider, dir=$vagrant_dir)"

env "$box_env_name=$box_path" VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant up --provision
VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant ssh-config --host "$host_alias" > "$ssh_config"

if [ "$experiment" = "exp2" ] || [ "$experiment" = "exp3" ]; then
  rsync -avH -e "ssh -F $ssh_config -o TCPKeepAlive=no -o ServerAliveInterval=10" --exclude .git --exclude .vagrant --exclude results --exclude paper/bin --exclude box --exclude '*.box' --exclude '*.tar' --exclude '*.tar.gz' --exclude '*.tgz' ./ "$host_alias:$remote_dir/"
else
  rsync -avH -e "ssh -F $ssh_config -o TCPKeepAlive=no -o ServerAliveInterval=10" --exclude .git --exclude .vagrant --exclude results --exclude paper/bin ./ "$host_alias:$remote_dir/"
fi

mkdir -p "$result_dir"
if [ "$experiment" != "exp2" ] && [ "$experiment" != "exp3" ] && [ "${RUN_IN_VM_CLEAR_LOCAL:-}" = "1" ]; then
  rm -rf "$result_dir"/*
fi

# Use ssh -F directly so the keepalive options appended to $ssh_config above take effect on the long-running command.
ssh -F "$ssh_config" -o TCPKeepAlive=no -o ServerAliveInterval=10 "$host_alias" "set -e; cd $remote_dir/$remote_subdir && make clean && $remote_make; mkdir -p results/minindn-logs; if [ -d /tmp/minindn ]; then for name in $mobility_log_nodes; do node=/tmp/minindn/\$name; if [ -d \"\$node/log\" ]; then mkdir -p \"results/minindn-logs/\$name\"; cp -f \"\$node/log/nfd.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; cp -f \"\$node/log/nlsr.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; fi; done; fi"

rsync -avH -e "ssh -F $ssh_config -o TCPKeepAlive=no -o ServerAliveInterval=10" "$host_alias:$remote_dir/$remote_subdir/results/." "$result_dir/"
VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant halt -f || true

echo ""
echo "*** Finished experiment VM workflow: $remote_subdir ($provider, dir=$vagrant_dir)"
echo ""

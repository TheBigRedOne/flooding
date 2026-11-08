#!/bin/sh
set -eu

# Resolve a grouped output path to its run directory.
# pcap_nodes/ and certs/ sit one level below the run; minindn-logs/<node>/ sits two.
resolve_run_root() {
  dir=$(dirname "$1")
  while :; do
    base=$(basename "$dir")
    parent=$(dirname "$dir")
    parent_base=$(basename "$parent")
    if [ "$base" = "pcap_nodes" ] || [ "$base" = "certs" ]; then
      dir=$parent
      continue
    fi
    if [ "$parent_base" = "minindn-logs" ]; then
      dir=$(dirname "$parent")
      continue
    fi
    break
  done
  printf '%s\n' "$dir"
}

# A replaceable Exp2/Exp3 directory is one run: r1–r5, smoke, or pilot.
single_run_root() {
  root=$1
  output=$2
  case "$root" in
    ""|.|..|/|./) return 1 ;;
  esac
  case "$output" in
    "$root"/*) ;;
    *) return 1 ;;
  esac
  case "$(basename "$root")" in
    r1|r2|r3|r4|r5|smoke|pilot) return 0 ;;
    *) return 1 ;;
  esac
}

if [ "${1:-}" = "--print-run-root" ]; then
  if [ "$#" -ne 2 ]; then
    echo "usage: sh scripts/run-in-vm.sh --print-run-root <output-path>" >&2
    exit 2
  fi
  resolve_run_root "$2"
  exit 0
fi

if [ "${1:-}" = "--run-root-status" ]; then
  if [ "$#" -ne 2 ]; then
    echo "usage: sh scripts/run-in-vm.sh --run-root-status <output-path>" >&2
    exit 2
  fi
  root=$(resolve_run_root "$2")
  if single_run_root "$root" "$2"; then
    printf 'safe %s\n' "$root"
    exit 0
  fi
  printf 'unsafe %s\n' "$root" >&2
  exit 1
fi

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

result_dir=$(resolve_run_root "$target_output")

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
  if ! single_run_root "$result_dir" "$target_output"; then
    echo "refusing to replace Exp2 results outside one run directory: $result_dir" >&2
    exit 1
  fi
  exp2_lock=${RUN_IN_VM_LOCK:-.exp2-vm.lock}
  if ! mkdir "$exp2_lock" 2>/dev/null; then
    echo "Exp2 VM is already in use ($exp2_lock)" >&2
    exit 1
  fi
  trap 'rc=$?; VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant halt -f >/dev/null 2>&1 || true; rmdir "$exp2_lock" 2>/dev/null || true; exit "$rc"' EXIT
elif [ "$experiment" = "exp3" ]; then
  if ! single_run_root "$result_dir" "$target_output"; then
    echo "refusing to replace Exp3 results outside one run directory: $result_dir" >&2
    exit 1
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
if [ "$experiment" = "exp2" ] || [ "$experiment" = "exp3" ]; then
  # Clear this out-of-date run before the new guest results are copied back.
  rm -rf "$result_dir"/*
elif [ "${RUN_IN_VM_CLEAR_LOCAL:-}" = "1" ]; then
  rm -rf "$result_dir"/*
fi

# Use ssh -F directly so the keepalive options appended to $ssh_config above take effect on the long-running command.
copy_guest_diagnostics() {
  ssh -F "$ssh_config" -o TCPKeepAlive=no -o ServerAliveInterval=10 "$host_alias" "set -e; cd $remote_dir/$remote_subdir && mkdir -p results/minindn-logs; if [ -d /tmp/minindn ]; then for name in $mobility_log_nodes; do node=/tmp/minindn/\$name; if [ -d \"\$node/log\" ]; then mkdir -p \"results/minindn-logs/\$name\"; cp -f \"\$node/log/nfd.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; cp -f \"\$node/log/nlsr.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; fi; done; fi"
}

if [ "$experiment" = "exp3" ]; then
  # set -e would skip every later copy when the guest make fails. Collection is
  # best-effort and does not change the guest status.
  guest_status=0
  ssh -F "$ssh_config" -o TCPKeepAlive=no -o ServerAliveInterval=10 "$host_alias" "set -e; cd $remote_dir/$remote_subdir && make clean && $remote_make" || guest_status=$?
  if [ "$guest_status" -ne 0 ]; then
    copy_guest_diagnostics || true
    rsync -avH -e "ssh -F $ssh_config -o TCPKeepAlive=no -o ServerAliveInterval=10" "$host_alias:$remote_dir/$remote_subdir/results/." "$result_dir/" || true
    echo "Exp3 guest command failed with status ${guest_status}; diagnostic results were copied when available" >&2
    exit "$guest_status"
  fi
  copy_guest_diagnostics
else
  ssh -F "$ssh_config" -o TCPKeepAlive=no -o ServerAliveInterval=10 "$host_alias" "set -e; cd $remote_dir/$remote_subdir && make clean && $remote_make; mkdir -p results/minindn-logs; if [ -d /tmp/minindn ]; then for name in $mobility_log_nodes; do node=/tmp/minindn/\$name; if [ -d \"\$node/log\" ]; then mkdir -p \"results/minindn-logs/\$name\"; cp -f \"\$node/log/nfd.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; cp -f \"\$node/log/nlsr.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; fi; done; fi"
fi

rsync -avH -e "ssh -F $ssh_config -o TCPKeepAlive=no -o ServerAliveInterval=10" "$host_alias:$remote_dir/$remote_subdir/results/." "$result_dir/"
VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant halt -f || true

echo ""
echo "*** Finished experiment VM workflow: $remote_subdir ($provider, dir=$vagrant_dir)"
echo ""

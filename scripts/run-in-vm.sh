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
ssh_config=
vm_lock=
vagrant_dir=

# True only when every machine in this Vagrant project is not_created.
project_vm_absent() {
  output=$(VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant status --machine-readable) || return 1
  printf '%s\n' "$output" | awk -F, '
    $3 == "state" { seen = 1; if ($4 != "not_created") bad = 1 }
    END { exit (seen && !bad) ? 0 : 1 }
  '
}

# Destroy only this project. Success means the project is not_created afterwards.
destroy_project_vm() {
  destroy_status=0
  VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant destroy -f || destroy_status=$?
  if project_vm_absent; then
    return 0
  fi
  echo "$experiment VM in $vagrant_dir is still present after destroy (destroy status $destroy_status)" >&2
  return 1
}

release_run_files() {
  if [ -n "$ssh_config" ]; then
    rm -f "$ssh_config"
  fi
  if [ -n "$vm_lock" ]; then
    rm -f "$vm_lock/pid"
    rmdir "$vm_lock" 2>/dev/null || true
  fi
}

finish_run() {
  status=$1
  if ! destroy_project_vm; then
    echo "$experiment VM cleanup failed for $vagrant_dir" >&2
    if [ "$status" -eq 0 ]; then
      status=1
    fi
  fi
  release_run_files
  trap - EXIT
  exit "$status"
}

cleanup_run() {
  status=$?
  finish_run "$status"
}

if [ "$profile" = "exp1" ]; then
  experiment=exp1
  host_alias=exp1
  vagrant_dir=experiment/extended/exp1
  box_env_name=ACTUAL_SOLUTION_BOX_PATH
  remote_subdir=experiment/extended/exp1
  remote_make=${RUN_IN_VM_REMOTE_MAKE:?RUN_IN_VM_REMOTE_MAKE is required for exp1}
elif [ "$profile" = "exp2" ]; then
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
vm_lock=${RUN_IN_VM_LOCK:-.${experiment}-vm.lock}
if ! mkdir "$vm_lock" 2>/dev/null; then
  echo "$experiment VM is already in use ($vm_lock)" >&2
  exit 1
fi
echo $$ > "$vm_lock/pid"
trap cleanup_run EXIT

if [ "$experiment" = "exp2" ] || [ "$experiment" = "exp3" ]; then
  if ! single_run_root "$result_dir" "$target_output"; then
    echo "refusing to replace $experiment results outside one run directory: $result_dir" >&2
    exit 1
  fi
fi

echo "*** Running experiment VM workflow: $remote_subdir ($provider, dir=$vagrant_dir)"

if ! destroy_project_vm; then
  echo "refusing to start $experiment; stale VM remains in $vagrant_dir" >&2
  exit 1
fi
env "$box_env_name=$box_path" VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant up --provision
VAGRANT_DEFAULT_PROVIDER="$provider" VAGRANT_CWD="$vagrant_dir" vagrant ssh-config --host "$host_alias" > "$ssh_config"

ready=0
attempt=0
while [ "$attempt" -lt 30 ]; do
  if ssh -F "$ssh_config" -o BatchMode=yes -o ConnectTimeout=5 -o TCPKeepAlive=no "$host_alias" true; then
    ready=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "SSH to $host_alias was not ready" >&2
  exit 1
fi

rsync -aH --stats --human-readable \
  -e "ssh -F $ssh_config -o TCPKeepAlive=no -o ServerAliveInterval=10 -o BatchMode=yes" \
  --exclude .git/ --exclude .vagrant/ --exclude results/ --exclude paper/bin/ \
  --exclude experiment/tool/.venv/ --exclude __pycache__/ --exclude '*.pyc' \
  --exclude '.ssh_config_*' --exclude box/ --exclude '*.box' \
  --exclude '*.tar' --exclude '*.tar.gz' --exclude '*.tgz' \
  ./ "$host_alias:$remote_dir/"

mkdir -p "$result_dir"
if [ "$experiment" = "exp2" ] || [ "$experiment" = "exp3" ]; then
  rm -rf "$result_dir"/*
elif [ "${RUN_IN_VM_CLEAR_LOCAL:-}" = "1" ]; then
  rm -rf "$result_dir"/*
fi

# Best-effort copies for experiments whose node set is not the main topology.
copy_guest_diagnostics() {
  ssh -F "$ssh_config" -o BatchMode=yes -o TCPKeepAlive=no -o ServerAliveInterval=10 "$host_alias" "set -e; cd $remote_dir/$remote_subdir && mkdir -p results/minindn-logs; if [ -d /tmp/minindn ]; then for name in $mobility_log_nodes; do node=/tmp/minindn/\$name; if [ -d \"\$node/log\" ]; then mkdir -p \"results/minindn-logs/\$name\"; cp -f \"\$node/log/nfd.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; cp -f \"\$node/log/nlsr.log\" \"results/minindn-logs/\$name/\" 2>/dev/null || true; fi; done; fi"
}

# NLSR logs for routing.NODES and NFD logs for routing.ROUTING_UNIVERSE.
# A missing required log fails this command. Producer NFD is supplementary.
copy_required_logs() {
  ssh -F "$ssh_config" -o BatchMode=yes -o TCPKeepAlive=no -o ServerAliveInterval=10 "$host_alias" "set -eu; cd $remote_dir/$remote_subdir; copy_log() { name=\$1; kind=\$2; src=/tmp/minindn/\$name/log/\$kind.log; dest=results/minindn-logs/\$name/\$kind.log; test -f \"\$src\"; mkdir -p \"results/minindn-logs/\$name\"; cp -f \"\$src\" \"\$dest\"; }; for name in producer consumer core agg1 agg2 acc1 acc2 acc3 acc4 acc5 acc6; do copy_log \"\$name\" nlsr; done; for name in consumer core agg1 agg2 acc1 acc2 acc3 acc4 acc5 acc6; do copy_log \"\$name\" nfd; done; if [ -f /tmp/minindn/producer/log/nfd.log ]; then mkdir -p results/minindn-logs/producer; cp -f /tmp/minindn/producer/log/nfd.log results/minindn-logs/producer/nfd.log || true; fi"
}

copy_guest_results() {
  rsync -aH --stats --human-readable \
    -e "ssh -F $ssh_config -o TCPKeepAlive=no -o ServerAliveInterval=10 -o BatchMode=yes" \
    "$host_alias:$remote_dir/$remote_subdir/results/." "$result_dir/"
}

main_experiment() {
  [ "$experiment" = "baseline" ] || [ "$experiment" = "solution" ] || [ "$experiment" = "exp1" ]
}

require_main_evidence() {
  missing=0
  for name in params.txt handoffs.txt consumer_capture.pcap; do
    if [ ! -f "$result_dir/$name" ]; then
      echo "required evidence missing: $result_dir/$name" >&2
      missing=1
    fi
  done
  for node in core agg1 agg2 acc1 acc2 acc3 acc4 acc5 acc6 producer consumer; do
    if [ ! -f "$result_dir/pcap_nodes/$node.pcap" ]; then
      echo "required evidence missing: $result_dir/pcap_nodes/$node.pcap" >&2
      missing=1
    fi
    if [ ! -f "$result_dir/minindn-logs/$node/nlsr.log" ]; then
      echo "required evidence missing: $result_dir/minindn-logs/$node/nlsr.log" >&2
      missing=1
    fi
  done
  for node in consumer core agg1 agg2 acc1 acc2 acc3 acc4 acc5 acc6; do
    if [ ! -f "$result_dir/minindn-logs/$node/nfd.log" ]; then
      echo "required evidence missing: $result_dir/minindn-logs/$node/nfd.log" >&2
      missing=1
    fi
  done
  [ "$missing" -eq 0 ]
}

collect_logs() {
  if main_experiment; then
    copy_required_logs
  else
    copy_guest_diagnostics
  fi
}

guest_status=0
ssh -F "$ssh_config" -o BatchMode=yes -o TCPKeepAlive=no -o ServerAliveInterval=10 "$host_alias" "set -e; cd $remote_dir/$remote_subdir && make clean && $remote_make" || guest_status=$?
log_status=0
result_status=0
collect_logs || log_status=$?
copy_guest_results || result_status=$?
if [ "$guest_status" -ne 0 ]; then
  echo "$experiment guest command failed with status ${guest_status}; log copy status ${log_status}; result copy status ${result_status}" >&2
  exit "$guest_status"
fi
if [ "$result_status" -ne 0 ]; then
  echo "mandatory result retrieval failed with status ${result_status}; log copy status ${log_status}" >&2
  exit "$result_status"
fi
if main_experiment; then
  if [ "$log_status" -ne 0 ]; then
    echo "required log collection failed with status ${log_status}" >&2
    exit "$log_status"
  fi
  require_main_evidence
elif [ "$log_status" -ne 0 ]; then
  echo "$experiment supplementary log collection failed with status ${log_status}" >&2
fi

echo ""
echo "*** Finished experiment VM workflow: $remote_subdir ($provider, dir=$vagrant_dir)"
echo ""

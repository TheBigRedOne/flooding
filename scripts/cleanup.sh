#!/bin/sh

# Purpose: Remove generated host artifacts and repository-owned Vagrant
# resources for the cleanup targets.
# Interface: LATEXMK=<latexmk-command> PROVIDER=<provider> sh scripts/cleanup.sh
# <clean|vm-clean|deep-clean>
#
# vm-clean and deep-clean destroy only the Vagrant environments owned by this
# repository. deep-clean also removes this provider's generated box files and
# their Vagrant registrations. The shared bento/ubuntu-22.04 base image is not
# a repository box and is left registered.

set -eu

if [ $# != 1 ]; then
  echo "Usage: $0 <clean|vm-clean|deep-clean>"
  exit 1
fi

MODE=$1
LATEXMK_CMD=${LATEXMK:-latexmk}
MAIN_TEX=paper/OptoFlood.tex
PAPER_PDF=paper/OptoFlood.pdf
PAPER_BIN=paper/bin
VENV_DIR=experiment/tool/.venv
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

BASELINE_PAPER_FIGURES="
paper/figures/baseline_disruption.pdf
paper/figures/baseline_loss.pdf
paper/figures/baseline_throughput.pdf
"

SOLUTION_PAPER_FIGURES="
paper/figures/solution_disruption.pdf
paper/figures/solution_loss.pdf
paper/figures/solution_throughput.pdf
"

require_provider() {
  if [ x"${PROVIDER:-}" = x ]; then
    echo "Cannot clean Vagrant resources: provider is not set"
    exit 1
  fi
}

lock_is_active() {
  lock=$1
  if [ ! -d "$lock" ]; then
    return 1
  fi
  pid=$(cat "$lock/pid" 2>/dev/null || true)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "skipping resources for $lock; pid $pid is running" >&2
    return 0
  fi
  return 1
}

remove_idle_ssh_config() {
  config=$1
  lock=$2
  if lock_is_active "$lock"; then
    echo "keeping $config" >&2
    return 0
  fi
  rm -f "$config"
}

remove_ssh_configs() {
  remove_idle_ssh_config .ssh_config_baseline .baseline-vm.lock
  remove_idle_ssh_config .ssh_config_solution .solution-vm.lock
  remove_idle_ssh_config .ssh_config_exp1 .exp1-vm.lock
  remove_idle_ssh_config .ssh_config_exp2 .exp2-vm.lock
  remove_idle_ssh_config .ssh_config_exp3 .exp3-vm.lock
  rm -f \
    test/.ssh_config_baseline \
    test/.ssh_config_solution
}

remove_smoke_stamps() {
  rm -f "test/.baseline_pass.$PROVIDER" "test/.solution_pass.$PROVIDER"
}

remove_host_artifacts() {
  remove_ssh_configs
  remove_smoke_stamps
  # Removes results/routing/, routing PDFs, and the other host-side analysis outputs.
  rm -rf results
  rm -rf "$VENV_DIR"
  "$LATEXMK_CMD" -c "$MAIN_TEX"
  rm -f "$PAPER_PDF"
  rm -rf "$PAPER_BIN"
  rm -f $BASELINE_PAPER_FIGURES $SOLUTION_PAPER_FIGURES
  rm -rf test/pcap test/results test/baseline/results test/solution/results
  rm -f \
    test/consumer \
    test/producer \
    test/optoflood-daemon \
    test/trust-schema.conf \
    test/.validate_ok \
    test/.sync_solution_*
}

project_is_absent() {
  dir=$1
  output=$(VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$dir vagrant status --machine-readable) || return 1
  printf '%s\n' "$output" | awk -F, '
    $3 == "state" { seen = 1; if ($4 != "not_created") bad = 1 }
    END { exit (seen && !bad) ? 0 : 1 }
  '
}

destroy_vm() {
  echo "Destroying Vagrant environment: $1"
  if ! VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$1 vagrant destroy -f; then
    echo "vagrant destroy failed for $1" >&2
  fi
  if ! project_is_absent "$1"; then
    echo "$1 is still present after destroy" >&2
  fi
}

destroy_smoke_vm() {
  vagrant_dir=$1
  box_file=$2
  path_var=$3
  name_var=$4
  box_name=$5
  echo "Destroying Vagrant environment: $vagrant_dir"
  if ! env \
    "$path_var=$box_file" \
    "$name_var=$box_name" \
    VAGRANT_DEFAULT_PROVIDER="$PROVIDER" \
    VAGRANT_CWD="$vagrant_dir" \
    vagrant destroy -f; then
    echo "vagrant destroy failed for $vagrant_dir" >&2
  fi
  # vagrant status loads the smoke Vagrantfile, which requires the same
  # box path and name as destroy. Keep them in this subshell only.
  if ! (
    export "$path_var=$box_file"
    export "$name_var=$box_name"
    project_is_absent "$vagrant_dir"
  ); then
    echo "$vagrant_dir is still present after destroy" >&2
  fi
}

destroy_idle_vm() {
  vagrant_dir=$1
  lock=$2
  if lock_is_active "$lock"; then
    echo "keeping VM $vagrant_dir" >&2
    return 0
  fi
  destroy_vm "$vagrant_dir"
  if [ -d "$lock" ]; then
    pid=$(cat "$lock/pid" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "leaving $lock; pid $pid started during cleanup" >&2
    else
      rm -rf "$lock"
    fi
  fi
}

destroy_all_vms() {
  destroy_idle_vm experiment/baseline .baseline-vm.lock
  destroy_idle_vm experiment/solution .solution-vm.lock
  destroy_idle_vm experiment/extended/exp1 .exp1-vm.lock
  destroy_idle_vm experiment/extended/exp2 .exp2-vm.lock
  destroy_idle_vm experiment/extended/exp3 .exp3-vm.lock
  destroy_smoke_vm \
    test/baseline \
    "$ROOT/box/baseline/baseline.$PROVIDER.box" \
    ACTUAL_BASELINE_BOX_PATH \
    BASELINE_BOX_NAME \
    optoflood-baseline-smoke
  destroy_smoke_vm \
    test/solution \
    "$ROOT/box/solution/solution.$PROVIDER.box" \
    ACTUAL_SOLUTION_BOX_PATH \
    SOLUTION_BOX_NAME \
    optoflood-solution-smoke
  destroy_vm box/baseline
  destroy_vm box/solution
  destroy_vm box/initial
}

remove_registered_box() {
  echo "Removing Vagrant box registration: $1 ($PROVIDER)"
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER \
    vagrant box remove "$1" --provider "$PROVIDER" --all --force || true
}

remove_box_file() {
  remove_registered_box "$1"
  rm -f "$1" "$1.lock"
}

remove_all_boxes() {
  remove_box_file "box/initial/initial.$PROVIDER.box"
  remove_box_file "box/baseline/baseline.$PROVIDER.box"
  remove_box_file "box/solution/solution.$PROVIDER.box"
  remove_registered_box optoflood-baseline-smoke
  remove_registered_box optoflood-solution-smoke
}

case "$MODE" in
  clean)
    require_provider
    remove_host_artifacts
    ;;
  vm-clean)
    require_provider
    remove_ssh_configs
    destroy_all_vms
    ;;
  deep-clean)
    require_provider
    remove_host_artifacts
    destroy_all_vms
    remove_all_boxes
    ;;
  *)
    echo "Unknown cleanup mode: $MODE"
    exit 1
    ;;
esac

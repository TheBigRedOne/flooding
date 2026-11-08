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

remove_ssh_configs() {
  rm -f \
    .ssh_config_baseline \
    .ssh_config_solution \
    .ssh_config_exp2 \
    .ssh_config_exp3 \
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

destroy_vm() {
  echo "Destroying Vagrant environment: $1"
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$1 vagrant destroy -f || true
}

destroy_smoke_vm() {
  vagrant_dir=$1
  box_file=$2
  path_var=$3
  name_var=$4
  box_name=$5
  echo "Destroying Vagrant environment: $vagrant_dir"
  env \
    "$path_var=$box_file" \
    "$name_var=$box_name" \
    VAGRANT_DEFAULT_PROVIDER="$PROVIDER" \
    VAGRANT_CWD="$vagrant_dir" \
    vagrant destroy -f || true
}

destroy_all_vms() {
  destroy_vm experiment/baseline
  destroy_vm experiment/solution
  destroy_vm experiment/extended/exp2
  destroy_vm experiment/extended/exp3
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
  rm -rf .exp2-vm.lock .exp3-vm.lock
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

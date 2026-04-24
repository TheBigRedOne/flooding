#!/bin/sh

# Purpose: Remove generated host artifacts and Vagrant resources for the
# repository cleanup targets.
# Interface: LATEXMK=<latexmk-command> PROVIDER=<provider> sh scripts/cleanup.sh
# <clean|vm-clean|deep-clean>

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
BASELINE_MAKEFILE=Makefile.baseline
SOLUTION_MAKEFILE=Makefile.solution
BASELINE_SSH_CONFIG=.ssh_config_baseline
SOLUTION_SSH_CONFIG=.ssh_config_solution

BASELINE_PAPER_FIGURES="
paper/figures/baseline_disruption.pdf
paper/figures/baseline_loss.pdf
paper/figures/baseline_overhead_timeseries.pdf
paper/figures/baseline_overhead_summary.pdf
paper/figures/baseline_throughput.pdf
"

SOLUTION_PAPER_FIGURES="
paper/figures/solution_disruption.pdf
paper/figures/solution_loss.pdf
paper/figures/solution_overhead_timeseries.pdf
paper/figures/solution_overhead_summary.pdf
paper/figures/solution_throughput.pdf
"

require_provider() {
  if [ x"${PROVIDER:-}" = x ]; then
    echo "Cannot clean Vagrant resources: provider is not set"
    exit 1
  fi
}

remove_ssh_configs() {
  rm -f "$BASELINE_SSH_CONFIG" "$SOLUTION_SSH_CONFIG"
}

remove_host_artifacts() {
  remove_ssh_configs
  rm -rf results
  rm -rf "$VENV_DIR"
  rm -f "$BASELINE_MAKEFILE" "$SOLUTION_MAKEFILE"
  "$LATEXMK_CMD" -c "$MAIN_TEX"
  rm -f "$PAPER_PDF"
  rm -rf "$PAPER_BIN"
  rm -f $BASELINE_PAPER_FIGURES $SOLUTION_PAPER_FIGURES
  rm -rf test/pcap test/results
  rm -f test/consumer test/producer test/*.txt test/*.conf test/.ssh_config_solution \
    test/.validate_ok test/.sync_solution_*
}

destroy_vm() {
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER VAGRANT_CWD=$1 vagrant destroy -f || true
}

destroy_all_vms() {
  destroy_vm experiment/baseline
  destroy_vm experiment/solution
  destroy_vm test
  destroy_vm box/baseline
  destroy_vm box/solution
  destroy_vm box/initial
}

remove_box() {
  VAGRANT_DEFAULT_PROVIDER=$PROVIDER vagrant box remove "$1" || true
  rm -f "$1"
}

remove_all_boxes() {
  remove_box "box/baseline/baseline.$PROVIDER.box"
  remove_box "box/solution/solution.$PROVIDER.box"
  remove_box "box/initial/initial.$PROVIDER.box"
}

case "$MODE" in
  clean)
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

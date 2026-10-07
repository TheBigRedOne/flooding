# =============================================================================
# Options to control the build

# By default, running Vagrant will use the virtualbox provider. To use the
# libvirt provider with KVM, add PROVIDER=libvirt to the make invocation.

PROVIDER ?= virtualbox

# Example invocations:
#    make                              -- build using virtualbox
#    make PROVIDER=libvirt             -- build using KVM
#    make PROVIDER=libvirt deep-clean  -- deep-clean using KVM

export PROVIDER

# =============================================================================
# Master Control Makefile

BOXES = box/initial/initial.$(PROVIDER).box \
        box/baseline/baseline.$(PROVIDER).box \
        box/solution/solution.$(PROVIDER).box

# Experiment rules and result variables.
include Makefile.baseline
include Makefile.solution
include Makefile.exp1

# Baseline profile directories (parents of r1..r5; rules live in Makefile.baseline).
BASELINE_PROFILE_DIRS := $(addprefix results/baseline/,$(BASELINE_PROFILE_LIST))

# Active paper figures. Baseline tuning is G0..G4: SRT, content loss fraction,
# and NLSR control rate. The OptoFlood comparison adds recovery flooding volume.
# Routing convergence figures are produced by routing-analysis. Legacy
# forwarding-cost-ratio PDFs stay on the lower-level analysis targets only.
GENERATED_FIGURES := results/baseline_service_recovery_time.pdf \
                     results/baseline_content_loss_fraction.pdf \
                     results/baseline_nlsr_control_rate.pdf \
                     results/solution_service_recovery_time.pdf \
                     results/solution_content_loss_fraction.pdf \
                     results/solution_recovery_flooding_volume.pdf \
                     results/solution_nlsr_control_rate.pdf \
                     results/routing_topology_update_latency.pdf \
                     results/routing_service_path_fib_convergence.pdf \
                     results/routing_network_fib_convergence.pdf

ALL_FIGURES := paper/figures/NDN_Packets_Processing_Flow.pdf \
               paper/figures/NDN_Producer_Mobility_Problem.pdf \
               paper/figures/NDN_Producer_Mobility_Problem_Solution.pdf \
               paper/figures/Topology.pdf \
               $(GENERATED_FIGURES) \
               $(EXT1_SENSITIVITY_OUTPUTS) \
               $(EXT1_TIMELINE_OUTPUT)

# Sources checked by phony target `mypy`.
PLOT_TOOL_SRCS := experiment/tool/plot_latency.py \
                  experiment/tool/compute_latency_metrics.py \
                  experiment/tool/plot_loss.py \
                  experiment/tool/compute_loss_metrics.py \
                  experiment/tool/plot_overhead.py \
                  experiment/tool/compute_overhead_metrics.py \
                  experiment/tool/compute_overhead_ymax.py \
                  experiment/tool/plot_throughput.py \
                  experiment/tool/compute_throughput_metrics.py \
                  experiment/tool/plot_throughput_comparison.py \
                  experiment/tool/plot_disruption_comparison.py \
                  experiment/tool/plot_unmet_interest_comparison.py \
                  experiment/tool/summarise_nlsr_sensitivity.py \
                  experiment/tool/plot_nlsr_disruption_comparison.py \
                  experiment/tool/plot_nlsr_network_cost_comparison.py \
                  experiment/tool/mobility_event_metrics.py \
                  experiment/tool/plot_mobility_event_metrics.py \
                  experiment/tool/run_mobility_event_analysis.py \
                  experiment/tool/test_mobility_event_metrics.py \
                  experiment/tool/audit_decoder_parity.py \
                  experiment/tool/plot_delivery_timeline.py \
                  experiment/tool/routing_convergence_metrics.py \
                  experiment/tool/run_routing_convergence_analysis.py \
                  experiment/tool/test_routing_convergence_metrics.py

# Full workflow. One recipe runs each stage to completion before the next, so
# `make -j` cannot overlap these stages or start analysis before experiments.
all:
	$(MAKE) experiment-baseline
	$(MAKE) test
	$(MAKE) experiment-solution
	$(MAKE) experiment-exp1
	$(MAKE) mobility-analysis
	$(MAKE) paper

# High-level orchestration targets (set the provider via `PROVIDER=...` when needed)
.PHONY: boxes experiment experiment-baseline experiment-solution experiment-exp1 plot-exp1 exp1 \
        result plot plot-baseline plot-main paper test mypy vm-clean


# Experiments (run inside VMs and pull back CSVs)
experiment-baseline: $(BASELINE_RAW_OUTPUTS)

experiment-solution: $(SOLUTION_RESULTS)

# Extended evaluation, Exp 1 (request-interval sweep, solution only).
experiment-exp1: $(EXT1_RAW_OUTPUTS)

plot-exp1: $(EXT1_ANALYSIS_OUTPUTS)

exp1: experiment-exp1 plot-exp1

# Run the baseline, solution, and Exp 1 experiments
experiment: experiment-baseline experiment-solution experiment-exp1

# Assemble the active comparison figures and the Exp 1 figures.
result: $(BASELINE_PROFILE_COMPARE_OUTPUTS) $(SOLUTION_COMPARE_OUTPUTS) $(EXT1_ANALYSIS_OUTPUTS)

# Run the test experiment
test: test/.validate_ok

test/.validate_ok: test/Makefile test/Vagrantfile test/exp_test.py test/validate.py \
             experiment/app/producer.cpp experiment/app/consumer.cpp \
             experiment/app/optoflood-daemon.cpp \
             experiment/app/trust-schema.conf experiment/tool/ndn.lua \
             box/solution/solution.$(PROVIDER).box \
             | $(BASELINE_RAW_OUTPUTS)
	$(MAKE) -C test PROVIDER=$(PROVIDER) SOLUTION_NLSR_RESULT_DRIVEN=$(SOLUTION_NLSR_RESULT_DRIVEN) SOLUTION_NLSR_EVENT_DRIVEN_VERIFICATION=$(SOLUTION_NLSR_EVENT_DRIVEN_VERIFICATION) test-all

# Plot only (reuse existing captures; no VM run).
# plot-main is the G0-versus-OptoFlood box plots.
plot: plot-baseline plot-main

# Analysis-only targets. Their file rules do not depend on experiment outputs,
# so Make cannot rebuild a stale PCAP by entering a VM recipe.

.PHONY: mobility-analysis test-mobility-analysis plot-exp1-diagnostic routing-analysis plot-routing test-routing-analysis

mobility-analysis:
	$(MAKE) plot-baseline
	$(MAKE) plot-main
	$(MAKE) plot-exp1
	$(MAKE) routing-analysis

# One command, used by the explicit routing-analysis target and by the paper
# PDF rule. The PDF rule must not call $(MAKE): a dry-run would execute that
# recipe, and a failed grouped-target update can delete the sibling PDF.
ROUTING_ANALYSIS_CMD = python3 experiment/tool/run_routing_convergence_analysis.py

routing-analysis:
	$(ROUTING_ANALYSIS_CMD)

# Paper depends on the topology-update PDF and the two FIB subfigure PDFs.
# The stacked routing_fib_convergence.pdf remains a diagnostic side effect of
# the analysis command and is not a paper input. Missing a paper PDF reruns
# analysis of existing logs and captures, and does not start a VM.
ROUTING_PAPER_FIGURES := results/routing_topology_update_latency.pdf \
                         results/routing_service_path_fib_convergence.pdf \
                         results/routing_network_fib_convergence.pdf

$(ROUTING_PAPER_FIGURES) &: experiment/tool/run_routing_convergence_analysis.py \
                            experiment/tool/routing_convergence_metrics.py
	$(ROUTING_ANALYSIS_CMD)

plot-routing: routing-analysis

test-routing-analysis:
	python3 -m unittest experiment.tool.test_routing_convergence_metrics

test-mobility-analysis:
	python3 -m unittest experiment.tool.test_mobility_event_metrics

plot-exp1-diagnostic:
	python3 experiment/tool/run_mobility_event_analysis.py analyze-exp1 --diagnostic --deadline $(EXT1_PRIMARY_DEADLINE)

plot-baseline: $(BASELINE_PROFILE_COMPARE_OUTPUTS) $(BASELINE_LEGACY_FCR)

plot-main: $(SOLUTION_COMPARE_OUTPUTS) $(SOLUTION_LEGACY_FCR)

# Build the paper PDF (follow dependencies; do not hand-check and exit)
paper: paper/OptoFlood.pdf

# Ensure results directories exist
results:
	mkdir $@

results/baseline: | results
	mkdir $@

results/solution: | results
	mkdir $@

$(BASELINE_PROFILE_DIRS): | results/baseline
	mkdir -p "$@"

paper/figures:
	mkdir $@

# Static typing (mypy). Callers are responsible for resolving `python3` to an
# interpreter that has mypy and the host-side runtime dependencies installed;
# see the "Static Typing" section in README.md for the supported workflow.
mypy:
	python3 -m mypy --config-file mypy.ini test/validate.py $(PLOT_TOOL_SRCS)


# =============================================================================
# Rules to build the Vagrant boxes

build-boxes: boxes

box: boxes

box-initial: box/initial/initial.$(PROVIDER).box

box-baseline: box/baseline/baseline.$(PROVIDER).box

box-solution: box/solution/solution.$(PROVIDER).box

boxes: $(BOXES)

box/initial/initial.$(PROVIDER).box: box/initial/Vagrantfile
	PROVIDER=$(PROVIDER) sh scripts/make-box.sh $(dir $<) $@

box/baseline/baseline.$(PROVIDER).box: box/baseline/Vagrantfile box/initial/initial.$(PROVIDER).box
	PROVIDER=$(PROVIDER) sh scripts/make-box.sh $(dir $<) $@

box/solution/solution.$(PROVIDER).box: box/solution/Vagrantfile box/initial/initial.$(PROVIDER).box
	PROVIDER=$(PROVIDER) sh scripts/make-box.sh $(dir $<) $@


# =============================================================================

# Generate the paper
paper/OptoFlood.pdf: paper/OptoFlood.tex $(ALL_FIGURES) | paper/bin
	@echo "Compiling LaTeX with latexmk..."
	latexmk -pdf -interaction=nonstopmode -output-directory=paper/bin paper/OptoFlood.tex
	cp paper/bin/OptoFlood.pdf paper/OptoFlood.pdf

paper/bin:
	mkdir -p paper/bin


# Cleanup
clean:
	PROVIDER=$(PROVIDER) LATEXMK=latexmk sh scripts/cleanup.sh clean

deep-clean: clean
	PROVIDER=$(PROVIDER) LATEXMK=latexmk sh scripts/cleanup.sh deep-clean

# Clean SSH config file
clean-ssh-config:
	rm -f .ssh_config_baseline .ssh_config_solution

# Destroy all VMs (keep boxes)
vm-clean:
	PROVIDER=$(PROVIDER) LATEXMK=latexmk sh scripts/cleanup.sh vm-clean


.PHONY: all build-boxes boxes clean deep-clean clean-ssh-config box box-initial box-baseline box-solution experiment experiment-baseline experiment-solution experiment-exp1 plot-exp1 exp1 result plot plot-baseline plot-main paper test mypy vm-clean mobility-analysis test-mobility-analysis plot-exp1-diagnostic routing-analysis plot-routing test-routing-analysis

.DELETE_ON_ERROR:

.NOTINTERMEDIATE:

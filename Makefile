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
include Makefile.exp2
include Makefile.exp3

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

# Paper-facing figures produced by the Exp1 parameter-sensitivity analysis.
EXP1_PAPER_FIGURES := results/extended/exp1/exp1_sync_delay_sensitivity.pdf \
                      results/extended/exp1/exp1_verification_timeout_sensitivity.pdf

# Shared-versus-Distinct comparison figures. The recipe reads existing
# analysis CSVs and does not start a VM.
EXP2_PAPER_FIGURES := results/extended/exp2/comparison/rfv_shared_vs_distinct.pdf \
                      results/extended/exp2/comparison/srt_shared_vs_distinct.pdf \
                      results/extended/exp2/comparison/clf_shared_vs_distinct.pdf
EXP2_COMPARISON_INPUTS := results/extended/exp2/analysis/network_handoffs.csv \
                          results/extended/exp2/analysis/consumer_handoffs.csv \
                          results/extended/exp2/analysis/analysis_audit.txt \
                          results/extended/exp2/distinct/analysis/network_handoffs.csv \
                          results/extended/exp2/distinct/analysis/consumer_handoffs.csv \
                          results/extended/exp2/distinct/analysis/stream_recovery_diagnostics.csv \
                          results/extended/exp2/distinct/analysis/analysis_audit.txt

# Exp3 manuscript figures. Formal population plots stay under analysis/figures.
# The two supplementary plots use paper-figures/ so they do not enter the
# protected analysis tree. Recipes are host-side Python only.
EXP3_CAMPAIGN_DIR := results/extended/exp3/analysis/campaign
EXP3_FORMAL_PAPER_FIGURES := results/extended/exp3/analysis/figures/clf_by_population.pdf \
                             results/extended/exp3/analysis/figures/network_rfv_by_population.pdf \
                             results/extended/exp3/analysis/figures/nlsr_control_rate_by_population.pdf
EXP3_SUPPLEMENTARY_FIGURES := results/extended/exp3/paper-figures/srt_by_producer.pdf \
                              results/extended/exp3/paper-figures/prefix_rfv_by_attachment.pdf

ALL_FIGURES := paper/figures/NDN_Packets_Processing_Flow.pdf \
               paper/figures/NDN_Producer_Mobility_Problem.pdf \
               paper/figures/NDN_Producer_Mobility_Problem_Solution.pdf \
               paper/figures/Topology.pdf \
               $(GENERATED_FIGURES) \
               $(EXP1_PAPER_FIGURES) \
               $(EXP2_PAPER_FIGURES) \
               $(EXP3_FORMAL_PAPER_FIGURES) \
               $(EXP3_SUPPLEMENTARY_FIGURES)

$(EXP2_PAPER_FIGURES) &: experiment/tool/exp2/plot_exp2_comparison.py $(EXP2_COMPARISON_INPUTS)
	python3 -m experiment.tool.exp2.plot_exp2_comparison

$(EXP3_FORMAL_PAPER_FIGURES) &: experiment/tool/exp3/plot_exp3.py \
                                $(EXP3_CAMPAIGN_DIR)/campaign_status.txt \
                                $(EXP3_CAMPAIGN_DIR)/events.csv \
                                $(EXP3_CAMPAIGN_DIR)/population_comparison.csv
	python3 -m experiment.tool.exp3.plot_exp3

$(EXP3_SUPPLEMENTARY_FIGURES) &: experiment/tool/exp3/plot_exp3.py \
                                 $(EXP3_CAMPAIGN_DIR)/campaign_status.txt \
                                 $(EXP3_CAMPAIGN_DIR)/events.csv \
                                 $(EXP3_CAMPAIGN_DIR)/prefix_rfv.csv
	python3 -m experiment.tool.exp3.plot_exp3 --extended \
		--analysis-root results/extended/exp3/analysis \
		--figure-dir results/extended/exp3/paper-figures

# Sources checked by phony target `mypy`.
PLOT_TOOL_SRCS := experiment/tool/common/exp.py \
                  experiment/tool/common/handoff_schedule.py \
                  experiment/tool/exp1/run_sensitivity_analysis.py \
                  experiment/tool/exp2/exp2_shared_driver.py \
                  experiment/tool/exp2/exp2_shared_config.py \
                  experiment/tool/exp2/exp2_shared_metrics.py \
                  experiment/tool/exp2/exp2_distinct_metrics.py \
                  experiment/tool/exp2/exp2_scale_metrics.py \
                  experiment/tool/exp2/run_exp2_shared_analysis.py \
                  experiment/tool/exp2/run_exp2_distinct_analysis.py \
                  experiment/tool/exp2/run_exp2_scale_analysis.py \
                  experiment/tool/exp2/plot_exp2_comparison.py \
                  experiment/tool/exp2/plot_exp2_scale.py \
                  experiment/tool/exp2/check_exp2_shared_evidence.py \
                  experiment/tool/exp3/exp3_driver.py \
                  experiment/tool/exp3/exp3_config.py \
                  experiment/tool/exp3/exp3_processes.py \
                  experiment/tool/exp3/exp3_metrics.py \
                  experiment/tool/exp3/run_exp3_analysis.py \
                  experiment/tool/exp3/plot_exp3.py \
                  experiment/tool/exp3/check_exp3_evidence.py \
                  experiment/tool/analysis/mobility_event_metrics.py \
                  experiment/tool/analysis/routing_convergence_metrics.py \
                  experiment/tool/analysis/plot_mobility_event_metrics.py \
                  experiment/tool/analysis/extract_overhead_csv.py \
                  experiment/tool/analysis/run_mobility_event_analysis.py \
                  experiment/tool/analysis/run_routing_convergence_analysis.py

# Full workflow. Each recipe line finishes before the next, including under
# `make -j`. Baseline and Solution experiments pull their smoke stamps.
all:
	$(MAKE) experiment-baseline
	$(MAKE) experiment-solution
	$(MAKE) experiment-exp1
	$(MAKE) experiment-exp2
	$(MAKE) experiment-exp3
	$(MAKE) mobility-analysis
	$(MAKE) analyze-exp2
	$(MAKE) analyze-exp3
	$(MAKE) paper

# High-level orchestration targets (set the provider via `PROVIDER=...` when needed)
.PHONY: boxes experiment experiment-baseline experiment-solution experiment-exp1 plot-exp1 exp1 \
        result plot plot-baseline plot-main paper test mypy vm-clean


# Experiments run inside VMs and pull the captures back.
# Baseline, solution, and Exp1 run one after another.
experiment-baseline: $(BASELINE_RAW_OUTPUTS)

experiment-solution: $(SOLUTION_RESULTS)

experiment-exp1:
	$(MAKE) experiment-exp1-sync-delay
	$(MAKE) experiment-exp1-verification-timeout

exp1:
	$(MAKE) experiment-exp1
	$(MAKE) plot-exp1

experiment:
	$(MAKE) experiment-baseline
	$(MAKE) experiment-solution
	$(MAKE) experiment-exp1

# Baseline and solution comparison outputs, plus the Exp1 sensitivity figures.
result: $(BASELINE_PROFILE_COMPARE_OUTPUTS) $(SOLUTION_COMPARE_OUTPUTS) $(EXP1_PAPER_FIGURES)

# Integration smokes. A stamp exists only after that smoke's assertions pass.
# The provider is part of the file name, so one hypervisor cannot satisfy the other.
BASELINE_SMOKE_PASS := test/.baseline_pass.$(PROVIDER)
SOLUTION_SMOKE_PASS := test/.solution_pass.$(PROVIDER)

BASELINE_SMOKE_INPUTS := box/baseline/baseline.$(PROVIDER).box \
	experiment/app/producer.cpp \
	experiment/app/consumer.cpp \
	experiment/app/trust-schema.conf \
	test/run_smoke.sh \
	test/inside_smoke.sh \
	test/baseline_smoke.py \
	test/validate_baseline.py \
	test/smoke_runtime.py \
	test/smoke_validate.py \
	test/baseline/Vagrantfile

SOLUTION_SMOKE_INPUTS := box/solution/solution.$(PROVIDER).box \
	experiment/app/producer.cpp \
	experiment/app/consumer.cpp \
	experiment/app/optoflood-daemon.cpp \
	experiment/app/guard_flood_id.hpp \
	experiment/app/trust-schema.conf \
	test/run_smoke.sh \
	test/inside_smoke.sh \
	test/solution_smoke.py \
	test/validate_solution.py \
	test/smoke_runtime.py \
	test/smoke_validate.py \
	test/solution/Vagrantfile

$(BASELINE_SMOKE_PASS): $(BASELINE_SMOKE_INPUTS)
	rm -f $@
	PROVIDER=$(PROVIDER) sh test/run_smoke.sh baseline
	echo $(PROVIDER) > $@

$(SOLUTION_SMOKE_PASS): $(SOLUTION_SMOKE_INPUTS)
	rm -f $@
	PROVIDER=$(PROVIDER) sh test/run_smoke.sh solution
	echo $(PROVIDER) > $@

test:
	$(MAKE) $(BASELINE_SMOKE_PASS)
	$(MAKE) $(SOLUTION_SMOKE_PASS)

# Plot only (reuse existing captures; no VM run).
# plot-main is the G0-versus-OptoFlood box plots.
# plot-baseline and plot-main refresh the host-side comparison figures.
plot: plot-baseline plot-main

# Host-side analysis. `make all` runs these targets after the experiments,
# so the PDF figures come from the captures just written.

.PHONY: mobility-analysis routing-analysis plot-routing

mobility-analysis:
	$(MAKE) plot-baseline
	$(MAKE) plot-main
	$(MAKE) routing-analysis
	$(MAKE) plot-exp1

# One command, used by the explicit routing-analysis target and by the paper
# PDF rule. The PDF rule must not call $(MAKE): a dry-run would execute that
# recipe, and a failed grouped-target update can delete the sibling PDF.
ROUTING_ANALYSIS_CMD = python3 -m experiment.tool.analysis.run_routing_convergence_analysis

routing-analysis:
	$(ROUTING_ANALYSIS_CMD)

# Paper depends on the topology-update PDF and the two FIB subfigure PDFs.
# The stacked routing_fib_convergence.pdf remains a diagnostic side effect of
# the analysis command and is not a paper input. Missing a paper PDF reruns
# analysis of existing logs and captures, and does not start a VM.
ROUTING_PAPER_FIGURES := results/routing_topology_update_latency.pdf \
                         results/routing_service_path_fib_convergence.pdf \
                         results/routing_network_fib_convergence.pdf

$(ROUTING_PAPER_FIGURES) &: experiment/tool/analysis/run_routing_convergence_analysis.py \
                            experiment/tool/analysis/routing_convergence_metrics.py
	$(ROUTING_ANALYSIS_CMD)

plot-routing: routing-analysis

define EXP1_ANALYSIS_CMD
python3 -m experiment.tool.exp1.run_sensitivity_analysis sync-delay
python3 -m experiment.tool.exp1.run_sensitivity_analysis verification-timeout
python3 -m experiment.tool.exp1.run_sensitivity_analysis cross-check
endef

plot-exp1:
	$(EXP1_ANALYSIS_CMD)

# Host-side Exp1 figures. plot-exp1 runs this analysis after the experiment stage.
# Paper builds these outputs directly.
$(EXP1_PAPER_FIGURES) &: experiment/tool/exp1/run_sensitivity_analysis.py \
                         experiment/tool/analysis/mobility_event_metrics.py \
                         experiment/tool/analysis/routing_convergence_metrics.py \
                         experiment/tool/analysis/run_mobility_event_analysis.py \
                         experiment/tool/analysis/plot_mobility_event_metrics.py \
                         experiment/tool/analysis/extract_overhead_csv.py \
                         experiment/tool/resources/ndn.lua
	$(EXP1_ANALYSIS_CMD)

plot-baseline:
	$(BASELINE_ANALYSIS_CMD)

plot-main:
	$(SOLUTION_ANALYSIS_CMD)

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
	python3 -m mypy --config-file mypy.ini $(PLOT_TOOL_SRCS)


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
paper/OptoFlood.pdf: paper/OptoFlood.tex paper/OptoFlood.bib $(ALL_FIGURES) | paper/bin
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

# SSH configs for the formal experiments and the two smoke VMs.
clean-ssh-config:
	rm -f .ssh_config_baseline .ssh_config_solution .ssh_config_exp2 .ssh_config_exp3 \
	  test/.ssh_config_baseline test/.ssh_config_solution

# Destroy repository VMs and keep generated boxes.
vm-clean:
	PROVIDER=$(PROVIDER) LATEXMK=latexmk sh scripts/cleanup.sh vm-clean


.PHONY: all build-boxes boxes clean deep-clean clean-ssh-config box box-initial box-baseline box-solution experiment experiment-baseline experiment-solution experiment-exp1 plot-exp1 exp1 result plot plot-baseline plot-main paper test mypy vm-clean mobility-analysis routing-analysis plot-routing

.DELETE_ON_ERROR:

.NOTINTERMEDIATE:

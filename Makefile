# =============================================================================
# Options to control the build

# By default, running Vagrant will use the virtualbox provider. To use the
# libvirt provider with KVM, add PROVIDER=libvirt to the make invocation.

PROVIDER ?= virtualbox

# By default, tests are run to demonstrate that the flooding mechanisms is
# working. To disable the tests, add DISABLE_TEST=1 to the make invocation.

DISABLE_TEST ?=

# Example invocations:
#    make                                  -- build using virtualbox
#    make PROVIDER=libvirt DISABLE_TEST=1  -- build using KVM without tests
#    make PROVIDER=libvirt deep-clean      -- deep-clean using KVM

export PROVIDER
export DISABLE_TEST

# =============================================================================
# Master Control Makefile

BOXES = box/initial/initial.$(PROVIDER).box \
        box/baseline/baseline.$(PROVIDER).box \
        box/solution/solution.$(PROVIDER).box

# Baseline parameter-set configuration
include experiment/tool/baseline_profiles.mk
BASELINE_PROFILE_DIRS := $(foreach profile,$(BASELINE_PROFILE_IDS),$(BASELINE_PROFILE_DIR_$(profile)))
BASELINE_PROFILE_RAW_OUTPUTS := \
	$(foreach profile,$(BASELINE_PROFILE_IDS),$(BASELINE_PROFILE_DIR_$(profile))/consumer_capture.pcap) \
	$(foreach profile,$(BASELINE_PROFILE_IDS),$(foreach node,core agg1 agg2 acc1 acc2 acc3 acc4 acc5 acc6 producer consumer,$(BASELINE_PROFILE_DIR_$(profile))/pcap_nodes/$(node).pcap)) \
	$(foreach profile,$(BASELINE_PROFILE_IDS),$(BASELINE_PROFILE_DIR_$(profile))/params.txt)
BASELINE_PROFILE_SUMMARY_INPUTS := \
	$(foreach profile,$(BASELINE_PROFILE_IDS),$(BASELINE_PROFILE_DIR_$(profile))/params.txt) \
	$(foreach profile,$(BASELINE_PROFILE_IDS),$(BASELINE_PROFILE_DIR_$(profile))/disruption_metrics.txt) \
	$(foreach profile,$(BASELINE_PROFILE_IDS),$(BASELINE_PROFILE_DIR_$(profile))/overhead_total.txt)

# Baseline parameter-set comparison outputs
BASELINE_PROFILE_COMPARE_OUTPUTS := results/baseline/summary.csv \
                                   results/baseline/disruption_comparison.pdf \
                                   results/baseline/network_cost_comparison.pdf
MAIN_RESULT_OUTPUTS := $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/disruption_times.pdf \
                       $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/disruption_metrics.txt \
                       $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/loss_comparison.pdf \
                       $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/loss_ratio.txt \
                       $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/throughput_timeseries.pdf \
                       $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/throughput_metrics.txt \
                       $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_timeseries.pdf \
                       $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_summary.pdf \
                       $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_total.txt \
                       results/solution/disruption_times.pdf \
                       results/solution/disruption_metrics.txt \
                       results/solution/loss_comparison.pdf \
                       results/solution/loss_ratio.txt \
                       results/solution/throughput_timeseries.pdf \
                       results/solution/throughput_metrics.txt \
                       results/solution/overhead_timeseries.pdf \
                       results/solution/overhead_summary.pdf \
                       results/solution/overhead_total.txt

# --- Paper Figure Dependencies ---
# These variables link the experiment outputs to the figures in the paper.
BASELINE_PAPER_FIGURES := paper/figures/baseline_disruption.pdf \
                          paper/figures/baseline_loss.pdf \
                          paper/figures/baseline_overhead_timeseries.pdf \
                          paper/figures/baseline_overhead_summary.pdf \
                          paper/figures/baseline_throughput.pdf
SOLUTION_PAPER_FIGURES := paper/figures/solution_disruption.pdf \
                          paper/figures/solution_loss.pdf \
                          paper/figures/solution_overhead_timeseries.pdf \
                          paper/figures/solution_overhead_summary.pdf \
                          paper/figures/solution_throughput.pdf
STATIC_FIGURES := paper/figures/NDN_Packets_Processing_Flow.pdf \
                  paper/figures/NDN_Producer_Mobility_Problem.pdf \
                  paper/figures/NDN_Producer_Mobility_Problem_Solution.pdf \
                  paper/figures/Topology.pdf
ALL_FIGURES := $(STATIC_FIGURES) $(BASELINE_PAPER_FIGURES) $(SOLUTION_PAPER_FIGURES)

# Common application source files
APP_SRCS := experiment/app/producer.cpp \
            experiment/app/consumer.cpp \
            experiment/app/trust-schema.conf

# Experiment-specific source files
BASELINE_SRCS := experiment/baseline/Vagrantfile \
                experiment/baseline/Makefile
SOLUTION_SRCS := experiment/solution/Vagrantfile \
                experiment/solution/Makefile

# Tool groups used by aggregate validation targets.
PLOT_TOOL_SRCS := experiment/tool/plot_latency.py \
                  experiment/tool/plot_loss.py \
                  experiment/tool/plot_overhead.py \
                  experiment/tool/compute_overhead_ymax.py \
                  experiment/tool/plot_throughput.py \
                  experiment/tool/summarize_nlsr_sensitivity.py \
                  experiment/tool/plot_nlsr_disruption_comparison.py \
                  experiment/tool/plot_nlsr_network_cost_comparison.py \
                  experiment/tool/plot_result_metrics.py \
                  experiment/tool/plot_main_results.py
TEST_SRCS := test/Makefile test/Vagrantfile test/exp_test.py test/validate.py \
             experiment/app/producer.cpp experiment/app/consumer.cpp \
             experiment/app/trust-schema.conf experiment/tool/ndn.lua

-include Makefile.baseline
include Makefile.solution

# Main target (set DISABLE_TEST=1 to skip tests)
all: $(BOXES) experiment $(if $(DISABLE_TEST),,test/.validate_ok) result paper

# High-level orchestration targets (set the provider via `PROVIDER=...` when needed)
.PHONY: boxes experiment experiment-baseline experiment-solution experiment-nlsr-tuning \
        result plot plot-baseline plot-main plot-nlsr-tuning paper test mypy vm-clean


# Experiments (run inside VMs and pull back CSVs)
experiment-baseline: $(BASELINE_PROFILE_RAW_OUTPUTS)

experiment-solution: $(SOLUTION_RESULTS)

# Backward-compatible alias for the baseline parameter-set experiment pipeline.
experiment-nlsr-tuning: $(BASELINE_PROFILE_RAW_OUTPUTS) results/baseline/summary.csv \
                        results/baseline/disruption_comparison.pdf results/baseline/network_cost_comparison.pdf

# Run both experiments
experiment: experiment-baseline experiment-solution

# Assemble result figures for the paper (copy from results/ to paper/figures)
result: $(BASELINE_PAPER_FIGURES) $(SOLUTION_PAPER_FIGURES)

# Run the test experiment
test: test/.validate_ok

test/.validate_ok: $(TEST_SRCS) box/solution/solution.$(PROVIDER).box
	$(MAKE) -C test PROVIDER=$(PROVIDER) test-all

# Plot only (reuse existing CSVs; no VM run)
plot: plot-baseline plot-main

plot-baseline: $(BASELINE_PROFILE_COMPARE_OUTPUTS)

plot-main: $(MAIN_RESULT_OUTPUTS)

# Backward-compatible alias for the baseline parameter-set plot pipeline.
plot-nlsr-tuning: plot-baseline

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

$(addsuffix /pcap_nodes,$(BASELINE_PROFILE_DIRS)) results/solution/pcap_nodes:
	mkdir -p "$@"

paper/figures:
	mkdir $@

# Type checking (mypy) using host venv
mypy: | experiment/tool/.venv
	experiment/tool/.venv/bin/python3 -m mypy --config-file mypy.ini test/validate.py $(PLOT_TOOL_SRCS)


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


Makefile.baseline: scripts/makefile-baseline.py experiment/tool/baseline_profiles.mk
	python3 scripts/makefile-baseline.py > "$@"

Makefile.solution: scripts/makefile-solution.py
	python3 scripts/makefile-solution.py > "$@"

results/baseline/summary.csv: $(BASELINE_PROFILE_SUMMARY_INPUTS) experiment/tool/summarize_nlsr_sensitivity.py experiment/tool/baseline_profiles.mk | results/baseline
	python3 experiment/tool/summarize_nlsr_sensitivity.py --root-dir results/baseline --profiles "$(foreach profile,$(BASELINE_PROFILE_IDS),$(notdir $(BASELINE_PROFILE_DIR_$(profile))))" --default-profile "$(notdir $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE)))" --output "$@"

results/baseline/disruption_comparison.pdf: results/baseline/summary.csv experiment/tool/plot_nlsr_disruption_comparison.py | results/baseline
	python3 experiment/tool/plot_nlsr_disruption_comparison.py --input results/baseline/summary.csv --output "$@"

results/baseline/network_cost_comparison.pdf: results/baseline/summary.csv experiment/tool/plot_nlsr_network_cost_comparison.py | results/baseline
	python3 experiment/tool/plot_nlsr_network_cost_comparison.py --input results/baseline/summary.csv --output "$@"

# Host-side venv for plotting
experiment/tool/.venv: experiment/tool/requirements.txt
	python3 -m venv experiment/tool/.venv
	experiment/tool/.venv/bin/pip install -r experiment/tool/requirements.txt
	touch experiment/tool/.venv

# Plot baseline(default) and solution full metric sets with shared overhead axes
$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/disruption_times.pdf: experiment/tool/plot_latency.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/consumer_capture.csv
	python3 $^ $@

$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/disruption_metrics.txt: experiment/tool/plot_latency.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/consumer_capture.csv
	python3 $^ $@

$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/loss_comparison.pdf: experiment/tool/plot_loss.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/consumer_capture.csv
	python3 $^ $@

$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/loss_ratio.txt: experiment/tool/plot_loss.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/consumer_capture.csv
	python3 $^ $@

$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/throughput_timeseries.pdf: experiment/tool/plot_throughput.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/consumer_capture.csv
	python3 $^ $@

$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/throughput_metrics.txt: experiment/tool/plot_throughput.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/consumer_capture.csv
	python3 $^ $@

results/main_overhead_limits.txt: experiment/tool/compute_overhead_ymax.py experiment/tool/plot_overhead.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/network_overhead.csv results/solution/network_overhead.csv | results
	python3 experiment/tool/compute_overhead_ymax.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/network_overhead.csv results/solution/network_overhead.csv $@

$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_timeseries.pdf: experiment/tool/plot_overhead.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/network_overhead.csv results/main_overhead_limits.txt
	python3 $^ $@

$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_summary.pdf: experiment/tool/plot_overhead.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/network_overhead.csv results/main_overhead_limits.txt
	python3 $^ $@

$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_total.txt: experiment/tool/plot_overhead.py $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/network_overhead.csv
	python3 $^ $@

# --- Copy Results to Paper Directory ---

paper/figures/baseline_disruption.pdf: $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/disruption_times.pdf | paper/figures
	cp "$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/disruption_times.pdf" "$@"

paper/figures/baseline_loss.pdf: $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/loss_comparison.pdf | paper/figures
	cp "$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/loss_comparison.pdf" "$@"

paper/figures/baseline_overhead_timeseries.pdf: $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_timeseries.pdf | paper/figures
	cp "$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_timeseries.pdf" "$@"

paper/figures/baseline_overhead_summary.pdf: $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_summary.pdf | paper/figures
	cp "$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/overhead_summary.pdf" "$@"

paper/figures/baseline_throughput.pdf: $(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/throughput_timeseries.pdf | paper/figures
	cp "$(BASELINE_PROFILE_DIR_$(BASELINE_DEFAULT_PROFILE))/throughput_timeseries.pdf" "$@"

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


.PHONY: all build-boxes boxes clean deep-clean clean-ssh-config box box-initial box-baseline box-solution experiment experiment-baseline experiment-solution experiment-nlsr-tuning result plot plot-baseline plot-main plot-nlsr-tuning paper test mypy vm-clean

.DELETE_ON_ERROR:

.NOTINTERMEDIATE:

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

# Experiment rules and result variables.
include Makefile.baseline
include Makefile.solution

MAIN_RESULT_OUTPUTS := $(BASELINE_DEFAULT_DIR)/disruption_times.pdf \
                       $(BASELINE_DEFAULT_DIR)/disruption_metrics.txt \
                       $(BASELINE_DEFAULT_DIR)/loss_comparison.pdf \
                       $(BASELINE_DEFAULT_DIR)/loss_ratio.txt \
                       $(BASELINE_DEFAULT_DIR)/throughput_timeseries.pdf \
                       $(BASELINE_DEFAULT_DIR)/throughput_metrics.txt \
                       $(BASELINE_DEFAULT_DIR)/overhead_timeseries.pdf \
                       $(BASELINE_DEFAULT_DIR)/overhead_summary.pdf \
                       $(BASELINE_DEFAULT_DIR)/overhead_total.txt \
                       results/solution/disruption_times.pdf \
                       results/solution/disruption_metrics.txt \
                       results/solution/loss_comparison.pdf \
                       results/solution/loss_ratio.txt \
                       results/solution/throughput_timeseries.pdf \
                       results/solution/throughput_metrics.txt \
                       results/solution/overhead_timeseries.pdf \
                       results/solution/overhead_summary.pdf \
                       results/solution/overhead_total.txt
UNMET_INTEREST_COMPARISON_INPUTS := \
                       $(BASELINE_DEFAULT_DIR)/loss_ratio.txt \
                       results/solution/loss_ratio.txt

# --- Paper Figure Dependencies ---
# These variables link the experiment outputs to the figures in the paper.
BASELINE_PAPER_FIGURES := paper/figures/throughput_comparison.pdf \
                          paper/figures/service_disruption_comparison.pdf \
                          paper/figures/unmet_interest_comparison.pdf \
                          paper/figures/baseline_nlsr_disruption_comparison.pdf \
                          paper/figures/baseline_nlsr_network_cost_comparison.pdf \
                          paper/figures/baseline_overhead_timeseries.pdf \
                          paper/figures/baseline_overhead_summary.pdf
SOLUTION_PAPER_FIGURES := paper/figures/solution_overhead_timeseries.pdf \
                          paper/figures/solution_overhead_summary.pdf
STATIC_FIGURES := paper/figures/NDN_Packets_Processing_Flow.pdf \
                  paper/figures/NDN_Producer_Mobility_Problem.pdf \
                  paper/figures/NDN_Producer_Mobility_Problem_Solution.pdf \
                  paper/figures/Topology.pdf
ALL_FIGURES := $(STATIC_FIGURES) $(BASELINE_PAPER_FIGURES) $(SOLUTION_PAPER_FIGURES)

# Tool groups used by aggregate validation targets.
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
                  experiment/tool/plot_nlsr_network_cost_comparison.py
TEST_SRCS := test/Makefile test/Vagrantfile test/exp_test.py test/validate.py \
             experiment/app/producer.cpp experiment/app/consumer.cpp \
             experiment/app/trust-schema.conf experiment/tool/ndn.lua

# Main target (set DISABLE_TEST=1 to skip tests)
all: $(BOXES) experiment $(if $(DISABLE_TEST),,test/.validate_ok) result paper

# High-level orchestration targets (set the provider via `PROVIDER=...` when needed)
.PHONY: boxes experiment experiment-baseline experiment-solution experiment-nlsr-tuning \
        result plot plot-baseline plot-main plot-nlsr-tuning paper test mypy vm-clean


# Experiments (run inside VMs and pull back CSVs)
experiment-baseline: $(BASELINE_RAW_OUTPUTS)

experiment-solution: $(SOLUTION_RESULTS)

# Backward-compatible alias for the baseline parameter-set experiment pipeline.
experiment-nlsr-tuning: $(BASELINE_RAW_OUTPUTS) $(BASELINE_PROFILE_COMPARE_OUTPUTS)

# Run both experiments
experiment: experiment-baseline experiment-solution

# Assemble result figures and baseline profile comparisons.
result: $(BASELINE_PAPER_FIGURES) $(SOLUTION_PAPER_FIGURES) $(BASELINE_PROFILE_COMPARE_OUTPUTS)

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


# Host-side venv for plotting
experiment/tool/.venv: experiment/tool/requirements.txt
	python3 -m venv experiment/tool/.venv
	experiment/tool/.venv/bin/pip install -r experiment/tool/requirements.txt
	touch experiment/tool/.venv

# Shared overhead y-axis limits for baseline(default) and solution main-result plots.
results/main_overhead_limits.txt: experiment/tool/compute_overhead_ymax.py $(BASELINE_DEFAULT_DIR)/network_overhead.csv results/solution/network_overhead.csv | experiment/tool/plot_overhead.py results
	python3 $^ $@

$(BASELINE_DEFAULT_DIR)/overhead_timeseries.pdf: experiment/tool/plot_overhead.py $(BASELINE_DEFAULT_DIR)/network_overhead.csv results/main_overhead_limits.txt
	python3 $^ $@

$(BASELINE_DEFAULT_DIR)/overhead_summary.pdf: experiment/tool/plot_overhead.py $(BASELINE_DEFAULT_DIR)/network_overhead.csv results/main_overhead_limits.txt
	python3 $^ $@

# --- Copy Results to Paper Directory ---

paper/figures/throughput_comparison.pdf: experiment/tool/plot_throughput_comparison.py $(BASELINE_DEFAULT_DIR)/consumer_capture.csv results/solution/consumer_capture.csv | paper/figures
	python3 $^ $@

paper/figures/service_disruption_comparison.pdf: experiment/tool/plot_disruption_comparison.py $(BASELINE_DEFAULT_DIR)/disruption_metrics.txt results/solution/disruption_metrics.txt | paper/figures
	python3 $^ $@

paper/figures/unmet_interest_comparison.pdf: experiment/tool/plot_unmet_interest_comparison.py $(UNMET_INTEREST_COMPARISON_INPUTS) | paper/figures
	python3 $^ $@ --log-scale

paper/figures/baseline_disruption.pdf: $(BASELINE_DEFAULT_DIR)/disruption_times.pdf | paper/figures
	cp "$(BASELINE_DEFAULT_DIR)/disruption_times.pdf" "$@"

paper/figures/baseline_loss.pdf: $(BASELINE_DEFAULT_DIR)/loss_comparison.pdf | paper/figures
	cp "$(BASELINE_DEFAULT_DIR)/loss_comparison.pdf" "$@"

paper/figures/baseline_nlsr_disruption_comparison.pdf: results/baseline/disruption_comparison.pdf | paper/figures
	cp "results/baseline/disruption_comparison.pdf" "$@"

paper/figures/baseline_nlsr_network_cost_comparison.pdf: results/baseline/network_cost_comparison.pdf | paper/figures
	cp "results/baseline/network_cost_comparison.pdf" "$@"

paper/figures/baseline_overhead_timeseries.pdf: $(BASELINE_DEFAULT_DIR)/overhead_timeseries.pdf | paper/figures
	cp "$(BASELINE_DEFAULT_DIR)/overhead_timeseries.pdf" "$@"

paper/figures/baseline_overhead_summary.pdf: $(BASELINE_DEFAULT_DIR)/overhead_summary.pdf | paper/figures
	cp "$(BASELINE_DEFAULT_DIR)/overhead_summary.pdf" "$@"

paper/figures/baseline_throughput.pdf: $(BASELINE_DEFAULT_DIR)/throughput_timeseries.pdf | paper/figures
	cp "$(BASELINE_DEFAULT_DIR)/throughput_timeseries.pdf" "$@"

paper/figures/solution_disruption.pdf: results/solution/disruption_times.pdf | paper/figures
	cp "results/solution/disruption_times.pdf" "$@"

paper/figures/solution_loss.pdf: results/solution/loss_comparison.pdf | paper/figures
	cp "results/solution/loss_comparison.pdf" "$@"

paper/figures/solution_overhead_timeseries.pdf: results/solution/overhead_timeseries.pdf | paper/figures
	cp "results/solution/overhead_timeseries.pdf" "$@"

paper/figures/solution_overhead_summary.pdf: results/solution/overhead_summary.pdf | paper/figures
	cp "results/solution/overhead_summary.pdf" "$@"

paper/figures/solution_throughput.pdf: results/solution/throughput_timeseries.pdf | paper/figures
	cp "results/solution/throughput_timeseries.pdf" "$@"

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

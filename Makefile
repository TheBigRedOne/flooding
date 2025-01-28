# Master Control Makefile

# Base paths
BASE_DIR := $(shell pwd)
RESULTS_DIR := $(BASE_DIR)/results
BASELINE_RESULTS := $(RESULTS_DIR)/baseline
SOLUTION_RESULTS := $(RESULTS_DIR)/solution
PAPER_DIR := $(BASE_DIR)/paper

# Results from experiments
BASELINE_PDF := $(BASELINE_RESULTS)/consumer_capture_throughput.pdf
SOLUTION_PDF := $(SOLUTION_RESULTS)/consumer_capture_throughput.pdf

# Paper dependencies and output
MAIN_TEX := $(PAPER_DIR)/OptoFlood.tex
BASELINE_FIGURE := $(PAPER_DIR)/figures/baseline_throughput.pdf
SOLUTION_FIGURE := $(PAPER_DIR)/figures/solution_throughput.pdf
PAPER_PDF := $(PAPER_DIR)/OptoFlood.pdf
STATIC_FIGURES := $(PAPER_DIR)/figures/NLSR_Work_Flow.png \
                  $(PAPER_DIR)/figures/Producer_Mobility_Problems.png \
                  $(PAPER_DIR)/figures/Topology.png
ALL_FIGURES := $(STATIC_FIGURES) $(BASELINE_FIGURE) $(SOLUTION_FIGURE)

# Rsync command
RSYNC_CMD = rsync -avH -e "ssh -F $(BASE_DIR)/.ssh_config"

# Main target
all: $(PAPER_PDF)

# Ensure results directories exist
$(BASELINE_RESULTS) $(SOLUTION_RESULTS) $(PAPER_DIR)/figures:
	mkdir -p $@

# Baseline experiment results
$(BASELINE_PDF): $(BASELINE_RESULTS) | $(BASELINE_RESULTS)
	cd $(BASE_DIR)/experiments/baseline && vagrant up && vagrant ssh -c '\
		cd /home/vagrant/mini-ndn/flooding/experiments/baseline && make all;'
	$(RSYNC_CMD) default:/home/vagrant/mini-ndn/flooding/experiments/baseline/results/ $(BASELINE_RESULTS)

# Solution experiment results
$(SOLUTION_PDF): $(SOLUTION_RESULTS) | $(SOLUTION_RESULTS)
	cd $(BASE_DIR)/experiments/solution && vagrant up && vagrant ssh -c '\
		cd /home/vagrant/mini-ndn/flooding/experiments/solution && make all;'
	$(RSYNC_CMD) default:/home/vagrant/mini-ndn/flooding/experiments/solution/results/ $(SOLUTION_RESULTS)

# Copy baseline figure to paper figures directory
$(BASELINE_FIGURE): $(BASELINE_PDF) | $(PAPER_DIR)/figures
	cp $< $@

# Copy solution figure to paper figures directory
$(SOLUTION_FIGURE): $(SOLUTION_PDF) | $(PAPER_DIR)/figures
	cp $< $@

# Generate the paper
$(PAPER_PDF): $(MAIN_TEX) $(ALL_FIGURES) | $(PAPER_DIR)
	$(MAKE) -C $(PAPER_DIR)

# Cleanup
clean: clean-ssh-config
	cd $(BASE_DIR)/experiments/baseline && vagrant destroy -f || true
	cd $(BASE_DIR)/experiments/solution && vagrant destroy -f || true
	rm -rf $(RESULTS_DIR)
	cd $(PAPER_DIR) && $(MAKE) clean

deep-clean: clean
	rm -rf $(PAPER_DIR)/figures $(PAPER_PDF)

# Clean SSH config file
clean-ssh-config:
	rm -f $(BASE_DIR)/.ssh_config

.PHONY: all clean deep-clean clean-ssh-config
.DELETE_ON_ERROR:
.NOTINTERMEDIATE:

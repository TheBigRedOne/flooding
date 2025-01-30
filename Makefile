# Master Control Makefile

# Detect OS (for Windows compatibility)
#ifeq ($(OS),Windows_NT)
#    BASE_DIR := $(shell cygpath -m $(shell pwd))
#else
#    BASE_DIR := $(shell pwd)
#endif

# Base paths
BASE_DIR := $(shell pwd)
RESULTS_DIR := $(BASE_DIR)/results
BASELINE_RESULTS := $(RESULTS_DIR)/baseline
SOLUTION_RESULTS := $(RESULTS_DIR)/solution
PAPER_DIR := $(BASE_DIR)/paper

# Experiment Paths
BASELINE_DIR := $(BASE_DIR)/experiments/baseline
SOLUTION_DIR := $(BASE_DIR)/experiments/solution

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

# Rsync command for copying files from VM
RSYNC_CMD = rsync -avH -e "ssh -F $(BASE_DIR)/.ssh_config"

# Main target
all: $(PAPER_PDF)

# Ensure results directories exist
$(BASELINE_RESULTS) $(SOLUTION_RESULTS) $(PAPER_DIR)/figures:
	mkdir -p $@

# Baseline experiment SSH config
.SSH_CONFIG_BASELINE:
	cd $(BASELINE_DIR); \
	vagrant up; \
	vagrant ssh-config --host baseline > $(BASE_DIR)/.ssh_config

# Solution experiment SSH config
.SSH_CONFIG_SOLUTION:
	cd $(SOLUTION_DIR); \
	vagrant up; \
	vagrant ssh-config --host solution >> $(BASE_DIR)/.ssh_config

# Baseline experiment results
$(BASELINE_PDF): $(BASELINE_DIR)/consumer.cpp $(BASELINE_DIR)/producer.cpp .SSH_CONFIG_BASELINE | $(BASELINE_RESULTS)
	cd $(BASELINE_DIR); \
	vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding/experiments/baseline && make all'; \
	$(RSYNC_CMD) baseline:/home/vagrant/mini-ndn/flooding/experiments/baseline/results/ $(BASELINE_RESULTS); \
	cd $(BASELINE_DIR); vagrant destroy -f || true

# Solution experiment results
$(SOLUTION_PDF): $(SOLUTION_DIR)/consumer_mp.cpp $(SOLUTION_DIR)/producer_mp.cpp .SSH_CONFIG_SOLUTION | $(SOLUTION_RESULTS)
	cd $(SOLUTION_DIR); \
	vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding/experiments/solution && make all'; \
	$(RSYNC_CMD) solution:/home/vagrant/mini-ndn/flooding/experiments/solution/results/ $(SOLUTION_RESULTS); \
	cd $(SOLUTION_DIR); vagrant destroy -f || true

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

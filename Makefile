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

# Source directories
SOURCE_BASELINE := $(BASE_DIR)/baseline
SOURCE_SOLUTION := $(BASE_DIR)/solution
SOURCE_TOOLS    := $(BASE_DIR)/tools

# Box files
INITIAL_BOX := $(BASE_DIR)/boxes/initial/initial.box
BASELINE_BOX := $(BASE_DIR)/boxes/baseline/baseline.box
SOLUTION_BOX := $(BASE_DIR)/boxes/solution/solution.box

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

# Main target
all: $(PAPER_PDF)

# Ensure results directories exist
$(BASELINE_RESULTS) $(SOLUTION_RESULTS) $(PAPER_DIR)/figures:
	mkdir -p $@

# Boxes check
$(INITIAL_BOX): boxes/initial/Vagrantfile
	@echo "Initial box not found. Creating it now..."
	$(MAKE) -C boxes/initial

$(BASELINE_BOX): boxes/baseline/Vagrantfile $(INITIAL_BOX)
	@echo "Baseline box not found. Creating it now..."
	$(MAKE) -C boxes/baseline

$(SOLUTION_BOX): boxes/solution/Vagrantfile $(INITIAL_BOX)
	@echo "Solution box not found. Creating it now..."
	$(MAKE) -C boxes/solution

.PHONY: check-boxes
check-boxes: $(INITIAL_BOX) $(BASELINE_BOX) $(SOLUTION_BOX)

# SSH config file for baseline experiment
$(BASE_DIR)/.ssh_config_baseline: $(BASELINE_DIR)/Vagrantfile $(BASELINE_BOX)
	cd $(BASELINE_DIR); \
	vagrant up; \
	vagrant ssh-config --host baseline > $(BASE_DIR)/.ssh_config_baseline

# SSH config file for solution experiment
$(BASE_DIR)/.ssh_config_solution: $(SOLUTION_DIR)/Vagrantfile $(SOLUTION_BOX)
	cd $(SOLUTION_DIR); \
	vagrant up; \
	vagrant ssh-config --host solution > $(BASE_DIR)/.ssh_config_solution

# Rsync commands
RSYNC_CMD_BASELINE = rsync -avH -e "ssh -F $(BASE_DIR)/.ssh_config_baseline"
RSYNC_CMD_SOLUTION = rsync -avH -e "ssh -F $(BASE_DIR)/.ssh_config_solution"

# Baseline experiment results
$(BASELINE_PDF): $(BASELINE_DIR) $(BASE_DIR)/.ssh_config_baseline | $(BASELINE_RESULTS)
	cd $(BASELINE_DIR); \
		vagrant up; \
		vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding/experiments/baseline && make all'; \
	$(RSYNC_CMD_BASELINE) baseline:/home/vagrant/mini-ndn/flooding/experiments/baseline/results/ $(BASELINE_RESULTS); \
	cd $(BASELINE_DIR); vagrant halt -f || true

# Solution experiment results
$(SOLUTION_PDF): $(SOLUTION_DIR) $(BASE_DIR)/.ssh_config_solution | $(SOLUTION_RESULTS)
	cd $(SOLUTION_DIR); \
		vagrant up; \
		vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding/experiments/solution && make all'; \
	$(RSYNC_CMD_SOLUTION) solution:/home/vagrant/mini-ndn/flooding/experiments/solution/results/ $(SOLUTION_RESULTS); \
	cd $(SOLUTION_DIR); vagrant halt -f || true

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
	rm -rf $(BASELINE_FIGURE) $(SOLUTION_FIGURE) $(PAPER_PDF)

    # Remove local Vagrant box cache to ensure using .box files
    vagrant box remove initial -f --all || true
    vagrant box remove baseline -f --all || true
    vagrant box remove solution -f --all || true

# Clean SSH config file
clean-ssh-config:
	rm -f $(BASE_DIR)/.ssh_config_baseline $(BASE_DIR)/.ssh_config_solution

.PHONY: all clean deep-clean clean-ssh-config
.DELETE_ON_ERROR:
.NOTINTERMEDIATE:

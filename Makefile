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

# Final paper
PAPER_PDF := $(PAPER_DIR)/OptoFlood.pdf

# Main targets
all: $(BASELINE_PDF) $(SOLUTION_PDF) $(PAPER_PDF)

# Baseline experiment results
$(BASELINE_PDF):
	cd $(BASE_DIR)/experiments/baseline && vagrant up && vagrant ssh -c '\
		cd /home/vagrant/mini-ndn/flooding/experiments/baseline && make all;'
	mkdir -p $(BASELINE_RESULTS)
	cp $(BASE_DIR)/experiments/baseline/results/consumer_capture_throughput.pdf $(BASELINE_PDF)

# Solution experiment results
$(SOLUTION_PDF):
	cd $(BASE_DIR)/experiments/solution && vagrant up && vagrant ssh -c '\
		cd /home/vagrant/mini-ndn/flooding/experiments/solution && make all;'
	mkdir -p $(SOLUTION_RESULTS)
	cp $(BASE_DIR)/experiments/solution/results/consumer_capture_throughput.pdf $(SOLUTION_PDF)

# Paper generation
$(PAPER_PDF): $(BASELINE_PDF) $(SOLUTION_PDF)
	cp $(BASELINE_PDF) $(PAPER_DIR)/baseline_throughput.pdf
	cp $(SOLUTION_PDF) $(PAPER_DIR)/solution_throughput.pdf
	$(MAKE) -C $(PAPER_DIR)

# Cleanup
clean:
	cd $(BASE_DIR)/experiments/baseline && vagrant destroy -f || true
	cd $(BASE_DIR)/experiments/solution && vagrant destroy -f || true
	rm -rf $(RESULTS_DIR)
	cd $(PAPER_DIR) && $(MAKE) clean

.PHONY: all clean
.DELETE_ON_ERROR:

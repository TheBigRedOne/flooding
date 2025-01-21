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
BASELINE_FIGURE := $(PAPER_DIR)/figures/baseline_throughput.pdf
SOLUTION_FIGURE := $(PAPER_DIR)/figures/solution_throughput.pdf
PAPER_PDF := $(PAPER_DIR)/OptoFlood.pdf

# Main targets
all: $(PAPER_PDF)

# Baseline experiment results
$(BASELINE_PDF): $(BASE_DIR)/experiments/baseline/Vagrantfile $(BASE_DIR)/experiments/baseline/consumer.cpp $(BASE_DIR)/experiments/baseline/producer.cpp
	cd $(BASE_DIR)/experiments/baseline && vagrant up && vagrant ssh -c '\
		cd /home/vagrant/mini-ndn/flooding/experiments/baseline && make all;'
	mkdir -p $(BASELINE_RESULTS)
	cp $(BASE_DIR)/experiments/baseline/results/consumer_capture_throughput.pdf $(BASELINE_PDF)

# Solution experiment results
$(SOLUTION_PDF): $(BASE_DIR)/experiments/solution/Vagrantfile $(BASE_DIR)/experiments/solution/consumer_mp.cpp $(BASE_DIR)/experiments/solution/producer_mp.cpp
	cd $(BASE_DIR)/experiments/solution && vagrant up && vagrant ssh -c '\
		cd /home/vagrant/mini-ndn/flooding/experiments/solution && make all;'
	mkdir -p $(SOLUTION_RESULTS)
	cp $(BASE_DIR)/experiments/solution/results/consumer_capture_throughput.pdf $(SOLUTION_PDF)


# Copy baseline figure to paper figures directory
$(BASELINE_FIGURE): $(BASELINE_PDF)
	mkdir -p $(PAPER_DIR)/figures
	cp $(BASELINE_PDF) $(BASELINE_FIGURE)

# Copy solution figure to paper figures directory
$(SOLUTION_FIGURE): $(SOLUTION_PDF)
	mkdir -p $(PAPER_DIR)/figures
	cp $(SOLUTION_PDF) $(SOLUTION_FIGURE)

# Generate the paper
$(PAPER_PDF): $(BASELINE_FIGURE) $(SOLUTION_FIGURE)
	$(MAKE) -C $(PAPER_DIR)

# Cleanup
clean:
	cd $(BASE_DIR)/experiments/baseline && vagrant destroy -f || true
	cd $(BASE_DIR)/experiments/solution && vagrant destroy -f || true
	rm -rf $(RESULTS_DIR)
	cd $(PAPER_DIR) && $(MAKE) clean

deep-clean: clean
	rm -rf $(PAPER_DIR)/figures

.PHONY: all clean deep-clean
.DELETE_ON_ERROR:

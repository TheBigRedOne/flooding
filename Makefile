# Master Control Makefile

# Results directory on the host
HOST_RESULTS_DIR := ./results/experiments/baseline
PAPER_DIR := ./paper
PAPER_RESULTS_DIR := $(PAPER_DIR) # 将结果导入到论文文件夹
# Results directory in the VM
VM_RESULTS_DIR := /home/vagrant/mini-ndn/flooding/experiments/baseline/results

# Main targets
all: run-experiment export-results generate-paper shutdown-vm

# Start the VM and run the experiment
run-experiment:
	vagrant status | grep "running (virtualbox)" > /dev/null || vagrant up --provider virtualbox
	vagrant ssh -c '\
		if [ -d /home/vagrant/mini-ndn/flooding/experiments/baseline ]; then \
			cd /home/vagrant/mini-ndn/flooding/experiments/baseline && make all; \
		else \
			echo "Error: Path /home/vagrant/mini-ndn/flooding/experiments/baseline does not exist."; \
			exit 1; \
		fi'

# Export experiment results to host
export-results:
	# Ensure the results directory exists on the host
	mkdir -p $(HOST_RESULTS_DIR)
	mkdir -p $(PAPER_RESULTS_DIR)
	# Copy results from VM to host
	vagrant ssh -c '\
		if [ -d $(VM_RESULTS_DIR) ]; then \
			cp -r $(VM_RESULTS_DIR)/* /vagrant/$(HOST_RESULTS_DIR); \
			cp -r $(VM_RESULTS_DIR)/consumer_capture_throughput.pdf /vagrant/$(PAPER_RESULTS_DIR); \
		else \
			echo "Error: Results directory does not exist in VM." >&2; \
			exit 1; \
		fi' > /dev/null

# Generate the paper PDF
generate-paper:
	$(MAKE) -C $(PAPER_DIR)

# Shutdown the VM
shutdown-vm:
	vagrant halt

.PHONY: all run-experiment export-results generate-paper shutdown-vm

# Makefile for the BASELINE experiment, to be run inside the VM.

# --- Variables ---
PCAP_FILE := results/consumer_capture.pcap
CSV_FILE  := results/consumer_capture.csv

CXX      := g++
CXXFLAGS := -std=c++17 -g -O2
LDFLAGS  := $(shell pkg-config --cflags --libs libndn-cxx)

APP_DIR  := ../app
TOOL_DIR := ../tool
VENV_DIR := $(TOOL_DIR)/.venv
PYTHON   := $(VENV_DIR)/bin/python3

# --- Targets ---

# The main target to run the full experiment and get all result files.
all: results/disruption_times.pdf results/disruption_metrics.txt results/loss_ratio.txt results/loss_comparison.pdf results/overhead_timeseries.pdf results/overhead_total.txt

# Define a target for the virtual environment setup.
# It checks if the requirements have changed before reinstalling.
$(VENV_DIR): $(TOOL_DIR)/requirements.txt
	python3 -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install -r $(TOOL_DIR)/requirements.txt
	touch $(VENV_DIR) # Update timestamp

# The final plots/data depend on the CSV file AND the venv being ready.
results/disruption_times.pdf results/disruption_metrics.txt: $(CSV_FILE) | $(VENV_DIR)
	# Generate plots and metrics from the CSV data for R1
	$(PYTHON) $(TOOL_DIR)/plot_latency.py --input $(CSV_FILE) --output-dir results --handoff-times "120, 240"

results/loss_ratio.txt results/loss_comparison.pdf: $(CSV_FILE) | $(VENV_DIR)
	$(PYTHON) $(TOOL_DIR)/plot_loss.py --input $(CSV_FILE) --output-dir results --handoff-times "120, 240"

results/overhead_timeseries.pdf results/overhead_total.txt: $(CSV_FILE) | $(VENV_DIR)
	$(PYTHON) $(TOOL_DIR)/plot_overhead.py --input $(CSV_FILE) --output-dir results --handoff-times "120, 240"


# Convert PCAP to CSV using tshark
$(CSV_FILE): $(PCAP_FILE)
	tshark -r $< -T fields -e frame.time_epoch -e ndn.type -e ndn.name -E separator=, -E header=y -E quote=d > $@

# The PCAP result depends on the experiment script and the compiled apps.
$(PCAP_FILE): $(TOOL_DIR)/exp.py producer consumer
	mkdir -p results
	# Run the experiment script using sudo, preserving EXPERIMENT_DIR environment.
	sudo -E env EXPERIMENT_DIR=$(shell pwd) python3 $(TOOL_DIR)/exp.py

# Recipe to compile the producer.
producer: $(APP_DIR)/producer.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)

# Recipe to compile the consumer.
consumer: $(APP_DIR)/consumer.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)

# A target to clean up all generated files.
clean:
	rm -rf producer consumer results

.PHONY: all clean

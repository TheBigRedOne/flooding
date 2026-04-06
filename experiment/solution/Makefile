# Makefile for the SOLUTION experiment, to be run inside the VM.

# --- Variables ---
PCAP_FILE := results/consumer_capture.pcap
CSV_FILE  := results/consumer_capture.csv
OVERHEAD_PCAP_DIR := results/pcap_nodes
OVERHEAD_CSV := results/network_overhead.csv
OVERHEAD_EXTRACTOR := ../tool/extract_overhead_csv.py

CXX      := g++
# CRITICAL: Add -DSOLUTION_ENABLED to activate solution-specific code via preprocessor macros.
CXXFLAGS := -std=c++17 -g -O2 -DSOLUTION_ENABLED
LDFLAGS  := $(shell pkg-config --cflags --libs libndn-cxx)

APP_DIR  := ../app
TOOL_DIR := ../tool

# --- Targets ---

# The main target to produce CSVs for host-side plotting
all: $(CSV_FILE) $(OVERHEAD_CSV)



# Convert PCAP to CSV using tshark
$(CSV_FILE): $(PCAP_FILE)
	tshark -r $< -T fields -e frame.time_epoch -e frame.len -e ndn.type -e ndn.name -E separator=, -E header=y -E quote=d > $@

# Convert per-node PCAPs to a unified CSV for network-overhead analysis
$(OVERHEAD_CSV): $(PCAP_FILE) $(OVERHEAD_EXTRACTOR)
	python3 $(OVERHEAD_EXTRACTOR) --pcap-dir $(OVERHEAD_PCAP_DIR) --output $@

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

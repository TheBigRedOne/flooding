# Makefile for the SOLUTION experiment, to be run inside the VM.

# --- Variables ---
PCAP_FILE := results/consumer_capture.pcap
OVERHEAD_PCAP_DIR := results/pcap_nodes
OVERHEAD_CAPTURE_NODES := core agg1 agg2 acc1 acc2 acc3 acc4 acc5 acc6 producer consumer
OVERHEAD_PCAP_FILES := $(foreach node,$(OVERHEAD_CAPTURE_NODES),$(OVERHEAD_PCAP_DIR)/$(node).pcap)

CXX      := g++
# CRITICAL: Add -DSOLUTION_ENABLED to activate solution-specific code via preprocessor macros.
CXXFLAGS := -std=c++17 -g -O2 -DSOLUTION_ENABLED
LDFLAGS  := $(shell pkg-config --cflags --libs libndn-cxx)

APP_DIR  := ../app
TOOL_DIR := ../tool

# --- Targets ---

# The default target produces only raw experiment artifacts for host-side analysis.
all: $(PCAP_FILE) $(OVERHEAD_PCAP_FILES)

# The experiment script generates the complete raw result set in one run.
$(PCAP_FILE) $(OVERHEAD_PCAP_FILES) &: $(TOOL_DIR)/exp.py producer consumer
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
	sudo rm -rf producer consumer results

.PHONY: all clean

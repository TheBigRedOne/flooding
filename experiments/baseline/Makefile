# Baseline Test Makefile

# Base paths
BASE_DIR := $(shell pwd)
RESULTS_DIR := $(BASE_DIR)/results
TOOLS_DIR := $(BASE_DIR)/../tools

# Executable names
CONSUMER_EXEC := $(BASE_DIR)/consumer
PRODUCER_EXEC := $(BASE_DIR)/producer

# Logs and output files
CONSUMER_LOG := $(RESULTS_DIR)/consumer.log
PRODUCER_LOG := $(RESULTS_DIR)/producer.log
PCAP_FILE := $(RESULTS_DIR)/consumer_capture.pcap
PCAP_CSV := $(RESULTS_DIR)/consumer_capture.csv
THROUGHPUT_CSV := $(RESULTS_DIR)/consumer_capture_throughput.csv
THROUGHPUT_PDF := $(RESULTS_DIR)/consumer_capture_throughput.pdf

# Main targets
all: $(PCAP_FILE) $(THROUGHPUT_CSV) $(THROUGHPUT_PDF)

$(CONSUMER_EXEC):
	g++ -std=c++17 -o $(CONSUMER_EXEC) consumer.cpp $$(pkg-config --cflags --libs libndn-cxx)

$(PRODUCER_EXEC):
	g++ -std=c++17 -o $(PRODUCER_EXEC) producer.cpp $$(pkg-config --cflags --libs libndn-cxx)

$(PCAP_FILE): $(CONSUMER_EXEC) $(PRODUCER_EXEC) generate-keys
	sudo python $(TOOLS_DIR)/exp.py
	mkdir -p $(RESULTS_DIR)
	cp consumer_capture.pcap $(PCAP_FILE)

$(THROUGHPUT_CSV): $(PCAP_FILE)
	tshark -r $(PCAP_FILE) -T fields -e frame.time_epoch -e frame.len -E header=y -E separator=, -E quote=d > $(PCAP_CSV)
	python $(TOOLS_DIR)/throughput_calculation.py $(PCAP_CSV)

$(THROUGHPUT_PDF): $(THROUGHPUT_CSV)
	python $(TOOLS_DIR)/plot_throughput.py $(THROUGHPUT_CSV)

# Key generation
generate-keys:
	ndnsec key-gen /example && \
	ndnsec cert-dump -i /example > example-trust-anchor.cert && \
	ndnsec key-gen /example/LiveStream && \
	ndnsec sign-req /example/LiveStream | ndnsec cert-gen -s /example -i example | ndnsec cert-install -
	cp $(TOOLS_DIR)/trust-schema.conf .

# Cleanup
clean:
	rm -f $(CONSUMER_LOG) $(PRODUCER_LOG) $(PCAP_FILE) $(PCAP_CSV) $(THROUGHPUT_CSV) $(THROUGHPUT_PDF)
	rm -f $(CONSUMER_EXEC) $(PRODUCER_EXEC)

.PHONY: all clean generate-keys
.DELETE_ON_ERROR:

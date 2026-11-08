# Makefile for the BASELINE experiment, to be run inside the VM.

# --- Target groups ---
EXPERIMENT_RESULTS = results/consumer_capture.pcap \
                     results/pcap_nodes/core.pcap \
                     results/pcap_nodes/agg1.pcap \
                     results/pcap_nodes/agg2.pcap \
                     results/pcap_nodes/acc1.pcap \
                     results/pcap_nodes/acc2.pcap \
                     results/pcap_nodes/acc3.pcap \
                     results/pcap_nodes/acc4.pcap \
                     results/pcap_nodes/acc5.pcap \
                     results/pcap_nodes/acc6.pcap \
                     results/pcap_nodes/producer.pcap \
                     results/pcap_nodes/consumer.pcap \
                     results/params.txt \
                     results/handoffs.txt

# --- Targets ---

# The default target produces only raw experiment artifacts for host-side analysis.
all: $(EXPERIMENT_RESULTS)

# The experiment script generates the complete raw result set in one run.
$(EXPERIMENT_RESULTS) &: ../tool/common/exp.py ../tool/common/handoff_schedule.py producer consumer
	mkdir -p results
	# Pass the profile and handoff settings explicitly so they survive sudo env_reset.
	# An empty value leaves that setting unset.
	sudo -E env EXPERIMENT_DIR=$(shell pwd) NLSR_HELLO_INTERVAL='$(NLSR_HELLO_INTERVAL)' NLSR_ADJ_LSA_BUILD_INTERVAL='$(NLSR_ADJ_LSA_BUILD_INTERVAL)' NLSR_ROUTING_CALC_INTERVAL='$(NLSR_ROUTING_CALC_INTERVAL)' NLSR_SYNC_INTEREST_LIFETIME_MS='$(NLSR_SYNC_INTEREST_LIFETIME_MS)' NLSR_TUNING_PROFILE='$(NLSR_TUNING_PROFILE)' NLSR_HANDOFF_COUNT='$(NLSR_HANDOFF_COUNT)' NLSR_HANDOFF_SEQUENCE='$(NLSR_HANDOFF_SEQUENCE)' NLSR_HANDOFF_INTERVALS='$(NLSR_HANDOFF_INTERVALS)' NLSR_HANDOFF_INTERVAL_BASE='$(NLSR_HANDOFF_INTERVAL_BASE)' NLSR_HANDOFF_INTERVAL_JITTER='$(NLSR_HANDOFF_INTERVAL_JITTER)' PYTHONPATH='$(abspath ../..)' python3 -m experiment.tool.common.exp

# Recipe to compile the producer.
producer: ../app/producer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

# Recipe to compile the consumer.
consumer: ../app/consumer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

# A target to clean up all generated files.
clean:
	sudo rm -rf producer consumer results

.PHONY: all clean

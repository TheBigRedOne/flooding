# Makefile for the SOLUTION experiment, to be run inside the VM.

# Solution-box defaults: full OptoFlood enables both NLSR accelerations.
# NLSR's own nlsr.conf default remains off; these env vars are the experiment
# override. Host ablation: SOLUTION_NLSR_EVENT_DRIVEN_VERIFICATION=off maps to
# NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION=off via RUN_IN_VM_REMOTE_MAKE.
# Corridor stays off unless the smoke/host explicitly sets it on.
NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD ?= on
NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION ?= on
NLSR_CORRIDOR_PRIORITISED_ROUTING ?= off
NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY ?= 1
NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS ?= 0

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
                     results/handoffs.txt

# --- Targets ---

# The default target produces only raw experiment artifacts for host-side analysis.
all: $(EXPERIMENT_RESULTS)

# The experiment script generates the complete raw result set in one run.
$(EXPERIMENT_RESULTS) &: ../tool/exp.py producer consumer optoflood-daemon
	mkdir -p results
	# Pass NLSR switches on the env line so they survive sudo env_reset.
	sudo -E env EXPERIMENT_DIR=$(shell pwd) NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD=$(NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD) NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION=$(NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION) NLSR_CORRIDOR_PRIORITISED_ROUTING=$(NLSR_CORRIDOR_PRIORITISED_ROUTING) NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY=$(NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY) NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS=$(NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS) python3 ../tool/exp.py

# Recipe to compile the producer (plain baseline application).
producer: ../app/producer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

# Recipe to compile the consumer (plain baseline application).
consumer: ../app/consumer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

# Recipe to compile the OptoFlood mobility control daemon (solution control plane).
optoflood-daemon: ../app/optoflood-daemon.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

# A target to clean up all generated files.
clean:
	sudo rm -rf producer consumer optoflood-daemon results

.PHONY: all clean

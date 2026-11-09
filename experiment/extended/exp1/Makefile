# Exp1 guest build. Compiles the shared applications in this directory and runs
# the common experiment driver. Clean removes only these binaries and this
# directory's results.

NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD ?= on
NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION ?= on
NLSR_CORRIDOR_PRIORITISED_ROUTING ?= on
NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY ?= 1
NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS ?= 50
NLSR_HANDOFF_COUNT ?= 8
NLSR_HANDOFF_SEQUENCE ?= acc2,acc3,acc4,acc5,acc6,acc5,acc4,acc3,acc2
NLSR_HANDOFF_INTERVALS ?=
NLSR_HANDOFF_INTERVAL_BASE ?=
NLSR_HANDOFF_INTERVAL_JITTER ?=
EXP_REQUEST_INTERVAL_MS ?= 20

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

all: $(EXPERIMENT_RESULTS)

$(EXPERIMENT_RESULTS) &: ../../tool/common/exp.py ../../tool/common/handoff_schedule.py producer consumer optoflood-daemon
	mkdir -p results
	sudo -E env EXPERIMENT_DIR=$(shell pwd) NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD=$(NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD) NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION=$(NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION) NLSR_CORRIDOR_PRIORITISED_ROUTING=$(NLSR_CORRIDOR_PRIORITISED_ROUTING) NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY=$(NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY) NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS=$(NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS) NLSR_HANDOFF_COUNT='$(NLSR_HANDOFF_COUNT)' NLSR_HANDOFF_SEQUENCE='$(NLSR_HANDOFF_SEQUENCE)' NLSR_HANDOFF_INTERVALS='$(NLSR_HANDOFF_INTERVALS)' NLSR_HANDOFF_INTERVAL_BASE='$(NLSR_HANDOFF_INTERVAL_BASE)' NLSR_HANDOFF_INTERVAL_JITTER='$(NLSR_HANDOFF_INTERVAL_JITTER)' EXP_REQUEST_INTERVAL_MS='$(EXP_REQUEST_INTERVAL_MS)' PYTHONPATH='$(abspath ../../..)' python3 -m experiment.tool.common.exp

producer: ../../app/producer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

consumer: ../../app/consumer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

optoflood-daemon: ../../app/optoflood-daemon.cpp ../../app/guard_flood_id.hpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

clean:
	sudo rm -rf producer consumer optoflood-daemon results

.PHONY: all clean

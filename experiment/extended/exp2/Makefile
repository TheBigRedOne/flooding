# Exp2 guest build. Compiles the shared applications in this directory and runs
# the Exp2 driver. Clean removes only these binaries and this directory's results.

NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD ?= on
NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION ?= on
NLSR_CORRIDOR_PRIORITISED_ROUTING ?= on
NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY ?= 1
NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS ?= 50
NLSR_HANDOFF_COUNT ?= 1
NLSR_HANDOFF_SEQUENCE ?= acc2,acc3
NLSR_HANDOFF_INTERVALS ?=
NLSR_HANDOFF_INTERVAL_BASE ?= 90
NLSR_HANDOFF_INTERVAL_JITTER ?= 60
EXP2_ACTIVE_CONSUMERS ?= consumer1
EXP2_WARMUP_S ?= 20
EXP2_TAIL_S ?= 30
EXP2_SCHEDULE ?= smoke
EXP2_RUN_ID ?=

all: exp2-shared

exp2-shared: producer consumer optoflood-daemon
	mkdir -p results
	sudo -E env EXPERIMENT_DIR=$(shell pwd) NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD=$(NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD) NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION=$(NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION) NLSR_CORRIDOR_PRIORITISED_ROUTING=$(NLSR_CORRIDOR_PRIORITISED_ROUTING) NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY=$(NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY) NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS=$(NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS) NLSR_HANDOFF_COUNT='$(NLSR_HANDOFF_COUNT)' NLSR_HANDOFF_SEQUENCE='$(NLSR_HANDOFF_SEQUENCE)' NLSR_HANDOFF_INTERVALS='$(NLSR_HANDOFF_INTERVALS)' NLSR_HANDOFF_INTERVAL_BASE='$(NLSR_HANDOFF_INTERVAL_BASE)' NLSR_HANDOFF_INTERVAL_JITTER='$(NLSR_HANDOFF_INTERVAL_JITTER)' EXP2_ACTIVE_CONSUMERS='$(EXP2_ACTIVE_CONSUMERS)' EXP2_WARMUP_S='$(EXP2_WARMUP_S)' EXP2_TAIL_S='$(EXP2_TAIL_S)' EXP2_SCHEDULE='$(EXP2_SCHEDULE)' EXP2_RUN_ID='$(EXP2_RUN_ID)' EXP_REQUEST_INTERVAL_MS='20' python3 ../../tool/exp2_shared_driver.py

producer: ../../app/producer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

consumer: ../../app/consumer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

optoflood-daemon: ../../app/optoflood-daemon.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

clean:
	sudo rm -rf producer consumer optoflood-daemon results

.PHONY: all exp2-shared clean

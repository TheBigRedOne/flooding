# Exp3 guest build. Compiles the shared applications in this directory and runs
# the Exp3 driver. Clean removes only these binaries and this directory's results.

NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD ?= on
NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION ?= on
NLSR_CORRIDOR_PRIORITISED_ROUTING ?= on
NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY ?= 1
NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS ?= 50
EXP3_POPULATION ?= p1
EXP3_SCHEDULE ?= smoke
EXP3_RUN_ID ?=
EXP3_RUN_SEED ?=

all: exp3

exp3: producer consumer optoflood-daemon
	mkdir -p results
	sudo -E env EXPERIMENT_DIR=$(shell pwd) NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD=$(NLSR_RESULT_DRIVEN_ADJ_LSA_BUILD) NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION=$(NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION) NLSR_CORRIDOR_PRIORITISED_ROUTING=$(NLSR_CORRIDOR_PRIORITISED_ROUTING) NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY=$(NLSR_CORRIDOR_ADJ_LSA_SYNC_PUBLISH_DELAY) NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS=$(NLSR_EVENT_DRIVEN_VERIFICATION_TIMEOUT_MS) EXP3_POPULATION='$(EXP3_POPULATION)' EXP3_SCHEDULE='$(EXP3_SCHEDULE)' EXP3_RUN_ID='$(EXP3_RUN_ID)' EXP3_RUN_SEED='$(EXP3_RUN_SEED)' EXP_REQUEST_INTERVAL_MS='20' python3 ../../tool/exp3_driver.py

producer: ../../app/producer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

consumer: ../../app/consumer.cpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

optoflood-daemon: ../../app/optoflood-daemon.cpp ../../app/guard_flood_id.hpp
	g++ -std=c++17 -g -O2 -o $@ $< $$(pkg-config --cflags --libs libndn-cxx)

clean:
	sudo rm -rf producer consumer optoflood-daemon results

.PHONY: all exp3 clean

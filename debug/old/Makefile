# Makefile for debug/old experiment
# Run this inside the VM at /home/vagrant/mini-ndn/flooding

# Variables
CXX = g++
CXXFLAGS = -std=c++17 -g -O2
LDFLAGS = $(shell pkg-config --cflags --libs libndn-cxx)

# Default mode (can be overridden: make APP_MODE=solution)
APP_MODE ?= baseline

# Main target
all: run-experiment

# Compile applications based on mode
ifeq ($(APP_MODE),baseline)
producer: producer.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)
consumer: consumer.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)
else
producer: producer_mp.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)
consumer: consumer_mp.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)
endif

# Run experiment
run-experiment: producer consumer
	@echo "Starting experiment in $(APP_MODE) mode..."
	sudo python3 exp.py

# Clean
clean:
	rm -f producer consumer *.pcap *.log

.PHONY: all run-experiment clean

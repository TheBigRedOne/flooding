PROVIDER ?= virtualbox

# Provider goal rewriting: allow `make kvm …` or `make vb …` without double execution
ifeq ($(firstword $(MAKECMDGOALS)),kvm)
  PROVIDER := libvirt
  override MAKECMDGOALS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
endif
ifeq ($(firstword $(MAKECMDGOALS)),vb)
  PROVIDER := virtualbox
  override MAKECMDGOALS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
endif

# Purpose: Orchestrate OptoFlood validation tests (S1–S5) on the solution box/VM
# Interface:
#   - make kvm|vb test-s1 ... test-s5   Run a single test case
#   - make kvm|vb test-all              Run all test cases sequentially
#   - make kvm|vb vm-up|vm-halt|vm-destroy  Control solution VM lifecycle
# Parameters:
#   - PROVIDER: libvirt (kvm) or virtualbox (vb); set via provider wrapper goals above

ROOT_DIR := ..
SOLUTION_BOX := $(ROOT_DIR)/box/solution/solution.$(PROVIDER).box
VAGRANT_SOLUTION := VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=$(ROOT_DIR)/test vagrant

# Remote working directory for rsync-based test runs
REMOTE_DIR := /home/vagrant/flooding

# Local rsync wrapper using ssh-config generated for the solution VM
RSYNC_SOLUTION := rsync -avH -e "ssh -F .ssh_config_solution"

# Files/dirs excluded from rsync push (keep host-only artifacts out of VM)
RSYNC_EXCLUDES := \
	--exclude .git \
	--exclude .vagrant \
	--exclude results \
	--exclude paper/bin

.PHONY: test-all prep sync test-s1 test-s2 test-s3 test-s4 test-s5 \
        vm-up vm-halt vm-destroy

# Ensure solution box exists (build via parent Makefile if missing)
$(SOLUTION_BOX):
	$(MAKE) -C $(ROOT_DIR) PROVIDER=$(PROVIDER) box-solution

# Convenience VM lifecycle helpers (explicit; not auto-run unless invoked)
vm-up: $(SOLUTION_BOX)
	ACTUAL_SOLUTION_BOX_PATH="$(SOLUTION_BOX)" $(VAGRANT_SOLUTION) up

vm-halt:
	$(VAGRANT_SOLUTION) halt -f || true

vm-destroy:
	$(VAGRANT_SOLUTION) destroy -f || true

# Sync sources from host to VM via rsync (standardized entry)
sync: vm-up
	$(VAGRANT_SOLUTION) ssh-config --host solution > .ssh_config_solution
	$(RSYNC_SOLUTION) $(RSYNC_EXCLUDES) $(ROOT_DIR)/ solution:$(REMOTE_DIR)/

# Prepare: build apps in-VM for test, run dedicated test topology, and fetch artifacts
prep: check-solution-box vm-up sync
	# Build apps inside VM from rsynced sources under $(REMOTE_DIR)
	$(VAGRANT_SOLUTION) ssh -c 'set -e; test -d $(REMOTE_DIR)/experiment/app || (echo "rsync failed: $(REMOTE_DIR)/experiment/app missing" && exit 1)'
	$(VAGRANT_SOLUTION) ssh -c 'set -e; cd $(REMOTE_DIR)/test && rm -f producer consumer && PKG="$$(pkg-config --cflags --libs libndn-cxx)" && g++ -std=c++17 -g -O2 -DSOLUTION_ENABLED -o producer $(REMOTE_DIR)/experiment/app/producer.cpp $$PKG && chmod -v +x producer'
	$(VAGRANT_SOLUTION) ssh -c 'set -e; cd $(REMOTE_DIR)/test && PKG="$$(pkg-config --cflags --libs libndn-cxx)" && g++ -std=c++17 -g -O2 -DSOLUTION_ENABLED -o consumer $(REMOTE_DIR)/experiment/app/consumer.cpp $$PKG && chmod -v +x consumer'
	# Ensure trust schema is available beside binaries (fail if missing)
	$(VAGRANT_SOLUTION) ssh -c 'set -e; test -f $(REMOTE_DIR)/experiment/app/trust-schema.conf && cp -f $(REMOTE_DIR)/experiment/app/trust-schema.conf $(REMOTE_DIR)/test/'
	# Ensure tshark loads updated NDN dissector (ndn.lua)
	$(VAGRANT_SOLUTION) ssh -c 'set -e; sudo mkdir -p /usr/local/share/ndn-dissect-wireshark && sudo cp $(REMOTE_DIR)/experiment/tool/ndn.lua /usr/local/share/ndn-dissect-wireshark/ndn.lua'
	# Preflight check for tshark presence
	$(VAGRANT_SOLUTION) ssh -c 'EXPERIMENT_DIR=$(REMOTE_DIR)/test WIRESHARK_RUN_FROM_BUILD_DIRECTORY=1 WIRESHARK_PLUGIN_DIR= /usr/bin/sudo -E tshark -v >/dev/null 2>&1'
	# Run test topology; generate artifacts under $(REMOTE_DIR)/test
	$(VAGRANT_SOLUTION) ssh -c 'EXPERIMENT_DIR=$(REMOTE_DIR)/test WIRESHARK_RUN_FROM_BUILD_DIRECTORY=1 WIRESHARK_PLUGIN_DIR= LUA_PATH="/usr/local/share/ndn-dissect-wireshark/?.lua;;" LUA_CPATH=";;" /usr/bin/sudo -E python3 $(REMOTE_DIR)/test/exp_test.py'
	# Rsync back test artifacts to host test/ (only pcap and snapshots/logs)
	$(VAGRANT_SOLUTION) ssh -c 'mkdir -p $(REMOTE_DIR)/test/pcap'
	mkdir -p $(ROOT_DIR)/test/pcap
	$(RSYNC_SOLUTION) solution:$(REMOTE_DIR)/test/pcap/ $(ROOT_DIR)/test/pcap/
	$(RSYNC_SOLUTION) --include "r*_rib.txt" --include "*producer.log" --include "*consumer.log" --include "tcpdump_*.log" --exclude "*" solution:$(REMOTE_DIR)/test/ $(ROOT_DIR)/test/
	@echo "Artifacts synced to $(ROOT_DIR)/test/"

# Test aggregator (ensures one experiment run, then checks)
test-all: prep validate-s1 validate-s4 validate-s3 validate-s2 validate-s5

# S1: Data-side controllable flooding (LP OptoHopLimit decremented per hop)
validate-s1:
	@echo "[S1] Validating Data OptoHopLimit decrement and stop";
	python3 validate.py s1 || (echo "S1 FAIL" && exit 1)

# S2: Data deduplication and rate limiting
validate-s2:
	@echo "[S2] Validating Data deduplication & rate limiting";
	python3 validate.py s2 || (echo "S2 FAIL" && exit 1)

# S3: TFIB behavior (insert/hit/expire ~1s)
validate-s3:
	@echo "[S3] Validating TFIB insert/hit/expire";
	python3 validate.py s3 || (echo "S3 FAIL" && exit 1)

# S4: Interest-side controllable flooding (ApplicationParameters + HopLimit)
validate-s4:
	@echo "[S4] Validating Interest HopLimit decrement under miss";
	python3 validate.py s4 || (echo "S4 FAIL" && exit 1)

# S5: Fast-LSA (mgmt command + short-lived RIB with throttling/dedup)
validate-s5:
	@echo "[S5] Validating Fast-LSA throttle/dedup and short-lived RIB";
	python3 validate.py s5 || (echo "S5 FAIL" && exit 1)

.PHONY: kvm vb
kvm:
	@true

vb:
	@true

.DELETE_ON_ERROR:

.NOTINTERMEDIATE:



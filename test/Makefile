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

.PHONY: test-all prep test-s1 test-s2 test-s3 test-s4 test-s5 \
        vm-up vm-halt vm-destroy check-solution-box

check-solution-box:
	@if [ ! -f "$(SOLUTION_BOX)" ]; then \
	  echo "Missing solution box: $(SOLUTION_BOX)"; \
	  echo "Please run 'make $(PROVIDER) box-solution' at $(ROOT_DIR)"; \
	  exit 1; \
	fi

# Convenience VM lifecycle helpers (explicit; not auto-run unless invoked)
vm-up: check-solution-box
	ACTUAL_SOLUTION_BOX_PATH="$(SOLUTION_BOX)" $(VAGRANT_SOLUTION) up

vm-halt:
	$(VAGRANT_SOLUTION) halt -f || true

vm-destroy:
	$(VAGRANT_SOLUTION) destroy -f || true

# Prepare: build apps in-VM for test, run dedicated test topology, and fetch artifacts
prep: check-solution-box vm-up
	# Build apps inside VM (solution mode)
	$(VAGRANT_SOLUTION) ssh -c 'cd /home/vagrant/mini-ndn/flooding/experiment/solution && make clean && make producer && make consumer'
	# Ensure tshark loads updated NDN dissector (ndn.lua)
	$(VAGRANT_SOLUTION) ssh -c 'sudo mkdir -p /usr/local/share/ndn-dissect-wireshark && sudo cp /home/vagrant/mini-ndn/flooding/experiment/tool/ndn.lua /usr/local/share/ndn-dissect-wireshark/ndn.lua'
	# Run test topology and capture multi-point pcaps (outputs under /home/vagrant/mini-ndn/flooding/test)
	$(VAGRANT_SOLUTION) ssh -c 'EXPERIMENT_DIR=/home/vagrant/mini-ndn/flooding/test WIRESHARK_RUN_FROM_BUILD_DIRECTORY=1 WIRESHARK_PLUGIN_DIR= /usr/bin/sudo -E tshark -v >/dev/null 2>&1 || true'
	$(VAGRANT_SOLUTION) ssh -c 'EXPERIMENT_DIR=/home/vagrant/mini-ndn/flooding/test WIRESHARK_RUN_FROM_BUILD_DIRECTORY=1 WIRESHARK_PLUGIN_DIR= LUA_PATH="/usr/local/share/ndn-dissect-wireshark/?.lua;;" LUA_CPATH=";;" /usr/bin/sudo -E python3 /home/vagrant/mini-ndn/flooding/test/exp_test.py'
	# Rsync back test artifacts to host test/
	SSHCFG=.ssh_config_solution; \
		$(VAGRANT_SOLUTION) ssh-config --host solution > $$SSHCFG; \
		rsync -avH -e "ssh -F $$SSHCFG" solution:/home/vagrant/mini-ndn/flooding/test/ $(ROOT_DIR)/test/
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



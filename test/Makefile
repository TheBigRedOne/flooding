PROVIDER ?= virtualbox
export PROVIDER

# Purpose: Run solution VM validations (S1–S5) and manage VM lifecycle
# Interface: test-all, validate-s[1..5], vm-up|vm-halt|vm-destroy; PROVIDER=libvirt|virtualbox

ROOT_DIR := ..
SOLUTION_BOX := $(ROOT_DIR)/box/solution/solution.$(PROVIDER).box
BOX_NAME := optoflood-solution-test
VAGRANT_SOLUTION := VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=$(ROOT_DIR)/test vagrant
VAGRANT_ENV := ACTUAL_SOLUTION_BOX_PATH="$(SOLUTION_BOX)" SOLUTION_BOX_NAME=$(BOX_NAME)
SSH_CONFIG := .ssh_config_solution

# Remote working directory for rsync-based test runs
REMOTE_DIR := /home/vagrant/flooding

# Local rsync wrapper using ssh-config generated for the solution VM
RSYNC_SOLUTION := rsync -avH -e "ssh -F $(SSH_CONFIG)"

# Files/dirs excluded from rsync push (keep host-only artifacts out of VM)
RSYNC_EXCLUDES := \
	--exclude .git \
	--exclude .vagrant \
	--exclude results \
	--exclude paper/bin

.PHONY: test-all validate sync test-s1 test-s2 test-s3 test-s4 test-s5 \
        vm-up vm-halt vm-destroy

# Ensure solution box exists (build via parent Makefile if missing)
$(SOLUTION_BOX):
	$(MAKE) -C $(ROOT_DIR) PROVIDER=$(PROVIDER) box-solution

# Convenience VM lifecycle helpers (explicit; not auto-run unless invoked)
vm-up: $(SOLUTION_BOX)
	$(VAGRANT_ENV) $(VAGRANT_SOLUTION) up --provision

vm-halt:
	$(VAGRANT_SOLUTION) halt -f || true

vm-destroy:
	$(VAGRANT_SOLUTION) destroy -f || true

# Ensure VM is recreated from the latest solution box and emit SSH config
$(SSH_CONFIG): $(ROOT_DIR)/test/Vagrantfile $(SOLUTION_BOX)
	# Force destroy to avoid stale base box snapshots
	$(VAGRANT_SOLUTION) destroy -f || true
	# Remove previously cached box to force reload from local package
	$(VAGRANT_SOLUTION) box remove $(BOX_NAME) --provider=$(PROVIDER) || true
	$(VAGRANT_ENV) $(VAGRANT_SOLUTION) up --provision
	$(VAGRANT_SOLUTION) ssh-config --host solution > $(SSH_CONFIG)

# Sync sources from host to VM via rsync (standardized entry)
sync: $(SSH_CONFIG)
	$(RSYNC_SOLUTION) $(RSYNC_EXCLUDES) $(ROOT_DIR)/ solution:$(REMOTE_DIR)/

# Expected artifacts on host (collected under results/test)
RESULTS_DIR := $(ROOT_DIR)/results/test
REMOTE_RESULTS_DIR := $(REMOTE_DIR)/results/test
PCAP_DIR := $(RESULTS_DIR)/pcap
PCAPS := $(PCAP_DIR)/consumer.pcap $(PCAP_DIR)/producer.pcap $(PCAP_DIR)/r1.pcap $(PCAP_DIR)/r2.pcap $(PCAP_DIR)/r3.pcap $(PCAP_DIR)/r4.pcap $(PCAP_DIR)/r5.pcap
RIB_NODES := r1 r2 r3 r4 r5
T1_LABELS := T1_0 T1_1 T1_2 T1_3 T1_4
RIBS := $(foreach n,$(RIB_NODES),$(foreach t,$(T1_LABELS),$(RESULTS_DIR)/$(n)_$(t)_rib.txt)) \
        $(foreach n,$(RIB_NODES),$(RESULTS_DIR)/$(n)_T2_rib.txt)
VALIDATE_OK := $(ROOT_DIR)/test/.validate_ok
VM_VALIDATE_STAMP := $(RESULTS_DIR)/.validate_ok_vm

# Produce test artifacts via one VM run, then rsync back (grouped target)
$(PCAPS) $(RIBS) &: sync
	# Build apps inside VM from rsynced sources under $(REMOTE_DIR)
	$(VAGRANT_SOLUTION) ssh -c 'set -e; test -d $(REMOTE_DIR)/experiment/app || (echo "rsync failed: $(REMOTE_DIR)/experiment/app missing" && exit 1)'
	$(VAGRANT_SOLUTION) ssh -c 'set -e; cd $(REMOTE_DIR)/test && rm -f producer consumer && PKG="$$(pkg-config --cflags --libs libndn-cxx)" && g++ -std=c++17 -g -O2 -DSOLUTION_ENABLED -o producer $(REMOTE_DIR)/experiment/app/producer.cpp $$PKG && chmod -v +x producer'
	$(VAGRANT_SOLUTION) ssh -c 'set -e; cd $(REMOTE_DIR)/test && PKG="$$(pkg-config --cflags --libs libndn-cxx)" && g++ -std=c++17 -g -O2 -DSOLUTION_ENABLED -o consumer $(REMOTE_DIR)/experiment/app/consumer.cpp $$PKG && chmod -v +x consumer'
	# Ensure trust schema is available beside binaries (fail if missing)
	$(VAGRANT_SOLUTION) ssh -c 'set -e; test -f $(REMOTE_DIR)/experiment/app/trust-schema.conf && cp -f $(REMOTE_DIR)/experiment/app/trust-schema.conf $(REMOTE_DIR)/test/'
	# Ensure tshark loads updated NDN dissector (ndn.lua)
	$(VAGRANT_SOLUTION) ssh -c 'set -e; sudo mkdir -p /usr/local/share/ndn-dissect-wireshark && sudo cp $(REMOTE_DIR)/experiment/tool/ndn.lua /usr/local/share/ndn-dissect-wireshark/ndn.lua'
	# Preflight check for tshark presence
	$(VAGRANT_SOLUTION) ssh -c 'EXPERIMENT_DIR=$(REMOTE_DIR)/test RESULTS_DIR=$(REMOTE_RESULTS_DIR) WIRESHARK_RUN_FROM_BUILD_DIRECTORY=1 WIRESHARK_PLUGIN_DIR= /usr/bin/sudo -E tshark -v >/dev/null 2>&1'
	# Run test topology; generate artifacts under $(REMOTE_RESULTS_DIR)
	$(VAGRANT_SOLUTION) ssh -c 'EXPERIMENT_DIR=$(REMOTE_DIR)/test RESULTS_DIR=$(REMOTE_RESULTS_DIR) WIRESHARK_RUN_FROM_BUILD_DIRECTORY=1 WIRESHARK_PLUGIN_DIR= LUA_PATH="/usr/local/share/ndn-dissect-wireshark/?.lua;;" LUA_CPATH=";;" /usr/bin/sudo -E python3 $(REMOTE_DIR)/test/exp_test.py'
	# Ensure result directories exist in VM
	$(VAGRANT_SOLUTION) ssh -c 'mkdir -p $(REMOTE_RESULTS_DIR)/pcap'
	# Run validation inside VM (uses system python3 + tshark in box)
	$(VAGRANT_SOLUTION) ssh -c 'cd $(REMOTE_DIR)/test && RESULTS_DIR=$(REMOTE_RESULTS_DIR) /usr/bin/sudo -E python3 validate.py'
	$(VAGRANT_SOLUTION) ssh -c 'cd $(REMOTE_DIR)/test && /usr/bin/sudo chown -R vagrant:vagrant $(REMOTE_RESULTS_DIR) && echo OK > $(REMOTE_RESULTS_DIR)/.validate_ok_vm'
	# Rsync back test artifacts (including VM validate stamp) to host results/test
	mkdir -p $(RESULTS_DIR)
	$(RSYNC_SOLUTION) solution:$(REMOTE_RESULTS_DIR)/ $(RESULTS_DIR)/
	@echo "Artifacts synced to $(RESULTS_DIR)/"

# Validation stamp (runs all validations)
$(VALIDATE_OK): $(PCAPS) $(RIBS) $(VM_VALIDATE_STAMP)
	@test -f $(VM_VALIDATE_STAMP) || (echo "VM validation missing: $(VM_VALIDATE_STAMP)" && exit 1)
	@echo OK > $@

validate: $(VALIDATE_OK)

# Test aggregator
test-all: $(VALIDATE_OK)

# S1: Data-side controllable flooding (PCAP evidence)
validate-s1:
	@echo "[S1] Validating OptoFlood data flooding in PCAP";
	RESULTS_DIR=$(RESULTS_DIR) python3 validate.py s1 || (echo "S1 FAIL" && exit 1)

# S2: Data deduplication
validate-s2:
	@echo "[S2] Validating Data deduplication";
	RESULTS_DIR=$(RESULTS_DIR) python3 validate.py s2 || (echo "S2 FAIL" && exit 1)

# S3: TFIB update + forwarding
validate-s3:
	@echo "[S3] Validating TFIB update and forwarding";
	RESULTS_DIR=$(RESULTS_DIR) python3 validate.py s3 || (echo "S3 FAIL" && exit 1)

# S4: Interest-side controllable flooding (PCAP evidence)
validate-s4:
	@echo "[S4] Validating Interest HopLimit decrement in PCAP";
	RESULTS_DIR=$(RESULTS_DIR) python3 validate.py s4 || (echo "S4 FAIL" && exit 1)

# S5: Fast-LSA short-lived optoflood route
validate-s5:
	@echo "[S5] Validating Fast-LSA optoflood route appearance/expiry";
	RESULTS_DIR=$(RESULTS_DIR) python3 validate.py s5 || (echo "S5 FAIL" && exit 1)

.PHONY: kvm vb
kvm:
	@true

vb:
	@true

.DELETE_ON_ERROR:

.NOTINTERMEDIATE:



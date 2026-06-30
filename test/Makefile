PROVIDER ?= virtualbox
export PROVIDER

# Purpose: Run solution VM validations (S1–S5) and manage VM lifecycle
# Interface: test-all, validate-s[1..5], vm-up|vm-halt|vm-destroy; PROVIDER=kvm|vb

# Host->VM sync stamp to avoid re-running test flow when nothing changed.
SYNC_INPUTS := \
	../test/Makefile \
	../test/Vagrantfile \
	../test/exp_test.py \
	../test/validate.py \
	../experiment/app/producer.cpp \
	../experiment/app/consumer.cpp \
	../experiment/app/trust-schema.conf \
	../experiment/tool/ndn.lua

# Expected artifacts on host (collected under test/results)
PCAPS := ../test/results/pcap/consumer.pcap \
         ../test/results/pcap/producer.pcap \
         ../test/results/pcap/r1.pcap \
         ../test/results/pcap/r2.pcap \
         ../test/results/pcap/r3.pcap \
         ../test/results/pcap/r4.pcap \
         ../test/results/pcap/r5.pcap
RIBS  := ../test/results/r3_T1_rib.txt \
         ../test/results/r3_T2_rib.txt

.PHONY: test-all validate sync test-s1 test-s2 test-s3 test-s4 test-s5 \
        vm-up vm-halt vm-destroy

# Ensure solution box exists (build via parent Makefile if missing)
../box/solution/solution.$(PROVIDER).box:
	$(MAKE) -C .. PROVIDER=$(PROVIDER) box-solution

# Convenience VM lifecycle helpers (explicit; not auto-run unless invoked)
vm-up: ../box/solution/solution.$(PROVIDER).box
	ACTUAL_SOLUTION_BOX_PATH="../box/solution/solution.$(PROVIDER).box" SOLUTION_BOX_NAME=optoflood-solution-test VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant up --provision
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh-config --host solution > .ssh_config_solution

vm-halt:
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant halt -f || true

vm-destroy:
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant destroy -f || true

# Sync sources from host to VM via rsync (standardized entry)
sync: ../test/.sync_solution_$(PROVIDER)

# Recreate the dedicated test VM from the latest solution box and sync inputs.
../test/.sync_solution_$(PROVIDER): ../test/Vagrantfile ../box/solution/solution.$(PROVIDER).box $(SYNC_INPUTS)
	# Force destroy to avoid stale base box snapshots
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant destroy -f || true
	# Remove previously cached box to force reload from local package
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant box remove optoflood-solution-test --provider=$(PROVIDER) || true
	ACTUAL_SOLUTION_BOX_PATH="../box/solution/solution.$(PROVIDER).box" SOLUTION_BOX_NAME=optoflood-solution-test VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant up --provision
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh-config --host solution > .ssh_config_solution
	rsync -avH -e "ssh -F .ssh_config_solution" --exclude .git --exclude .vagrant --exclude results --exclude paper/bin ../ solution:/home/vagrant/flooding/
	@echo OK > $@

# Produce test artifacts via one dedicated VM run, then rsync back.
$(PCAPS) $(RIBS) ../test/results/.validate_ok_vm &: ../test/.sync_solution_$(PROVIDER)
	ACTUAL_SOLUTION_BOX_PATH="../box/solution/solution.$(PROVIDER).box" SOLUTION_BOX_NAME=optoflood-solution-test VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant up --provision
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh-config --host solution > .ssh_config_solution
	# Build apps inside VM from rsynced sources under /home/vagrant/flooding
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'set -e; test -d /home/vagrant/flooding/experiment/app || (echo "rsync failed: /home/vagrant/flooding/experiment/app missing" && exit 1)'
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'set -e; cd /home/vagrant/flooding/test && rm -f producer consumer && PKG="$$(pkg-config --cflags --libs libndn-cxx)" && g++ -std=c++17 -g -O2 -DSOLUTION_ENABLED -o producer /home/vagrant/flooding/experiment/app/producer.cpp $$PKG && chmod -v +x producer'
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'set -e; cd /home/vagrant/flooding/test && PKG="$$(pkg-config --cflags --libs libndn-cxx)" && g++ -std=c++17 -g -O2 -DSOLUTION_ENABLED -o consumer /home/vagrant/flooding/experiment/app/consumer.cpp $$PKG && chmod -v +x consumer'
	# Ensure trust schema is available beside binaries (fail if missing)
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'set -e; test -f /home/vagrant/flooding/experiment/app/trust-schema.conf && cp -f /home/vagrant/flooding/experiment/app/trust-schema.conf /home/vagrant/flooding/test/'
	# Ensure tshark loads updated NDN dissector (ndn.lua)
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'set -e; sudo mkdir -p /usr/local/share/ndn-dissect-wireshark && sudo cp /home/vagrant/flooding/experiment/tool/ndn.lua /usr/local/share/ndn-dissect-wireshark/ndn.lua'
	# Preflight check for tshark presence
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'EXPERIMENT_DIR=/home/vagrant/flooding/test WIRESHARK_RUN_FROM_BUILD_DIRECTORY=1 WIRESHARK_PLUGIN_DIR= /usr/bin/sudo -E tshark -v >/dev/null 2>&1'
	# Run test topology; generate artifacts under /home/vagrant/flooding/test
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'EXPERIMENT_DIR=/home/vagrant/flooding/test WIRESHARK_RUN_FROM_BUILD_DIRECTORY=1 WIRESHARK_PLUGIN_DIR= LUA_PATH="/usr/local/share/ndn-dissect-wireshark/?.lua;;" LUA_CPATH=";;" /usr/bin/sudo -E python3 /home/vagrant/flooding/test/exp_test.py'
	# Ensure result directories exist in VM
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'mkdir -p /home/vagrant/flooding/test/results/pcap'
	# Run validation inside VM (uses system python3 + tshark in box)
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'cd /home/vagrant/flooding/test && /usr/bin/sudo -E sh -c "rm -f results/.validate_ok_vm results/.validate_fail; python3 validate.py && echo OK > results/.validate_ok_vm || echo FAIL > results/.validate_fail"'
	# Ensure rsync can read results after validation
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant ssh -c 'cd /home/vagrant/flooding/test && /usr/bin/sudo chown -R vagrant:vagrant /home/vagrant/flooding/test/results'
	# Rsync back test artifacts (including VM validate stamp) to host test/results
	mkdir -p ../test/results
	rsync -avH -e "ssh -F .ssh_config_solution" solution:/home/vagrant/flooding/test/results/ ../test/results/
	# Power off the dedicated test VM once artifacts are collected.
	VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD=../test vagrant halt -f || true
	@echo "Artifacts synced to ../test/results/"

# Validation stamp (runs all validations)
../test/.validate_ok: $(PCAPS) $(RIBS) ../test/results/.validate_ok_vm
	@test -f ../test/results/.validate_ok_vm || (echo "VM validation missing: ../test/results/.validate_ok_vm" && exit 1)
	@echo OK > $@

validate: ../test/.validate_ok

# Test aggregator
test-all: ../test/.validate_ok

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

# S4: Interest-side controllable flooding (filters mgmt interests)
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



# Master Control Makefile

# Results from experiments
BASELINE_PDF := results/baseline/consumer_capture_throughput.pdf
SOLUTION_PDF := results/solution/consumer_capture_throughput.pdf

# Paper dependencies and output
MAIN_TEX := paper/OptoFlood.tex
BASELINE_FIGURE := paper/figures/baseline_throughput.pdf
SOLUTION_FIGURE := paper/figures/solution_throughput.pdf
PAPER_PDF := paper/OptoFlood.pdf
STATIC_FIGURES := paper/figures/NLSR_Work_Flow.png \
                  paper/figures/Producer_Mobility_Problems.png \
                  paper/figures/Topology.png
ALL_FIGURES := $(STATIC_FIGURES) $(BASELINE_FIGURE) $(SOLUTION_FIGURE)

# Experiment source files
BASELINE_SRCS := experiments/baseline/Vagrantfile \
                experiments/baseline/Makefile \
                experiments/baseline/consumer.cpp \
                experiments/baseline/producer.cpp

SOLUTION_SRCS := experiments/solution/Vagrantfile \
                experiments/solution/Makefile \
                experiments/solution/consumer_mp.cpp \
                experiments/solution/producer_mp.cpp

# Common tools used by both experiments
TOOLS_SRCS := experiments/tools/exp.py \
             experiments/tools/plot_throughput.py \
             experiments/tools/throughput_calculation.py \
             experiments/tools/trust-schema.conf

# Main target
all: $(PAPER_PDF)

# Ensure results directories exist
results:
	mkdir $@

results/baseline: | results
	mkdir $@

results/solution: | results
	mkdir $@

paper/figures:
	mkdir $@

# Boxes check
boxes/initial/initial.box:   boxes/initial/Vagrantfile
	-rm -f $@
	VAGRANT_CWD=boxes/initial vagrant up
	VAGRANT_CWD=boxes/initial vagrant package --output $@
	VAGRANT_CWD=boxes/initial vagrant halt
	VAGRANT_CWD=boxes/initial vagrant destroy -f

boxes/baseline/baseline.box: boxes/baseline/Vagrantfile boxes/initial/initial.box
	-rm -f $@
	VAGRANT_CWD=boxes/baseline vagrant up
	VAGRANT_CWD=boxes/baseline vagrant package --output $@
	VAGRANT_CWD=boxes/baseline vagrant halt
	VAGRANT_CWD=boxes/baseline vagrant destroy -f

boxes/solution/solution.box: boxes/solution/Vagrantfile boxes/initial/initial.box
	-rm -f $@
	VAGRANT_CWD=boxes/solution vagrant up
	VAGRANT_CWD=boxes/solution vagrant package --output $@
	VAGRANT_CWD=boxes/solution vagrant halt
	VAGRANT_CWD=boxes/solution vagrant destroy -f

build-boxes: boxes/baseline/baseline.box boxes/baseline/baseline.box

# SSH config file for baseline experiment
.ssh_config_baseline: experiments/baseline/Vagrantfile boxes/baseline/baseline.box
	VAGRANT_CWD=experiments/baseline vagrant up
	VAGRANT_CWD=experiments/baseline vagrant ssh-config --host baseline > .ssh_config_baseline

# SSH config file for solution experiment
.ssh_config_solution: experiments/solution/Vagrantfile boxes/solution/solution.box
	VAGRANT_CWD=experiments/solution vagrant up
	VAGRANT_CWD=experiments/solution vagrant ssh-config --host solution > .ssh_config_solution

# Rsync commands
RSYNC_BASELINE = rsync -avH -e "ssh -F .ssh_config_baseline"
RSYNC_SOLUTION = rsync -avH -e "ssh -F .ssh_config_solution"

# Baseline experiment results
$(BASELINE_PDF): $(BASELINE_SRCS) $(TOOLS_SRCS) .ssh_config_baseline | results/baseline
	VAGRANT_CWD=experiments/baseline vagrant up
	VAGRANT_CWD=experiments/baseline vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding/experiments/baseline && make all'
	$(RSYNC_BASELINE) baseline:/home/vagrant/mini-ndn/flooding/experiments/baseline/results/ results/baseline
	VAGRANT_CWD=experiments/baseline vagrant halt -f || true

# Solution experiment results
$(SOLUTION_PDF): $(SOLUTION_SRCS) $(TOOLS_SRCS) .ssh_config_solution | results/solution
	VAGRANT_CWD=experiments/solution vagrant up
	VAGRANT_CWD=experiments/solution vagrant ssh -c 'cd /home/vagrant/mini-ndn/flooding/experiments/solution && make all'
	$(RSYNC_SOLUTION) solution:/home/vagrant/mini-ndn/flooding/experiments/solution/results/ results/solution; \
	VAGRANT_CWD=experiments/solution vagrant halt -f || true

# Copy baseline figure to paper figures directory
$(BASELINE_FIGURE): $(BASELINE_PDF) | paper/figures
	cp $< $@

# Copy solution figure to paper figures directory
$(SOLUTION_FIGURE): $(SOLUTION_PDF) | paper/figures
	cp $< $@

# Generate the paper
$(PAPER_PDF): $(MAIN_TEX) $(ALL_FIGURES) | paper
	$(MAKE) -C paper

# Cleanup
clean: clean-ssh-config
	rm -rf results
	cd paper && $(MAKE) clean

deep-clean: clean
	rm -rf $(BASELINE_FIGURE) $(SOLUTION_FIGURE) $(PAPER_PDF)
	VAGRANT_CWD=experiments/baseline vagrant destroy -f
	VAGRANT_CWD=experiments/solution vagrant destroy -f
	VAGRANT_CWD=boxes/baseline vagrant destroy -f
	VAGRANT_CWD=boxes/solution vagrant destroy -f
	VAGRANT_CWD=boxes/initial  vagrant destroy -f
	vagrant box remove boxes/baseline/baseline.box || true
	vagrant box remove boxes/solution/solution.box || true
	vagrant box remove boxes/initial/initial.box || true
	rm -f boxes/baseline/baseline.box
	rm -f boxes/solution/solution.box
	rm -f boxes/initial/initial.box


# Clean SSH config file
clean-ssh-config:
	rm -f .ssh_config_baseline .ssh_config_solution

.PHONY: all build-boxes clean deep-clean clean-ssh-config 

.DELETE_ON_ERROR:

.NOTINTERMEDIATE:

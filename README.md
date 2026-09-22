This project uses Vagrant to create reproducible experiment environments.

## Prerequisites

- Vagrant 2.4.0 or later.
- A virtualization provider:
  - **VirtualBox (default):** VirtualBox 7.0 or later.
  - **KVM:** A working KVM/libvirt setup.


## Quick Start

To run the full workflow (build VMs, run the baseline parameter set and the solution experiment, analyze data, and build the paper PDF), execute:

```bash
# Using the default VirtualBox provider
make all

# Using KVM/libvirt
make PROVIDER=libvirt all
```

### Parallel execution

The post-experiment host-side pipeline (pcap-to-CSV decoding, metric
computation, plotting) is CPU-bound on `tshark` and dominates wall-clock time
once the VMs have produced the raw artifacts. Add `-j N` to use `N` host cores
for those steps:

```bash
# Use 8 cores for host-side analysis.
make -j 8 PROVIDER=libvirt all

# Use all available cores.
make -j $(nproc) PROVIDER=libvirt all
```

The Makefile chains every VM-launching rule through order-only prerequisites
so that all VM stages remain strictly serial under `make -j N`, regardless of
how many cores are available:

```
box/initial -> box/baseline -> g0/r1 -> ... -> g0/r5 -> g1/r1 -> ... -> g4/r5
            -> box/solution -> test -> solution/r1 -> ... -> solution/r5 -> exp1
```

Baseline tuning is 5 profiles × 5 runs. The OptoFlood comparison is 5 runs.
Each of those runs is one round trip of 8 hand-offs. Exp 1 keeps its own
K=16 zero-jitter schedule and runs after the solution runs because it uses the
same solution VM.

This command automates the entire process. It will:
1.  Build the necessary Vagrant base images (`.box` files) if they don't exist.
2.  Provision temporary VMs for the baseline parameter set and the `solution` experiment.
3.  Compile the C++ applications and run the mobility simulation inside each VM.
4.  Collect raw experiment artifacts, including `consumer_capture.pcap` and per-node `pcap_nodes/*.pcap`, into each run directory.
5.  Derive host-side CSV analysis inputs from those raw packet captures.
6.  Plot three per-handoff box plots for baseline tuning (G0--G4) and the same three for G0 versus OptoFlood: service disruption, forwarding-cost ratio, and NLSR control traffic.
7.  Compile the LaTeX source to produce `paper/OptoFlood.pdf`.

## Workflow Targets

- `make experiment-baseline`
  Runs the five baseline profiles, five runs each, and stores raw capture artifacts under `results/baseline/<profile>/rN/`.
- `make experiment-solution`
  Runs the five OptoFlood runs and stores raw capture artifacts under `results/solution/rN/`.
- `make plot-baseline`
  Regenerates the G0--G4 per-handoff box plots from existing captures.
- `make plot-main`
  Regenerates the G0-versus-OptoFlood box plots for the same three metrics.
- `make plot`
  Runs both plotting pipelines without re-running experiments.

## Baseline Parameter Sets

The baseline parameter groups and the r1..r5 repetition are declared in
`Makefile.baseline`. Each run is an explicit grouped target. Host-side
analysis uses the `results/baseline/%/...` and `results/solution/%/...` rules;
the `%` stem is `<profile>/rN` or `rN`.

To add a new baseline group:

- add its name to `BASELINE_PROFILE_LIST`;
- define `BASELINE_PROFILE_ENV_<name>` with `NLSR_HELLO_INTERVAL`,
  `NLSR_ADJ_LSA_BUILD_INTERVAL`, `NLSR_ROUTING_CALC_INTERVAL`,
  `NLSR_SYNC_INTEREST_LIFETIME_MS`, and `NLSR_TUNING_PROFILE`.

The run chain picks the new profile up in list order. `BASELINE_DEFAULT_DIR`
is the G0 directory compared with OptoFlood.

## Static Typing (optional)

`make mypy` runs static typing against the host-side plotting and validation
scripts. The Makefile invokes whichever `python3` is on `PATH`; install mypy
and the runtime dependencies into the environment of your choice before running
the target.

A convenience helper is provided for a venv-based setup:

```bash
sh experiment/tool/setup_venv.sh
. experiment/tool/.venv/bin/activate                   # Linux/macOS
# .\experiment\tool\.venv\Scripts\Activate.ps1         # Windows PowerShell
make mypy
```

Any other environment (conda, system pip, pipx, ...) works equally well as
long as `python3 -m mypy` is functional once activated.

## Cleaning Up

- To remove all experiment results, generated figures, and the paper PDF:
  ```bash
  make clean
  ```
- To perform a deep clean, which includes all of the above plus destroying all Vagrant VMs and removing the cached `.box` files:
  ```bash
  make deep-clean
  ```

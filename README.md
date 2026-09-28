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
6.  Decode the raw captures and plot service recovery time, content loss fraction, forwarding-cost ratio, and NLSR control rate for G0--G4 and for G0 versus OptoFlood.
7.  Compile the LaTeX source to produce `paper/OptoFlood.pdf`.

## Workflow Targets

- `make experiment-baseline`
  Runs the five baseline profiles, five runs each, and stores raw capture artifacts under `results/baseline/<profile>/rN/`.
- `make experiment-solution`
  Runs the five OptoFlood runs and stores raw capture artifacts under `results/solution/rN/`.
- `make plot-baseline`
  Regenerates the four G0--G4 mobility-event figures from existing raw captures.
- `make plot-main`
  Regenerates the four G0-versus-OptoFlood figures from the same event definitions.
- `make plot`
  Runs both plotting pipelines without re-running experiments.
- `make plot-exp1`
  Regenerates the Exp1 service-recovery, content-loss, and explicit-flood figures, plus the delivery timeline.
- `make mobility-analysis`
  Regenerates baseline, solution, and Exp1 mobility-event tables and figures from existing captures.
- `make test-mobility-analysis`
  Runs the mobility-event unit tests. This is separate from the protocol `test` target.

## Mobility-event analysis

Host-side analysis decodes each run's `pcap_nodes/*.pcap` with one Python decoder. Name equality uses `(component type, raw component bytes)`, not a rendered URI. Baseline is G0--G4, five runs, eight handoffs. The solution comparison is five OptoFlood runs of the same eight-handoff schedule. Exp1 keeps K=16 and zero jitter, and uses the same event parser.

The active metrics are service recovery time, content loss fraction, forwarding-cost ratio, and NLSR control rate. Exp1 plots service recovery time, content loss fraction, and explicit flood rate, and keeps the delivery timeline. Production figures:

- `results/baseline_service_recovery_time.pdf`
- `results/baseline_content_loss_fraction.pdf`
- `results/baseline_forwarding_cost_ratio.pdf`
- `results/baseline_nlsr_control_rate.pdf`
- `results/solution_service_recovery_time.pdf`
- `results/solution_content_loss_fraction.pdf`
- `results/solution_forwarding_cost_ratio.pdf`
- `results/solution_nlsr_control_rate.pdf`
- `results/extended/exp1/exp1_service_recovery_time.pdf`
- `results/extended/exp1/exp1_content_loss_fraction.pdf`
- `results/extended/exp1/exp1_explicit_flood_rate.pdf`
- `results/extended/exp1/exp1_delivery_timeline.pdf`

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

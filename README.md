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
            -> box/solution -> test -> solution/r1 -> ... -> solution/r5
            -> exp1 sync-delay d0 -> d1 -> d2 -> d4
            -> exp1 verification-timeout t10 -> t25 -> t50 -> t100 -> t250
```

Baseline tuning is 5 profiles × 5 runs. The OptoFlood comparison is 5 runs.
Each of those runs is one round trip of 8 hand-offs. Exp1 is the OptoFlood
parameter-sensitivity study: one SPRC Sync publication-delay sweep and one
EDRC verification-timeout sweep. Every full cell is one run of the same eight
handoffs and the same explicit interval list. It uses the solution VM and
runs after the solution runs.

This command automates the entire process. It will:
1.  Build the necessary Vagrant base images (`.box` files) if they don't exist.
2.  Provision temporary VMs for the baseline parameter set and the `solution` experiment.
3.  Compile the C++ applications and run the mobility simulation inside each VM.
4.  Collect raw experiment artifacts, including `consumer_capture.pcap` and per-node `pcap_nodes/*.pcap`, into each run directory.
5.  Derive host-side CSV analysis inputs from those raw packet captures.
6.  Decode the raw captures and plot service recovery time, content loss fraction, recovery flooding volume, and NLSR control rate for G0--G4 and for G0 versus OptoFlood, then measure routing convergence from the existing logs.
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
  Regenerates the two Exp1 parameter-sensitivity figures from existing captures.
- `make mobility-analysis`
  Regenerates baseline and solution mobility-event tables and figures, then the routing-convergence tables and figures, then the Exp1 sensitivity figures, from existing captures. Those steps run one after another, including under `make -j`.
- `make test-mobility-analysis`
  Runs the mobility-event unit tests. This is separate from the protocol `test` target.
- `make routing-analysis`
  Regenerates routing-convergence tables and the two routing figures from existing NLSR logs, NFD logs, handoff records, and mobility packet tables. It does not rerun experiments.
- `make plot-routing`
  Same host-side routing analysis as `make routing-analysis`.

## Mobility-event analysis

Host-side analysis decodes each run's `pcap_nodes/*.pcap` with one Python decoder. Name equality uses `(component type, raw component bytes)`, not a rendered URI. Baseline is G0--G4, five runs, eight handoffs. The solution comparison is five OptoFlood runs of the same eight-handoff schedule. Exp1 reuses those mobility-event and routing measurements on one explicit eight-handoff schedule.

The active main-experiment metrics are service recovery time, content loss fraction, recovery flooding volume, and NLSR control rate. Service recovery time is the time from a handoff until the producer receives the first fresh post-handoff content Interest. Recovery flooding volume is the aggregate bytes of actual OptoFlood flood-marked sender-egress transmissions per handoff. NLSR control rate measures control-plane traffic; recovery flooding volume measures recovery-induced flooding traffic. Exp1 is OptoFlood parameter sensitivity. The Sync publication-delay figure reports service-path LSA lead, service-path FIB convergence, and network-wide FIB convergence. The verification-timeout figure reports complete mobility-topology update latency and the same two FIB times. Production figures:

- `results/baseline_service_recovery_time.pdf`
- `results/baseline_content_loss_fraction.pdf`
- `results/baseline_nlsr_control_rate.pdf`
- `results/solution_service_recovery_time.pdf`
- `results/solution_content_loss_fraction.pdf`
- `results/solution_recovery_flooding_volume.pdf`
- `results/solution_nlsr_control_rate.pdf`

Exp1 figures:

- `results/extended/exp1/exp1_sync_delay_sensitivity.pdf`
- `results/extended/exp1/exp1_verification_timeout_sensitivity.pdf`

Legacy manuscript compatibility, not active evaluation metrics:

- `results/baseline_forwarding_cost_ratio.pdf`
- `results/solution_forwarding_cost_ratio.pdf`

## Routing-convergence analysis

`make routing-analysis` and `make plot-routing` read existing `handoffs.txt`, per-node `nlsr.log` and `nfd.log`, and `mobility_packets.csv`. They do not start a VM. A missing input fails with `required routing evidence missing`.

The measured routing quantities are:

- Complete Mobility-Topology Update Latency: producer-local Adj-LSA build after both sides of the move are definitive.
- Service-Path LSA Lead: per-handoff median of same-router, same Adj-LSA corridor Data versus NLSR Sync notice. Reported in `results/routing/service_path_lsa_lead.csv`. It has no standalone production figure.
- Service-Path FIB Convergence Time: latest NFD-confirmed correct `/LiveStream` installation on service-path routers whose next hop must change.
- Network-Wide FIB Convergence Time: the same NFD-confirmed endpoint over every affected NLSR router. `G1/r1/h8` is right-censored: the event is retained, the convergence cell is blank, and the capture boundary is not used as a convergence time.

Production figures:

- `results/routing_topology_update_latency.pdf`
- `results/routing_fib_convergence.pdf`

Tables and the audit are under `results/routing/`. `make clean` removes the `results/` tree, including `results/routing/` and the two routing PDFs.

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

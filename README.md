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

### Execution order

`make all` follows artifact dependencies. `make -j` may build the Baseline and Solution boxes at the same time after the Initial box, and otherwise keeps the experiment VMs in this order:

```
initial box -> baseline box and solution box
-> baseline smoke -> solution smoke
-> g0/r1 -> ... -> g4/r5
-> solution/r1 -> ... -> solution/r5
-> exp1 d0/r1..r5 -> d1/r1..r5 -> d2/r1..r5 -> d4/r1..r5 -> t10/r1..r5 -> t25/r1..r5 -> t50/r1..r5 -> t100/r1..r5 -> t250/r1..r5
-> exp2 formal runs -> exp3 formal runs
-> analysis and figures -> paper/OptoFlood.pdf
```

Each formal run creates a new VM from its prebuilt box and destroys that VM when the run finishes. `make paper` builds any missing evidence before compiling the PDF.

Baseline tuning is 5 profiles × 5 runs. The OptoFlood comparison is 5 runs.
Each of those runs is one round trip of 8 hand-offs. Exp1 is the OptoFlood
parameter-sensitivity study: one SPRC Sync publication-delay sweep and one
EDRC verification-timeout sweep. Every full cell is one run of the same eight
handoffs and the same explicit interval list. It uses the Solution box in its
own VM and runs after the solution runs.

This command automates the entire process. It will:
1.  Build the necessary Vagrant base images (`.box` files) if they don't exist.
2.  Provision temporary VMs for the baseline parameter set and the `solution` experiment.
3.  Compile the C++ applications and run the mobility simulation inside each VM.
4.  Collect raw experiment artifacts, including `consumer_capture.pcap` and per-node `pcap_nodes/*.pcap`, into each run directory.
5.  Derive host-side CSV analysis inputs from those raw packet captures.
6.  Decode the raw captures and plot service recovery time, content loss fraction, recovery flooding volume, and NLSR control rate for G0--G4 and for G0 versus OptoFlood, then measure routing convergence from the existing logs.
7.  Compile the LaTeX source to produce `paper/OptoFlood.pdf`.

## Workflow Targets

- `make box`
  Builds the Initial, Baseline, and Solution boxes.
- `make test`
  Builds any boxes required by the smoke tests, then runs the Baseline smoke and the Solution smoke.
- `make experiment`
  Runs all 110 formal runs: Baseline (25), Solution (5), Exp1 (45), Exp2 (20), and Exp3 (15).
- `make experiment-baseline`
  Runs the 25 Baseline formal runs.
- `make experiment-solution`
  Runs the five Solution formal runs.
- `make experiment-exp1`
  Runs the 45 Exp1 formal runs: five repetitions of each of the nine cells.
- `make experiment-exp2`
  Runs the 20 Exp2 formal runs.
- `make experiment-exp3`
  Runs the 15 Exp3 formal runs.
- `make analyse`
  Builds the analysis tables and summaries required by the paper. Missing or outdated captures, smoke stamps, or boxes are rebuilt through their artifact dependencies.
- `make plot`
  Builds every experiment-derived figure included in the paper. Missing or outdated analysis outputs are rebuilt first, and that chain can reach the formal experiments and boxes.
- `make paper`
  Builds `paper/OptoFlood.pdf` from the manuscript and its figures, rebuilding outdated prerequisites when required.
- `make all`
  Completes the full workflow: boxes, smoke tests, formal experiments, analyses, figures, and the paper.

Each target builds only the missing or outdated artifacts it requires. An up-to-date prerequisite is reused. Per-run checks and the Exp3 pilot remain available separately.

## Source layout

Active experiment code lives under `experiment/tool/`:

- `common/` runs the Baseline and Solution Mini-NDN experiments.
- `exp1/`, `exp2/`, and `exp3/` hold each experiment's driver, configuration, metrics, and figures.
- `analysis/` decodes captures and calculates the shared mobility and routing measurements. `resources/ndn.lua` is the packet dissector.
- `resources/` also holds the host analysis requirements and `setup_venv.sh`.

Host recipes run `python3 -m experiment.tool...` from the repository root. Guest recipes pass `PYTHONPATH` to the repository root on the `sudo -E env` line and use the same module names. The two integration smokes stay in `test/`.

The first Baseline run waits, as an order-only prerequisite, for both smoke stamps. Later Baseline runs wait only for the previous Baseline run. The first Solution run waits for the Solution smoke stamp and the last Baseline run. Formal Exp2 waits for the last Exp1 run, t250/r5, and formal Exp3 waits for the last Exp2 run. Those links order the VMs; a newer predecessor does not rebuild the later captures. A change that affects only the Solution smoke does not rebuild Baseline captures.

## Mobility-event analysis

Host-side analysis decodes each run's `pcap_nodes/*.pcap` with one Python decoder. Name equality uses `(component type, raw component bytes)`, not a rendered URI. Baseline is G0--G4, five runs, eight handoffs. The solution comparison is five OptoFlood runs of the same eight-handoff schedule. Exp1 reuses those mobility-event and routing measurements on five seeded schedules. Each schedule is shared by the nine cells of one repetition, and each figure reports the pooled handoff median and observed numeric range.

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

Recorded by the analysis command, and not used as paper figure inputs:

- `results/baseline_forwarding_cost_ratio.pdf`
- `results/solution_forwarding_cost_ratio.pdf`

## Routing-convergence analysis

`make analyse` and `make plot` read `handoffs.txt`, per-node `nlsr.log` and `nfd.log`, and `mobility_packets.csv` when building the routing tables and figures. A missing input is rebuilt from its upstream artifact, or the analysis stops with `required routing evidence missing` if that input is not one of the experiment outputs.

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

`make mypy` type-checks the active experiment modules. The Makefile invokes whichever `python3` is on `PATH`; install mypy and the runtime dependencies into that environment before running the target.

```bash
sh experiment/tool/resources/setup_venv.sh
. experiment/tool/.venv/bin/activate                   # Linux/macOS
# .\experiment\tool\.venv\Scripts\Activate.ps1         # Windows PowerShell
make mypy
```

Any other environment (conda, system pip, pipx, ...) works equally well as
long as `python3 -m mypy` is functional once activated.

## Cleaning Up

- To remove experiment results, smoke results, the current provider's smoke stamps, generated figures, and the paper PDF:
  ```bash
  make clean
  ```
- To destroy the repository VMs without removing boxes:
  ```bash
  make vm-clean
  ```
- To perform a deep clean, which includes `clean`, destroys the repository VMs, and removes this repository's generated box files and box registrations for the selected provider:
  ```bash
  make deep-clean
  ```
  The shared `bento/ubuntu-22.04` base image is not removed.

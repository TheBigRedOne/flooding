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

This command automates the entire process. It will:
1.  Build the necessary Vagrant base images (`.box` files) if they don't exist.
2.  Provision temporary VMs for the baseline parameter set and the `solution` experiment.
3.  Compile the C++ applications and run the mobility simulation inside each VM.
4.  Collect raw experiment artifacts, including `consumer_capture.pcap` and per-node `pcap_nodes/*.pcap`, into each result directory.
5.  Derive host-side CSV analysis inputs from those raw packet captures.
6.  Run host-side plotting pipelines for:
    - baseline parameter-set comparison (`disruption` and `overhead`)
    - baseline(default) and solution main results (`throughput`, `disruption`, `unmet-interest ratio`, and `overhead`)
7.  Copy the final figures into the `paper/` directory.
8.  Compile the LaTeX source to produce `paper/OptoFlood.pdf`.

## Workflow Targets

- `make experiment-baseline`
  Runs the configured baseline parameter groups and stores raw capture artifacts under `results/baseline/<profile>/`.
- `make experiment-solution`
  Runs the solution experiment and stores raw capture artifacts under `results/solution/`.
- `make plot-baseline`
  Regenerates only the baseline parameter-set comparison outputs from existing raw captures and derived CSV files.
- `make plot-main`
  Regenerates the baseline(default) and solution four-metric outputs from existing raw captures and derived CSV files.
- `make plot`
  Runs both plotting pipelines without re-running experiments.

## Baseline Parameter Sets

The baseline parameter groups are declared directly in `Makefile`.
Each group has an explicit experiment rule and uses the shared
`results/baseline/%/...` processing rules for host-side analysis.

To add a new baseline group:

- add its result directory to `BASELINE_PROFILE_DIRS`;
- add one grouped experiment target using `$(subst XXX,<group>,$(BASELINE_EXPERIMENT_OUTPUTS))`;
- set `NLSR_HELLO_INTERVAL`, `NLSR_ADJ_LSA_BUILD_INTERVAL`,
  `NLSR_ROUTING_CALC_INTERVAL`, and `NLSR_TUNING_PROFILE` in that target.

`BASELINE_DEFAULT_DIR` identifies the baseline group used for the main
baseline-versus-solution comparison.

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

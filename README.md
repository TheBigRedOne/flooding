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

## Baseline Profile Configuration

The baseline parameter groups are defined in `experiment/tool/baseline_profiles.mk`.
To add a new baseline profile, update that file with:

- the profile identifier in `BASELINE_PROFILE_IDS`
- the matching `BASELINE_PROFILE_DIR_<id>`
- the matching `BASELINE_PROFILE_HELLO_<id>`
- the matching `BASELINE_PROFILE_ADJ_<id>`
- the matching `BASELINE_PROFILE_ROUTE_<id>`

Set `BASELINE_DEFAULT_PROFILE` to the identifier of the default parameter group.
The default profile directory name intentionally retains the suffix `(default)`.

## Cleaning Up

- To remove all experiment results, generated figures, and the paper PDF:
  ```bash
  make clean
  ```
- To perform a deep clean, which includes all of the above plus destroying all Vagrant VMs and removing the cached `.box` files:
  ```bash
  make deep-clean
  ```

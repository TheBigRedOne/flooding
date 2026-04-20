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
4.  Collect the same raw CSV outputs for every experiment result directory.
5.  Run host-side plotting pipelines for:
    - baseline parameter-set comparison (`disruption` and `overhead`)
    - baseline(default) and solution main results (`throughput`, `disruption`, `unmet-interest ratio`, and `overhead`)
6.  Copy the final figures into the `paper/` directory.
7.  Compile the LaTeX source to produce `paper/OptoFlood.pdf`.

## Workflow Targets

- `make experiment-baseline`
  Runs the configured baseline parameter groups and stores them under `results/baseline/<profile>/`.
- `make experiment-solution`
  Runs the solution experiment and stores it under `results/solution/`.
- `make plot-baseline`
  Regenerates only the baseline parameter-set comparison outputs from existing CSV files.
- `make plot-main`
  Regenerates the baseline(default) and solution four-metric outputs from existing CSV files.
- `make plot`
  Runs both plotting pipelines without re-running experiments.

## Baseline Profile Configuration

The baseline parameter groups are defined in `experiment/tool/baseline_profiles.json`.
To add a new baseline profile, append one entry to that file with:

- `id`
- `directory_name`
- `hello_interval`
- `adj_lsa_build_interval`
- `routing_calc_interval`
- `is_default`

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

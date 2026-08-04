# Experiments

Each subdirectory here is one experiment, named by date (optionally with a
short slug):

    experiments/
    └── 2026-08-04-motif-scan/
        ├── runall          # every command, in order; rerun to reproduce
        └── results/        # this experiment's outputs

Rules:

- One `runall` per experiment. Rerunning `./runall` reproduces the whole
  experiment.
- Outputs go in `results/` under the experiment directory, not at the project
  root.
- Reusable code lives at the project top level (`scripts/`, `notebooks/`),
  not copied into each experiment. Experiment directories hold only that
  experiment's `runall` and results.
- Large outputs (model weights, big tables) go to the project-level
  `artifacts/` directory, not here — see `../artifacts/README.md`.

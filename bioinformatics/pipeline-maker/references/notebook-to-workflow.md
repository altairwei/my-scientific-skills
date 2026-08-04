# Notebook to workflow

Loaded for Mode A when the input is a Jupyter notebook. Ports `snkmaker`'s notebook-mode methodology (study `external/snkmaker/README.md` "Notebook support"; do not copy — write original guidance).

## 1. Parse cells

Read the notebook (`*.ipynb`, JSON). For each cell, identify three sets of variables:

- **Read** — variables the cell (might) read that were produced by earlier cells.
- **Write** — variables the cell (might) write that later cells will use.
- **Wildcards** — variables the cell (might) read that will be provided as Snakemake wildcards (resolved from filenames at run time).

Snakemake provides a first automatic resolution; the user can refine it.

## 2. Build the dependency DAG

Match each **Read** of a cell to the **closest prior Write** of that variable. This gives the cell-to-cell dependency graph. (Cell 1 writes `var1`; Cell 2 reads `var1` → Cell 2 depends on Cell 1. If Cell 1 modifies `var1` and Cell 3 also reads it, Cell 3 depends on the modified version from Cell 1.)

## 3. Split, merge, or remove cells

The user can:

- **Split** a cell into two rules (e.g., a cell that does two distinct transformations).
- **Merge** cells into one rule.
- **Remove** cells (exploratory/plotting only).

Refine the Read/Write/Wildcards sets manually — add a variable by selecting it in the code and marking it Read/Write/Wildcard; remove by unmarking.

## 4. Rule-vs-Script cascading constraint

Decide each cell as **Rule** or **Script**:

- A **Rule** can read output files from other rules and import scripts → can depend on both Rules and Scripts. Any cell can become a Rule.
- A **Script** can import other scripts but **cannot** directly read a file output by another rule → can depend only on Scripts.

Cascading consequence: setting a cell as a Rule may force dependent Scripts to become Rules too (so they can read the rule's output). **All cells must be Rule or Script before generation**; undecided cells are flagged.

## 5. Generate prefix + suffix code

For each cell set as a Rule, generate:

- **Prefix code** — import statements, command-line-argument reading, and reading of input files (from the `snakemake.input` object).
- **Suffix code** — writing of output files (to `snakemake.output`).
- The cell's original code is the body, between prefix and suffix.

For Script cells, only prefix code (no suffix — they don't write rule outputs directly).

## 6. Auto-propagate edits

If the user edits the generated code (e.g., changes an output's format or filename), the change propagates to dependent cells: update the rule's output filename, and update the rules + prefix code of cells that read that output. This keeps the DAG consistent after a manual edit.

## 7. Export

Write `Snakefile` + `scripts/*.py` (one per cell that became a Script or a Rule body) to a directory the user chooses. The Snakefile `include:`s or references the scripts via `script:`.

## 8. Validate

Run `scripts/validate-workflow.py`; read the real stderr, fix, retry until `snakemake -n` passes. Watch for: a cell whose Read variable has no producer (`MissingInputException` — mark it a Wildcard or add a producer); a Script cell that needs to read a rule output (cascading constraint — promote it to a Rule).

## Then

Hand off to `bioinfo-project-organization` for project-level layout (`experiments/`, `runall`, `lab-notebook.md`) if the user wants the workflow placed into a tracked project.

# Bash to workflow

Loaded for Mode A when the input is bash commands. Ports `snkmaker`'s bash-mode methodology (study `external/snkmaker/README.md` "Bash command support"; do not copy — write original guidance).

## 1. Collect commands

Accept pasted commands, a shell-history file, or a history export. Ask the user for context the commands don't carry: which files already exist, which token is the sample id, what the reference path is. Don't generate rules from commands whose data context is unclear.

## 2. Classify important vs one-timer

- **Important** — the command transforms files (reads input, writes output) and contributes to the workflow's deliverables.
- **One-timer** — `ls`, `cd`, `head`, quick lookups; skip these (they don't become rules).

Ask the user on ambiguity; the classification is editable. When in doubt, default to one-timer and let the user promote.

## 3. Extract I/O and infer rule names

For each important command, identify:

- **Input files** — paths the command reads (explicit args, stdin, `$(...)` expansions).
- **Output files** — paths the command writes: `>`, `>>`, `-o`, `--out`, `-O`, `2>` (stderr-to-log), `tee`. Include side files (`.bai`, `.tbi`, logs) if the tool writes them.
- **Rule name** — from the tool (`bwa_mem`), the output stem (`mark_duplicates`), or ask the user. Editable.

Present the extracted I/O table to the user before generating rules — wrong I/O mapping is the most common failure.

## 4. Detect composite opportunities

Multiple commands that together produce one output → merge into a **composite rule**. Example: `samtools sort` then `samtools index` of the same bam → one rule with a multi-line `shell:`. Snkmaker supports drag-and-drop merging; conversationally, propose the merge and let the user confirm.

## 5. Infer wildcard generalization

If the same command is run over many files differing only in a sample/dataset token, generalize to a **wildcard rule**: `{sample}.fastq → {sample}.bam` instead of one rule per sample. **Present the inference and let the user confirm before generalizing across samples** — over-generalization (e.g., treating a one-off batch as a wildcard) is a judgment call. Constraint the wildcard (`wildcard_constraints: sample="\d+"`) if the sample ids are patterned.

## 6. Build the dependency DAG

Match each command's input files to other commands' outputs; order the rules. Detect cycles and missing producers (a file read but not produced by any command → `MissingInputException`; ask the user where it comes from).

## 7. Decide rule vs script

- A command that reads a file output by another rule and can be expressed as a shell one-liner → **rule** with `shell:`.
- A command with complex logic, many steps, or control flow → a **`script:`** (`scripts/<name>.py` or `.sh`) called by a thin rule (`script: "scripts/<name>.py"`). Pure analysis logic goes in `scripts/`; rule formatting in `common.smk`.

(For notebooks, there's an additional cascading Rule-vs-Script constraint — see `notebook-to-workflow.md`.)

## 8. Generate rules

From `assets/rule.tmpl` / `assets/workflow-rules.smk.tmpl`, fill `<NAME>`/`<INPUT>`/`<OUTPUT>`/`<COMMAND>`/`<WILDCARD>`. Write `Snakefile` (`assets/Snakefile.tmpl`), `config.yaml` (`assets/config.yaml.tmpl`), and `common.smk` (`assets/common.smk.tmpl`) when shared helpers are needed. Keep the `log:` directive on every rule (it survives failures). Use `params:` for tool arguments that vary, not hardcoded strings.

## 9. GNU Make alternative

`snkmaker` can also emit GNU Make rules; this skill is **Snakemake-only**. If the user explicitly asks for Make, point them to `snkmaker` directly rather than adapting.

## Then

Validate (see SKILL.md "Validation loop"): run `scripts/validate-workflow.py`, read the real stderr, fix, retry until `snakemake -n` passes.

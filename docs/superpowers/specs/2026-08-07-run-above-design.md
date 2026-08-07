# Run Above / Run From selectors — Design Spec

**Date:** 2026-08-07
**Status:** Design — pending implementation plan
**Skill name:** `interactive-repl` (extension to the existing skill)
**Category:** `data-science/`

---

## 1. Problem & goal

`run_chunk`'s selector supports exact label (`extract`), index (`3`), range (`3-7`), and
open range (`3-`), but not the GUI notebook buttons: **Run All Above** (run everything up
to the current chunk) and **Run All Below** (run from the current chunk to the end). The
agent today has to know the index and use `1-N` / `N-`.

**Goal:** extend the selector grammar so `^label` runs chunks 1…label (Run Above) and
`label^` runs chunks label…end (Run From). The `^` is a literal prefix/suffix marker
(`^`-anchored at the start = anchored to the notebook start; `^`-anchored at the end =
anchored to the notebook end).

## 2. Selector grammar (single core change)

`_chunk_parser.resolve_selector` is the shared resolution used by both servers' `run_chunk`
**and** the CLI — so extending it gives the new selectors everywhere with no server changes.

| Selector | Meaning |
|---|---|
| `^label` | chunks **1…label, inclusive** — Run Above (Jupyter "Run All Above") |
| `label^` | chunks **label…end, inclusive** — Run From ("run all below") |
| `N-M` / `N-` / `N` / `label` | existing range / open-range / index / exact label — unchanged |

**Resolution order:** `N-M` → `N` → `^label` (`^\^(.+)$`) → `label^` (`^(.+)\^$`) → `label`.

**Edge cases:**
- `^label` / `label^` with an unknown label → the same helpful error as today:
  `"chunk '<label>' not found. Available: … (indices 1-N)"`.
- Inclusive in both directions: `^label` includes the label chunk; `label^` includes it too.
- The `^` in selectors is a literal character (selectors are exact-match strings, not
  regexes). Labels containing `^` are pathological; the caret forms win, consistent with
  the existing numeric-precedence rule.
- Caret forms resolve **by label only**, not by index — index-based Run Above/From is
  already covered by `1-N` / `N-`. (`^3` → "chunk '3' not found".)

## 3. `run_chunk` (both servers) — no change

`run_chunk` already calls `resolve_selector`; the cwd-set, `eval=FALSE` skip, language
routing, and stop-on-first-error all operate on the returned list unchanged. The only
user-visible change is that `selector` now accepts the two caret forms.

## 4. CLI (`notebook_chunks.py`) — one-line `--chunk` fix

`--chunks ^label` already works (prints 1…label's code). But `--chunk ^label` would print
only `sel[0]` (chunk 1). Fix: change `--chunk`'s handler from `print(sel[0].code)` to
`print("\n".join(c.code for c in sel))` — single-chunk selectors are unchanged; range-like
selectors print the full concatenated code. `--chunk`/`--chunks` both become "print the
selected chunk(s)' code".

## 5. Testing (TDD)

- `resolve_selector` unit tests: `^label` → [1…label]; `label^` → [label…end]; inclusive
  boundary both directions; unknown-label errors both directions; existing selectors
  unchanged (regression).
- Server tests (R + Python, `run_chunk` with `^label` / `label^` on the fixtures):
  `^<chunkX>` → `ran == [1..X]` (with `eval=FALSE` / language skips still applied);
  `<chunkX>^` → `ran == [X..end]`.
- CLI test: `--chunks ^label` prints 1…label's code.

## 6. Documentation

- `references/notebook-iteration.md`: add `^label` / `label^` rows to the selector table
  in "Run chunks".
- `SKILL.md`: update the `run_chunk` bullet's selector list to
  `label / index / N-M / N- / ^label / label^`.

## 7. Scope

**In v1:** the two caret forms in `resolve_selector`, the CLI `--chunk` fix, tests, docs.
**Deferred (YAGNI):** caret-by-index forms (`^3`, `3^` — `1-N`/`N-` already cover them);
a `run_until`/`run_from` param (the selector syntax subsumes it); `^N-M` composite ranges.

---
name: figure-style
description: Use when drawing or fixing any plot — publication figure,
  exploratory chart, or a panel of a larger figure. Correctness + legibility
  checklist (data fidelity, label economy, colour/CVD safety, typography,
  chart choice by data shape) with matplotlib helpers and a render-then-verify
  loop. Triggers on "draw a plot", "make a figure", "publication-ready",
  "fix this figure", or any matplotlib/seaborn task.
license: MIT
metadata:
  author: Altair Wei
  version: "0.1"
---

# Figure Style — make one plot correct and legible

A checklist, not a house look: frame, font, and palette stay your choice. The
rules catch figures that are *wrong* (an excluded row in a summary statistic,
a claim-title some row contradicts, red/green binary contrasts) and figures
that are *unreadable* (over-labelled, cramped, legend-bound). Apply them to
every plot, paper-bound or exploratory.

This is the **inner tier** of the figure family: one plot, done right. For a
multi-panel figure use `figure-composer`; for the whole paper's figure arc
use `paper-narrative`.

## Setup

`figure_style.py` is an **import-only module** (no CLI). Your plotting script
imports it; `uv run --with` supplies matplotlib:

```python
import sys
sys.path.insert(0, "<plugin>/scientific-writing/figure-style/scripts")
import figure_style as fs
```

```bash
uv run --with matplotlib --with numpy python plot.py
```

Add `--with scipy` only if you use `bar_with_points(errorbar="ci95")` (lazy
import). No `uv`? `curl -LsSf https://astral.sh/uv/install.sh | sh`, or run
`bash scripts/setup.sh` once to install uv and warm the wheel cache.

## The loop

1. **Read the rules** — `references/rules.md`, at least §1–§3 and §9
   (correctness). A `figure-composer` panel prompt will cite §-numbers; they
   resolve in that file.
2. **`fs.apply_figure_style()` before plotting** — sets the role-mapped
   font-size ladder (§5.2), outward ticks, frameless legends, 300-dpi save,
   Type-42 fonts. Frame/font/sizes are parameters, not a look.
3. **Plot with the helpers** where they fit (table below).
4. **§9 render-then-verify** — after `fig.savefig(...)`:
   - **9.1 geometric**: run the bbox-overlap snippet (rules.md §9.1) inside
     your script; fix and re-save until no visible text boxes overlap or
     cross a spine.
   - **9.2 perceptual**: dump `fs.panel_crops(fig)` to JSON, crop the saved
     PNG per box (the `pdf-explore` skill's `pdf_explore.py crop PNG --box
     x0,y0,x1,y1` or three lines of PIL), and **Read every crop** — contrast,
     smallest mark, leader crossings, colour confusion, legend binding. A
     defect that passes 9.1 is still a defect.

## Rule map (details in references/rules.md)

| § | covers | binding? |
|---|---|---|
| §1 | data fidelity — excluded rows, self-consistency, true claim-titles, one number per claim | correctness |
| §2 | label economy — identity floor (non-removable) vs annotation ceiling; titles are takeaways | correctness |
| §3 | axes/scales/small multiples — padding, breaks, log ticks, fill-the-box ≥75% | correctness |
| §4 | colour — threading, focal-vs-comparator weight, semantic-zero diverging, CVD safety | guidance* |
| §5 | typography — sentence titles, ≤3 role-mapped sizes, panel letters | guidance* |
| §6 | chart family by data shape — strip/bar/violin/lollipop/ridgeline/embedding conventions | guidance* |
| §7 | layout & narrative — one figure one message, legends in whitespace, figure arc | guidance* |
| §8 | anti-patterns — the nine correctness failures to grep your figure for | correctness |
| §9 | render-then-verify — bbox check + crop-and-look | correctness |

*guidance sections bind where they state a perceptual/factual invariant
(§4.4, §4.5, §6.9).

## Helper quick table

| helper | encodes |
|---|---|
| `apply_figure_style(frame, font, sizes, grid)` | §5.2 size ladder + mechanics rcParams |
| `set_frame(ax, style)` | spine visibility on an existing axes |
| `panel_letter(ax, 'a', case=...)` | §5.7 bold letter, venue case |
| `focal_palette(labels, focal, color, other=)` | §4.2 dominant focal vs muted comparators |
| `bar_with_points(ax, x, ymat, ...)` | §6.1 mean bar + raw points (or ci95 interval) |
| `strip_with_median(ax, groups, values)` | §6.1 jittered strip + median tick |
| `goodness_arrow(ax, ...)` | §3.6 upright "higher = better" cue |
| `end_of_line_labels(ax, xs, ys, labels)` | §6.3/§7.3 direct labels instead of legend |
| `two_tier_label(name, meta)` | §5 two-line label string |
| `panel_crops(fig)` | §9.2 per-panel crop boxes of the saved PNG |

## When NOT to use

- **Multi-panel figure from a claim + data** → `figure-composer` (it loads
  these rules per panel; you don't tile by hand).
- **Deciding which figures a paper needs / what Fig 1 should be** →
  `paper-narrative`.
- **Reading values off someone else's figure in a PDF** → `pdf-explore`
  (`render` + `crop`).
- **Interactive Plotly figures (hover/zoom, `px`) → `plotly-interactive-figures`**
  (JSON-spec verification; this skill's render-then-verify assumes you can `Read` PNGs).

## Notes

- **Random jitter** in `bar_with_points`/`strip_with_median` uses
  `np.random.rand` — seed inside your script if you need reproducible PNGs.
- **Panel-letter detection** in `panel_crops` keys on bold single-character
  Text placed by `panel_letter`; unlettered figures fall back to one crop per
  axes.
- **The rules file is the shared vocabulary of the family** — §-numbers are
  stable; `figure-composer`'s prompts cite them. If you edit rules.md, keep
  the numbering.

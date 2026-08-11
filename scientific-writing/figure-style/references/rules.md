# Publication-grade figure rules

The full checklist behind the `figure-style` skill — read this when drawing or
fixing any plot, and read the sections a `figure-composer` panel prompt cites
(§-numbers are stable across the family; a prompt citing "§2.1" means this
file). The helpers in `scripts/figure_style.py` encode the mechanical parts.

## §0 Scope

§1–§3, §8, §9 are **correctness** — no aesthetic judgement, binding on every
plot in every context. §4–§7 are **guidance** — defaults that yield a clean
figure; a deliberate, reasoned alternative may override them, except where a
rule states a perceptual or factual invariant (§4.4 semantic-zero centring,
§4.5 CVD safety, §6.9 leader anchoring still bind). This is the inner tier —
one plot, done right. For a multi-panel figure use `figure-composer`; for the
whole paper's figure arc use `paper-narrative`.

---

## §1 Data fidelity & self-consistency

**1.1 Excluded rows.** A row flagged or excluded in the source data is dropped
entirely, or drawn as a visually distinct open/hatched mark and named in the
key. It must **never** contribute to a summary statistic plotted next to
included rows.

**1.2 Comparable conditions only.** Arms measured under non-comparable
conditions (different n, epoch budget, initialisation, protocol) must not
appear as visual peers. Break them apart with a facet or flag the label, and
state the difference once in the caption.

**1.3 Self-consistency.** Every key, threshold, and title in the figure must
hold for every plotted row. Before saving, trace each categorical outcome
label back to the rule that defines it; a row contradicting its own label or
the title means the figure is wrong — not the data.

**1.4 Claim-titles must be true.** Test a sentence-title (§5.1) against every
category on the axis before rendering. One contradiction → qualify it
("on 3 of 4 pairs") or downgrade to a plain description.

**1.5 State n and what was held fixed.** Any panel drawing a summary mark
states `n` and the unit of replication; any small-multiple that holds a
variable fixed states the fixed value — in the panel, or in the caption when
the §2 budget is tight.

**1.6 Reference structure is reference.** A tree, ordering, or topology drawn
as *context* (scale bar, category strip) comes from an established reference,
not from the plotted data. Infer structure only when the structure *is* the
result.

**1.7 One number per claim.** A quantitative claim (runtime, accuracy, count)
has exactly one canonical value across all panels, captions, and the abstract.
Define what it measures once; use that value everywhere.

---

## §2 Label economy — floor and ceiling

The figure carries the pattern; the **caption** carries the context. Design
for a general scientific reader, not for the author.

**2.1 Floor (non-removable).** Every distinct mark, series, glyph, and
comparator must be identifiable from the figure alone. The caption explains
*why it matters*, never *what it is*. Test: delete a label — if the reader
now asks "what is that?", the label is floor; if they ask "why is that
there?", it was movable. Comparator labels name the thing
("prior method", "no joint training") — never a bare role word ("baseline",
"previous"). Any term a general scientist cannot parse gets a one-word gloss.

**2.2 Ceiling.** Per panel: title + axis labels + tick labels + series
identity (labelled once per row of small multiples) + at most 2–3 result
annotations. Count the strings: more than ~6 beyond axes/ticks is over. The
ceiling covers *narrative* annotations (callouts, value labels, brackets) —
identity labels are floor and don't count.

**2.3 Move to the caption:** n=, what's-held-fixed, abbreviation expansions,
non-comparable footnotes, exclusion rationale, methodological caveats.

**2.4 Titles are takeaways.** A reader who sees only the title knows what the
panel shows. "Robust to gene dropout" passes; "Fewer genes" fails — read it
aloud cold, and if the listener asks "fewer genes *what*?", rewrite. For a
row of small multiples varying one thing, replace per-panel titles with one
row-header.

**2.5 Value-on-mark only for the headline number** — the single number a
reader would quote. Everything else is read off the axis.

**2.6 When in doubt, delete the label and re-read.** If the message survives,
the label stays deleted.

---

## §3 Axes, scales, small multiples

**3.1 Axis padding.** Axis limits clear the data by at least one marker radius
on every side; marks and text never touch a spine. `ax.margins(0.04)` after
plotting, or extend the limit past any annotation.

**3.2 Axis breaks over wasted range.** When data fill under ~40% of an axis,
break the axis or start it at the data floor with a clear non-zero tick. Never
draw a reference line, threshold, or annotation inside a broken-axis gap — the
gap has no coordinate system.

**3.3 Log axes get human-readable ticks** — `10²`, `10³` or `1k / 10k / 100k`,
never raw exponents. **Never** draw filled bars on a log-scaled value axis
(bar length encodes ratio to an arbitrary floor); use points plus a median
tick instead.

**3.4 Shared axes across small multiples.** A row or column of small multiples
shows tick labels once (leftmost / bottommost panel); interior panels keep
ticks but drop labels. Panels sharing a y-axis and differing only in
x-variable render as abutting subplots (`wspace≤0.06`) under one row-header
title.

**3.5 Fill the box.** A panel's data envelope occupies ≥75% of its allotted
rectangle. If the natural aspect leaves dead bands, reshape the grid (rowspan,
stacked complementary panels) — don't pad the panel with empty space.

**3.6 Direction of goodness.** When higher- or lower-is-better is not obvious
from the axis label, put a small upright cue ("higher = better") in the
margin — once per row of panels, never per panel, never only in the caption.
A directional glyph embedded in rotated text rotates with it; set the cue
upright.

**3.7 Physical width.** A single-row figure at 300 dpi fits the venue's
double-column width. Adding a schematic or labels must not squeeze data
panels narrower than they were.

---

## §4 Colour

**4.1 Threading.** Once a colour is bound to an entity (method, feature,
condition), reuse that exact colour for every mark of that entity across the
figure — line, fill, marker, text, heatmap row. Colour *is* the
cross-reference; a reader should never consult a legend twice.

**4.2 Limit hues.** As few distinct hues as the data require. When the figure
pits a focal series against comparators, make the focal series visually
dominant (saturated, heavier) and render comparators with lower visual weight
(desaturated, lighter, thinner). The focal hue must not collide with any hue
of a categorical palette in the same figure. The focal series must stay
identifiable even when its mark is zero-width or coincident with others —
outline, marker, or a light tinted band.

**4.3 Hierarchical categories.** When categories nest, the outer level picks
the hue family and the inner level samples shades within it.

**4.4 Continuous and diverging.** Perceptually uniform sequential map for
generic continuous values; single-hue ramp for ordinal rank or size;
diverging map for signed quantities — **always** centred at the semantically
meaningful zero (0, 1.0, or median), never at the data midpoint.

**4.5 CVD safety.** Never rely on red/green for a binary or opposing
distinction; any binary pair must survive deuteranopia simulation. Reserve
one alarm hue for error/anomaly/perturbation marks and never reuse it as a
data-series colour.

**4.6 Two palettes, two legends.** When a figure uses two categorical colour
systems, each legend sits adjacent to the first panel where its palette
applies.

---

## §5 Typography

**5.1 Sentence titles.** A panel title states the comparison in plain
language, regular weight, left-aligned. Metric names belong on the axis, not
in the title.

**5.2 Role-mapped size ladder.** At most **three** font sizes per figure,
mapped to *role*, not to available space: titles/axis-labels/series-identity
at base size; legend/annotation one step down; tick labels one further step.
Panel letters are the sole exception (bold, one step up). If a label doesn't
fit at its role's size, fix the layout or shorten the text — don't invent an
intermediate size. `apply_figure_style(sizes=(8,7,6))` sets the ladder.

**5.3 Nomenclature.** Species, gene, and variable names that convention
italicises are italicised. Abbreviated codes inherit the rule; expand once at
first appearance.

**5.4 Magnitude suffixes.** Large counts use `k / M / B` (`4.2B`, `120 kb`),
not comma-grouped numerals.

**5.5 Numeric annotations.** On-mark numbers use at most 2 significant
figures — unless 2-sf rounding would print two distinct rows identically;
then show the digit that separates them. Text on a filled mark needs ≥4.5:1
contrast; otherwise place it outside the mark.

**5.6 No internal codes.** Axis labels use plain-language names; codebase
abbreviations appear only parenthesised after the readable name, or in the
caption. Comparator series are labelled by what they *are*, not a role word.

**5.7 Panel letters.** Bold, top-left, outside the axes box. Case follows the
venue's convention; `panel_letter(ax, 'a', case=...)` handles either.

---

## §6 Chart-family guidance (by data shape)

**6.1 Categorical × numeric.** Show the distribution, not only the summary.
Choice follows n: jittered strip with median tick at small n; box or violin
at large n; bar + overlaid raw points or bar + interval when the mean is the
message. The `errorbar='ci95'` interval is the t-distribution 95% CI of the
mean (half-width `t_{0.975,n−1}·s/√n`) — valid at small n, unlike the
z-approximation. Error bars and raw-point overlays are alternatives; both at
once is usually redundant. A category absent from a group is marked
(`n.d.`, `—`, hatched ghost) at its slot — an empty slot reads as zero. A
zero-valued bar gets a visible stub or dot at the baseline.

**6.2 Single-observation categories.** A filled dot with a thin neutral stem
to the semantic zero (lollipop); value labels beside the dot.

**6.3 Continuous series.** Mean-per-x as a line with markers; individual runs
as thin translucent lines or points behind. Label each series with direct
text at the right end of its line in preference to a legend box. Summary
glyphs (per-bin mean/median) use a shape unmistakable for a raw observation,
identical across series, drawn below the raw points in z-order.

**6.4 Distributions on shared support.** Heavily overlapping distributions
stack as small panels with a shared x-axis, or a ridgeline. Overlay only when
the separation is visually clear.

**6.5 Matrices.** A heatmap small enough to read (< ~200 cells) prints the
value in every cell. State the threshold once, in the colourbar label.

**6.6 Embeddings.** Dimensionality-reduction scatters (UMAP, t-SNE, PCA) drop
ticks and tick labels; a small corner arrow pair names the axes. Clusters are
labelled by thin leader lines to text in surrounding whitespace.

**6.7 Paired prediction vs. observation.** Stack the two as adjacent tracks
with identical x and colour; let the alignment carry the comparison. Target
regions are translucent spans registered in the legend.

**6.8 Insets.** Connect a detail inset to its source region visibly — a
bounding box with connector lines, or a translucent wedge.

**6.9 Label the extremes.** On a scatter of named observations, direct-label
at least the maximum, minimum, and any flagged point with a thin leader line.
After rendering, verify every leader endpoint lands within one marker radius
of the row it names.

---

## §7 Layout & narrative

**7.1 Show what is measured before the result.** A reader grasps what's being
compared before seeing the comparison — via a plain-language title, a
labelled schematic, or panel ordering. A schematic uses the same words and
glyphs as the data panels' labels.

**7.2 One figure, one message.** A multi-panel figure has a single sentence
it is trying to make true. Every panel states it, supports it, or bounds it;
a panel doing none of these belongs in supplement.

**7.3 Legends live in whitespace.** Frameless, inside the figure's natural
whitespace, or replaced by direct labelling. Entries are swatch-first,
left-aligned, and resolve every visually distinct glyph on the panel.

**7.4 Row-band headers for nested faceting.** Grouped small multiples get one
spanning header per group, not repeated per-panel titles.

**7.5 The figure arc.** For a paper: Figure 1 renders the paper's one-sentence
pitch as data — scope, not architecture. Subsequent figures cover mechanism,
evidence, robustness, application. A panel is judged against the paper's
pitch, not only its own figure's claim; content moves between figures when
the story needs it. The `paper-narrative` skill runs that review.

**7.6 Don't re-decorate a passing panel.** Between revision rounds, a panel
that already passes is not made more complex to fix nothing. Adding marks or
labels to a clean panel is a regression.

---

## §8 Anti-patterns

Correctness failures, not style preferences:

- Red and green as opposing categories.
- Filled bars on a log-scaled value axis.
- Colourbar ticks evenly spaced but missing the semantic centre.
- A diverging colormap centred on the data midpoint instead of the semantic
  zero.
- An axis title that restates the tick labels.
- Direction-of-goodness explained only in the caption.
- A "reference" line drawn at a value that is itself a plotted point.
- An excluded row entering a plotted summary statistic.
- A leader line whose nearest mark is not the row it labels.

---

## §9 Render-then-verify

After `fig.savefig(...)`, before calling the figure done:

**9.1 Geometric (bbox) check.** Run inside the plotting script:

```python
r = fig.canvas.get_renderer()
texts = [(t, t.get_window_extent(r)) for t in fig.findobj(mpl.text.Text)
         if t.get_text().strip() and t.get_visible()]
spines = [(s, s.get_window_extent(r)) for ax in fig.axes
          for s in ax.spines.values() if s.get_visible()]
ticklabels = {ax: set(ax.get_xticklabels(which='both') + ax.get_yticklabels(which='both'))
              for ax in fig.axes}
overlaps  = [(a, b) for i, (a, ba) in enumerate(texts) for b, bb in texts[i+1:] if ba.overlaps(bb)]
overlaps += [(t, s) for t, bt in texts for s, bs in spines
             if bt.overlaps(bs) and t not in ticklabels[s.axes]]
# assert: overlaps == [] and every text box lies within fig.bbox
```

Overlap is judged between *visible* boxes; a tick label on its own spine is
not a finding. Fix (move, shorten, stagger) and re-save until clean.

**9.2 Perceptual check.** §9.1 is geometric — it cannot catch a low-contrast
label, a leader crossing three others, or two series colours confusable with
each other. Crop the saved PNG per panel and *look*:

```python
fig.savefig("figure.png")
import json
json.dump(panel_crops(fig), open("crops.json", "w"), indent=1)
```

Then crop `figure.png` to each box in `crops.json` — the `pdf-explore`
skill's `uv run pdf_explore.py crop figure.png --box x0,y0,x1,y1 --out
crop_a.png` works, as does three lines of PIL — and `Read` every crop. For
each: Is every glyph and mark legible against its background? Does the
smallest plotted element have a stroke or stub? Do any leaders cross? Could
any series colour be mistaken for another? Does the legend sit beside what it
keys? A perceptual defect that passes §9.1 is still a defect.

---

*When in doubt: fewer hues, more direct labels, raw data over summary stats,
and state what is being measured before showing the result.*

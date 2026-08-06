# Plot iteration — save and look

The iterate-on-plots loop has one firm rule and one hard-won caveat.

## Save and look

`run_code` auto-saves figures — matplotlib figures → `savefig()`, ggplot objects →
`ggsave()` — and returns the PNG paths in `plots`. **`Read` the PNG to actually see
it.** Don't reason about the figure from the data layer alone.

## Looking is necessary, not sufficient

A real session `Read` a PNG and *still* mis-reasoned. The plot was a histogram with
`scale_y_log10()`. The agent attributed empty panels to "censored markers /
white-transparent bars" — the true cause was that `count=1` bars on a log10 scale
can't render 1→0 (`log(0)` is undefined), so they vanish or render as a thin sliver.

The agent's data-layer reasoning ("every day has ≥1 case, so no zero-count problem")
was precisely the trap. **Understand the rendering semantics, not just the data.** For
log/tricky-scale plots especially, reason about how the geometry renders.

## When the user says "the plot looks wrong"

Believe them first — then look yourself. The user saw the artifact; the agent didn't.
`ggsave`/`savefig` to disk + `Read` the PNG to verify with your own eyes. Don't assert
the figure is correct from the data layer.

## Don't auto-"fix" on warnings

`log(0)=-Inf` / `Removed N rows containing missing values` are normal ggplot/matplotlib
semantics on log-scale plots — the warning is ggplot doing its job, not a defect. **Look
at the render before deciding.** Only act if the rendered figure is actually wrong.

## `Read` can return "Unsupported Image"

In some environments, `Read` on a PNG returns "Unsupported Image" (can't render). Fall
back to verifying key distribution stats numerically — e.g. `print(df[col].describe())`
or `table(cut(df$x, breaks=...))` — to confirm the data matches what the plot should show.
Note: when `Read` fails, the agent's data-layer reasoning becomes *more* error-prone
(real sessions showed the user had to push twice) — slow down and verify numerically.

## The final choice in the real session

The user ultimately switched `scale_y_log10()` → `scale_y_sqrt()` (`sqrt(0)=0`, no
down-fill artifact) and added manual `breaks`. Prefer `scale_y_sqrt()` for
count-distribution histograms where small counts matter.

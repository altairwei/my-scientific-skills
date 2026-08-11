"""Tests for figure_style.py (import-only matplotlib helper module).

Run via uv (Agg backend, no display needed):

  uv run --with matplotlib --with numpy --with scipy --with pytest \
      pytest scientific-writing/figure-style/tests/ -v
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import figure_style as fs  # noqa: E402


@pytest.fixture(autouse=True)
def clean_figs():
    yield
    plt.close("all")


# ── apply_figure_style ───────────────────────────────────────────────────────

def test_apply_figure_style_size_ladder_and_mechanics():
    fs.apply_figure_style()
    rc = plt.rcParams
    assert rc["font.size"] == 8 and rc["axes.labelsize"] == 8 and rc["axes.titlesize"] == 8
    assert rc["legend.fontsize"] == 7
    assert rc["xtick.labelsize"] == 6 and rc["ytick.labelsize"] == 6
    assert rc["savefig.dpi"] == 300 and rc["savefig.bbox"] == "tight"
    assert rc["legend.frameon"] is False
    assert rc["xtick.direction"] == "out"
    assert rc["axes.spines.top"] is False and rc["axes.spines.right"] is False  # open frame
    assert rc["pdf.fonttype"] == 42


def test_apply_figure_style_boxed_and_custom_sizes():
    fs.apply_figure_style(frame="boxed", sizes=(10, 9, 8))
    rc = plt.rcParams
    assert rc["axes.spines.top"] is True and rc["axes.spines.right"] is True
    assert rc["font.size"] == 10 and rc["xtick.labelsize"] == 8
    fs.apply_figure_style()  # restore defaults for other tests


def test_apply_figure_style_bad_frame():
    with pytest.raises(ValueError, match="frame"):
        fs.apply_figure_style(frame="triangle")


# ── set_frame / panel_letter ─────────────────────────────────────────────────

def test_set_frame_modes():
    fig, ax = plt.subplots()
    fs.set_frame(ax, "open")
    assert ax.spines["top"].get_visible() is False
    assert ax.spines["left"].get_visible() is True
    fs.set_frame(ax, "none")
    assert all(not ax.spines[s].get_visible() for s in ("top", "right", "bottom", "left"))


def test_panel_letter_case():
    fig, ax = plt.subplots()
    fs.panel_letter(ax, "a")
    fs.panel_letter(ax, "b", case="upper", dx=0.9)
    texts = [t.get_text() for t in ax.findobj(matplotlib.text.Text)]
    assert "a" in texts and "B" in texts
    bold = [t for t in ax.findobj(matplotlib.text.Text) if t.get_text() == "a"][0]
    assert bold.get_fontweight() in ("bold", 700)


# ── focal_palette ────────────────────────────────────────────────────────────

def test_focal_palette_modes():
    labels = ["ours", "m1", "m2"]
    out = fs.focal_palette(labels, "ours", "#D62728", other="grey")
    assert out[0] == "#D62728" and out[1] == out[2] == "#BCBCBC"
    out = fs.focal_palette(labels, "ours", "#D62728", other="ordinal")
    assert out[0] == "#D62728" and out[1] != out[2]  # ramp: lighter → darker
    out = fs.focal_palette(labels, "ours", "#D62728", other="muted",
                           base_colors=["#1f77b4", "#ff7f0e"])
    assert out[0] == "#D62728" and out[1] != "#1f77b4"  # muted toward grey


def test_focal_palette_focal_missing():
    with pytest.raises(ValueError, match="not found"):
        fs.focal_palette(["a", "b"], "zzz", "#D62728")


# ── bar_with_points / strip_with_median ──────────────────────────────────────

def test_bar_with_points_overlays_points():
    fig, ax = plt.subplots()
    ymat = [[1, 2, 3], [2, 3, 4]]
    fs.bar_with_points(ax, [0, 1], ymat, ["x", "y"], ["#444", "#888"])
    assert len(ax.patches) == 2                      # two bars
    assert len(ax.collections) == 2                  # two scatter overlays
    assert [t.get_text() for t in ax.get_xticklabels()] == ["x", "y"]


def test_bar_with_points_ci95_no_points():
    from matplotlib.collections import LineCollection, PathCollection
    fig, ax = plt.subplots()
    ymat = [[1, 2, 3], [2, 3, 4]]
    fs.bar_with_points(ax, [0, 1], ymat, ["x", "y"], ["#444", "#888"],
                       show_points=False, errorbar="ci95")
    assert not any(isinstance(c, PathCollection) for c in ax.collections)  # no scatter
    assert any(isinstance(c, LineCollection) for c in ax.collections)      # errorbar segments


def test_strip_with_median_tick():
    fig, ax = plt.subplots()
    vals = [[1, 2, 3, 4, 5]]
    fs.strip_with_median(ax, ["g"], vals)
    assert len(ax.collections) == 1                  # jittered points
    tick = [l for l in ax.lines if l.get_linewidth() == 1.6]
    assert len(tick) == 1 and np.allclose(tick[0].get_ydata(), [3.0, 3.0])


# ── small helpers ────────────────────────────────────────────────────────────

def test_goodness_arrow_and_two_tier_label():
    fig, ax = plt.subplots()
    fs.goodness_arrow(ax, axis="y")
    texts = [t.get_text() for t in ax.findobj(matplotlib.text.Text)]
    assert any("higher = better" in s for s in texts)
    assert fs.two_tier_label("RMSE", "n = 12") == "RMSE\nn = 12"


def test_end_of_line_labels():
    fig, ax = plt.subplots()
    xs = [np.array([0, 1, 2])]
    ys = [np.array([0, 1, 4])]
    ax.plot(xs[0], ys[0])
    fs.end_of_line_labels(ax, xs, ys, ["series A"])
    texts = [t.get_text() for t in ax.findobj(matplotlib.text.Text)]
    assert "series A" in texts


# ── panel_crops ──────────────────────────────────────────────────────────────

def test_panel_crops_lettered():
    fs.apply_figure_style()
    fig, (ax0, ax1) = plt.subplots(1, 2)
    ax0.plot([0, 1], [0, 1]); ax1.plot([0, 1], [1, 0])
    fs.panel_letter(ax0, "a"); fs.panel_letter(ax1, "b")
    crops = fs.panel_crops(fig)
    assert set(crops) == {"a", "b"}
    for box in crops.values():
        x0, y0, x1, y1 = box
        assert x0 >= 0 and y0 >= 0 and x1 > x0 and y1 > y0
    assert crops["a"][2] < crops["b"][0] or crops["a"][0] < crops["b"][0]  # a left of b


def test_panel_crops_fallback_per_axes():
    fs.apply_figure_style()
    fig, (ax0, ax1) = plt.subplots(1, 2)
    ax0.plot([0, 1], [0, 1]); ax1.plot([0, 1], [1, 0])
    crops = fs.panel_crops(fig)
    assert set(crops) == {"0", "1"}                # index-keyed fallback


def test_panel_crops_unions_sharey_siblings():
    fs.apply_figure_style()
    fig, (ax0, ax1) = plt.subplots(1, 2, sharey=True)
    fig.subplots_adjust(wspace=0.06)
    ax0.plot([0, 1], [0, 1]); ax1.plot([0, 1], [1, 0])
    fs.panel_letter(ax0, "a")                      # letter only on leftmost
    crops = fs.panel_crops(fig)
    assert set(crops) == {"a"}
    W = crops["a"][2]
    fig.canvas.draw()
    assert W > fig.get_size_inches()[0] * plt.rcParams["savefig.dpi"] * 0.5  # spans both panels

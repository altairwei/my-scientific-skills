"""Tests for figure_compose.py (stateless CLI; pillow-only).

Run via uv:

  uv run --with pillow --with pytest pytest scientific-writing/figure-composer/tests/ -v
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import figure_compose as fc  # noqa: E402

OUTLINE = {
    "claim": "test claim", "width_mm": 180, "ncol": 12,
    "row_heights_mm": [60, 60],
    "panels": [
        {"letter": "a", "role": "hero", "row": 0, "col": 0, "colspan": 12,
         "chart_family": "schematic", "message": "m", "ask": "k", "data_path": None},
        {"letter": "b", "role": "primary", "row": 1, "col": 0, "colspan": 7,
         "chart_family": "scatter", "message": "m", "ask": "k"},
        {"letter": "c", "role": "supporting", "row": 1, "col": 7, "colspan": 5,
         "chart_family": "strip", "message": "m", "ask": "k"},
    ],
}

MM = 300 / 25.4
W_FULL = int(180 * MM)          # 2125
G = int(4 * MM)                 # 47
COLW = (W_FULL - G * 11) // 12  # 134
ROWH = int(60 * MM)             # 708


# ── grid math ────────────────────────────────────────────────────────────────

def test_grid_geom():
    W, ncol, colw, rowh, row_y, g = fc.grid_geom(OUTLINE)
    assert (W, ncol, colw, g) == (W_FULL, 12, COLW, G)
    assert rowh == [ROWH, ROWH] and row_y == [0, ROWH + G]


def test_panel_px_spans():
    assert fc.panel_px(OUTLINE, "a") == (COLW * 12 + G * 11, ROWH)       # full width
    assert fc.panel_px(OUTLINE, "b") == (COLW * 7 + G * 6, ROWH)
    assert fc.panel_px(OUTLINE, "c") == (COLW * 5 + G * 4, ROWH)
    wb, _ = fc.panel_px(OUTLINE, "b"); wc, _ = fc.panel_px(OUTLINE, "c")
    assert wb + wc + G == W_FULL                                          # b+c+1 gutter = full row


def test_panel_xy_and_unknown_letter():
    assert fc.panel_xy(OUTLINE, "b") == (0, ROWH + G)
    assert fc.panel_xy(OUTLINE, "c") == (7 * (COLW + G), ROWH + G)
    with pytest.raises(KeyError):
        fc.panel_px(OUTLINE, "z")


# ── validate ─────────────────────────────────────────────────────────────────

def _bad(patch):
    o = json.loads(json.dumps(OUTLINE))
    patch(o)
    return fc.validate_outline(o)


def test_validate_good():
    assert fc.validate_outline(OUTLINE) == []


def test_validate_catches_errors():
    assert any("claim" in e for e in _bad(lambda o: o.pop("claim")))
    assert any("role" in e for e in _bad(lambda o: o["panels"][0].update(role="king")))
    assert any("duplicate" in e for e in _bad(lambda o: o["panels"][1].update(letter="a")))
    assert any("ncol" in e for e in _bad(lambda o: o["panels"][1].update(colspan=13)))
    assert any("row" in e.lower() for e in _bad(lambda o: o["panels"][1].update(rowspan=2)))
    assert any("overlap" in e for e in _bad(lambda o: o["panels"][1].update(col=6)))


# ── compose + crops ──────────────────────────────────────────────────────────

def _make_panels(tmp_path, outline=OUTLINE):
    paths = {}
    for p in outline["panels"]:
        w, h = fc.panel_px(outline, p["letter"])
        im = Image.new("RGBA", (w, h), (200, 30 * (ord(p["letter"]) - 96), 30, 255))
        if p["letter"] == "b":
            for x in range(0, w // 2):                      # transparent TL quadrant
                for y in range(0, h // 2):
                    im.putpixel((x, y), (0, 0, 0, 0))
        path = tmp_path / f"panel_{p['letter']}.png"
        im.save(path)
        paths[p["letter"]] = str(path)
    return paths


def test_compose_figure_tiles_and_stamps(tmp_path):
    paths = _make_panels(tmp_path)
    out, (W, H) = fc.compose_figure(OUTLINE, paths, str(tmp_path / "fig.png"))
    assert (W, H) == (W_FULL, ROWH + G + ROWH)
    im = Image.open(out).convert("RGB")
    # panel content landed (a spans the top row)
    ax, ay = fc.panel_xy(OUTLINE, "a")
    assert im.getpixel((ax + 100, ay + 100)) != (255, 255, 255)
    # RGBA paste: b's transparent quadrant shows the white canvas
    bx, by = fc.panel_xy(OUTLINE, "b")
    assert im.getpixel((bx + 10, by + 10)) == (255, 255, 255)
    # letter stamp: dark pixels near each panel's top-left stamp zone
    for L in "abc":
        x, y = fc.panel_xy(OUTLINE, L)
        region = im.crop((x + 5, y + 3, x + 60, y + 30))
        assert min(region.getextrema()[0][0], 255) < 128, f"no stamp for {L}"


def test_compose_crops_bounds():
    crops = fc.compose_crops(OUTLINE, pad_px=4)
    assert set(crops) == {"a", "b", "c"}
    H = ROWH + G + ROWH
    for L, (x0, y0, x1, y1) in crops.items():
        px = fc.panel_xy(OUTLINE, L)
        assert x0 == max(px[0] - 4, 0) and y0 == max(px[1] - 4, 0)
        assert 0 <= x0 < x1 <= W_FULL and 0 <= y0 < y1 <= H


# ── fixes grouping ───────────────────────────────────────────────────────────

def test_group_fixes_by_panel():
    review = {"violations": [
        {"severity": "BLOCKER", "rule_ref": "§2.1", "location": "panel b",
         "panel_letter": "b", "finding": "unlabelled series", "fix": "label it"},
        {"severity": "MINOR", "panel_letter": "b", "finding": "nit", "fix": "x"},
        {"severity": "MAJOR", "rule_ref": "§4.5", "location": "panel c",
         "finding": "red/green", "fix": "recolour"},
    ]}
    out = fc.group_fixes_by_panel(review)
    assert set(out) == {"b", "c"}                    # MINOR excluded
    assert "BLOCKER" in out["b"] and "unlabelled series" in out["b"]
    assert "c" in out and "§4.5" in out["c"]         # letter from location fallback


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT_DIR / "figure_compose.py"), *args],
                          capture_output=True, text=True, cwd=cwd)


def test_cli_help():
    r = _cli("--help")
    assert r.returncode == 0 and "compose" in r.stdout and "validate" in r.stdout


def test_cli_validate_and_panel_px(tmp_path):
    good = tmp_path / "o.json"; good.write_text(json.dumps(OUTLINE))
    r = _cli("validate", str(good))
    assert r.returncode == 0 and json.loads(r.stdout)["ok"] is True
    bad = tmp_path / "bad.json"
    o = json.loads(json.dumps(OUTLINE)); o["panels"][1]["letter"] = "a"
    bad.write_text(json.dumps(o))
    r = _cli("validate", str(bad))
    assert r.returncode == 1 and json.loads(r.stdout)["ok"] is False
    r = _cli("panel-px", str(good), "b")
    assert r.stdout.strip() == f"{COLW * 7 + G * 6}x{ROWH}"


def test_cli_compose_end_to_end(tmp_path):
    (tmp_path / "outline.json").write_text(json.dumps(OUTLINE))
    _make_panels(tmp_path)
    r = _cli("compose", "outline.json", "--panels", ".", "--out", "fig.png", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout)
    assert info["width_px"] == W_FULL
    assert Image.open(tmp_path / "fig.png").size == (W_FULL, ROWH + G + ROWH)
    # missing panel file → exit 1
    (tmp_path / "panel_b.png").unlink()
    r = _cli("compose", "outline.json", "--panels", ".", "--out", "x.png", cwd=tmp_path)
    assert r.returncode == 1 and "missing panel file" in r.stderr

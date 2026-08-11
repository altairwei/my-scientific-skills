#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""figure_compose — deterministic half of multi-panel figure composition.

Stateless CLI; the reasoning (writing the outline, rendering panels, judging
reviews) is Claude/Agent-orchestrated — see the figure-composer SKILL.md.

Subcommands:
  compose   OUTLINE --panels DIR --out FIG.png   tile panel_{letter}.pngs + stamp letters
  crops     OUTLINE [--pad-px N]                 per-panel pixel crop boxes of the composed PNG
  panel-px  OUTLINE LETTER                       exact WxH px a panel must render at
  validate  OUTLINE                              structural check of an outline JSON
  fixes     REVIEW                               group a review's BLOCKER/MAJOR violations by panel

OUTLINE is a JSON file (schema in references/prompts.md). All output is JSON
on stdout except panel-px (prints WxH). Errors go to stderr, exit 1.
"""
import argparse
import json
import sys

ROLES = ("schematic", "hero", "primary", "supporting")


# ── grid geometry (port of science-skills figure-composer/kernel.py) ─────────

def grid_geom(outline, dpi=300, gutter_mm=4):
    mm = dpi / 25.4
    W = int(outline["width_mm"] * mm)
    ncol = outline["ncol"]
    g = int(gutter_mm * mm)
    colw = (W - g * (ncol - 1)) // ncol
    rowh = [int(h * mm) for h in outline["row_heights_mm"]]
    row_y = [sum(rowh[:i]) + g * i for i in range(len(rowh))]
    return W, ncol, colw, rowh, row_y, g


def _panel(outline, letter):
    for p in outline["panels"]:
        if p["letter"] == letter:
            return p
    raise KeyError(f"no panel with letter {letter!r}")


def panel_px(outline, letter, dpi=300, gutter_mm=4):
    _, _, colw, rowh, _, g = grid_geom(outline, dpi, gutter_mm)
    p = _panel(outline, letter)
    cs, rs, r = p["colspan"], p.get("rowspan", 1), p["row"]
    return colw * cs + g * (cs - 1), sum(rowh[r:r + rs]) + g * (rs - 1)


def panel_xy(outline, letter, dpi=300, gutter_mm=4):
    _, _, colw, _, row_y, g = grid_geom(outline, dpi, gutter_mm)
    p = _panel(outline, letter)
    return p["col"] * (colw + g), row_y[p["row"]]


def compose_crops(outline, dpi=300, gutter_mm=4, pad_px=4):
    """Pixel crop boxes {letter: (x0,y0,x1,y1)} for the composed PNG (origin
    top-left, matching PIL.Image.crop). Use after `compose` for the §3.5/§9.2
    crop-and-Read perceptual self-QA."""
    W, _, _, rowh, row_y, _ = grid_geom(outline, dpi, gutter_mm)
    H = row_y[-1] + rowh[-1]
    out = {}
    for p in outline["panels"]:
        L = p["letter"]
        w, h = panel_px(outline, L, dpi, gutter_mm)
        x, y = panel_xy(outline, L, dpi, gutter_mm)
        out[L] = [max(x - pad_px, 0), max(y - pad_px, 0),
                  min(x + w + pad_px, W), min(y + h + pad_px, H)]
    return out


def _load_letter_font(letter_font, letter_pt, dpi):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(letter_font, int(letter_pt / 72 * dpi))
    except Exception:
        pass
    try:  # matplotlib bundles DejaVuSans-Bold — use it if importable
        import matplotlib, os
        p = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data",
                         "fonts", "ttf", "DejaVuSans-Bold.ttf")
        return ImageFont.truetype(p, int(letter_pt / 72 * dpi))
    except Exception:
        return ImageFont.load_default()


def compose_figure(outline, panel_paths, out_path, dpi=300, gutter_mm=4,
                   letter_pt=9, letter_case="lower"):
    from PIL import Image, ImageDraw
    W, _, _, rowh, row_y, _ = grid_geom(outline, dpi, gutter_mm)
    H = row_y[-1] + rowh[-1]
    canvas = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(canvas)
    ft = _load_letter_font("DejaVuSans-Bold.ttf", letter_pt, dpi)
    for p in outline["panels"]:
        L = p["letter"]
        w, h = panel_px(outline, L, dpi, gutter_mm)
        x, y = panel_xy(outline, L, dpi, gutter_mm)
        im = Image.open(panel_paths[L]).convert("RGBA")
        if im.size != (w, h):
            im = im.resize((w, h))
        canvas.paste(im, (x, y), im)
        stamp = L.lower() if letter_case == "lower" else L.upper()
        draw.text((x + int(1.5 / 25.4 * dpi), y + int(1 / 25.4 * dpi)),
                  stamp, fill="black", font=ft)
    canvas.save(out_path)
    return out_path, (W, H)


# ── review post-processing ───────────────────────────────────────────────────

def group_fixes_by_panel(review):
    """{letter: markdown fix list} from a review's BLOCKER/MAJOR violations."""
    import re
    out = {}
    for v in review.get("violations", []):
        if v.get("severity") not in ("BLOCKER", "MAJOR"):
            continue
        L = v.get("panel_letter")
        if not L:  # fallback: "… panel c …" in free-text location, else first char
            m = re.search(r"panel\s+([A-Za-z])\b", v.get("location", ""))
            L = m.group(1) if m else (v.get("location", " ") + " ")[0]
        out.setdefault(L, []).append(
            f"- **[{v['severity']}]** ({v.get('rule_ref', '')}, {v.get('location', '')}) "
            f"{v.get('finding', '')} **Fix:** {v.get('fix', '')}")
    return {k: "\n".join(v) for k, v in out.items()}


# ── outline validation (hand-rolled — outlines are hand-written JSON) ────────

def validate_outline(o):
    errs = []
    for k, t in [("claim", str), ("width_mm", (int, float)),
                 ("ncol", int), ("row_heights_mm", list), ("panels", list)]:
        if k not in o:
            errs.append(f"missing top-level key {k!r}")
        elif not isinstance(o[k], t):
            errs.append(f"{k!r} must be {t}")
    if errs:
        return errs
    nrow = len(o["row_heights_mm"])
    if not all(isinstance(h, (int, float)) and h > 0 for h in o["row_heights_mm"]):
        errs.append("row_heights_mm must be positive numbers")
    letters = []
    occupied = {}
    for i, p in enumerate(o["panels"]):
        where = f"panels[{i}]" + (f" ({p.get('letter')})" if p.get("letter") else "")
        for k in ("letter", "role", "message", "chart_family", "row", "col",
                      "colspan", "ask"):
            if k not in p:
                errs.append(f"{where}: missing {k!r}")
        if "role" in p and p["role"] not in ROLES:
            errs.append(f"{where}: role must be one of {ROLES}")
        L = p.get("letter")
        if L in letters:
            errs.append(f"{where}: duplicate letter {L!r}")
        letters.append(L)
        r, c = p.get("row", 0), p.get("col", 0)
        cs, rs = p.get("colspan", 1), p.get("rowspan", 1)
        if c + cs > o["ncol"]:
            errs.append(f"{where}: col+colspan ({c}+{cs}) exceeds ncol {o['ncol']}")
        if r + rs > nrow:
            errs.append(f"{where}: row+rowspan ({r}+{rs}) exceeds {nrow} rows")
        for rr in range(r, r + rs):
            for cc in range(c, c + cs):
                cell = (rr, cc)
                if cell in occupied:
                    errs.append(f"{where}: grid cell r{rr}c{cc} overlaps panel "
                                f"{occupied[cell]!r}")
                occupied[cell] = L
    return errs


# ── CLI ──────────────────────────────────────────────────────────────────────

def _load_json(path):
    with open(path) as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="figure_compose",
                                 description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_grid_args(sp):
        sp.add_argument("--dpi", type=int, default=300)
        sp.add_argument("--gutter-mm", type=int, default=4)

    sp = sub.add_parser("compose", help="tile panel PNGs + stamp letters")
    sp.add_argument("outline")
    sp.add_argument("--panels", required=True, help="dir holding panel_{letter}.png")
    sp.add_argument("--out", required=True)
    sp.add_argument("--letter-case", choices=["lower", "upper"], default="lower")
    sp.add_argument("--letter-pt", type=float, default=9)
    add_grid_args(sp)

    sp = sub.add_parser("crops", help="per-panel crop boxes of the composed PNG")
    sp.add_argument("outline")
    sp.add_argument("--pad-px", type=int, default=4)
    add_grid_args(sp)

    sp = sub.add_parser("panel-px", help="exact WxH px a panel must render at")
    sp.add_argument("outline")
    sp.add_argument("letter")
    add_grid_args(sp)

    sp = sub.add_parser("validate", help="structural check of an outline JSON")
    sp.add_argument("outline")

    sp = sub.add_parser("fixes", help="group BLOCKER/MAJOR review violations by panel")
    sp.add_argument("review")

    args = ap.parse_args(argv)

    if args.cmd == "compose":
        import os
        o = _load_json(args.outline)
        errs = validate_outline(o)
        if errs:
            for e in errs:
                print(f"outline error: {e}", file=sys.stderr)
            return 1
        panel_paths = {}
        for p in o["panels"]:
            path = os.path.join(args.panels, f"panel_{p['letter']}.png")
            if not os.path.exists(path):
                print(f"missing panel file: {path}", file=sys.stderr)
                return 1
            panel_paths[p["letter"]] = path
        out, (W, H) = compose_figure(o, panel_paths, args.out, dpi=args.dpi,
                                     gutter_mm=args.gutter_mm,
                                     letter_pt=args.letter_pt,
                                     letter_case=args.letter_case)
        print(json.dumps({"out": out, "width_px": W, "height_px": H}))
    elif args.cmd == "crops":
        print(json.dumps(compose_crops(_load_json(args.outline), dpi=args.dpi,
                                       gutter_mm=args.gutter_mm,
                                       pad_px=args.pad_px), indent=1))
    elif args.cmd == "panel-px":
        w, h = panel_px(_load_json(args.outline), args.letter, dpi=args.dpi,
                        gutter_mm=args.gutter_mm)
        print(f"{w}x{h}")
    elif args.cmd == "validate":
        o = _load_json(args.outline)
        errs = validate_outline(o)
        print(json.dumps({"ok": not errs, "errors": errs,
                          "n_panels": len(o.get("panels", []))}, indent=1))
        return 0 if not errs else 1
    elif args.cmd == "fixes":
        print(json.dumps(group_fixes_by_panel(_load_json(args.review)), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

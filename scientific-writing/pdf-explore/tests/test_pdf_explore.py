"""Tests for pdf_explore.py.

Run via uv (deps auto-resolved from --with flags):

  uv run --with pytest --with reportlab --with pypdfium2 --with pillow --with pypdf \\
    pytest scientific-writing/pdf-explore/tests/

The fixture PDF is generated inline with reportlab (2 pages: a heading +
body text each), so no binary fixture is checked in. pypdfium2 is the
script's primary backend; reportlab only generates the fixture.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("reportlab")      # fixture generation
pytest.importorskip("pypdfium2")      # script's primary backend

# import the script as a module (it lives in ../scripts/)
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import pdf_explore  # noqa: E402


def _args(**kw):
    return argparse.Namespace(**kw)


@pytest.fixture(scope="module")
def fixture_pdf(tmp_path_factory):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    p = tmp_path_factory.mktemp("pdf") / "fixture.pdf"
    c = canvas.Canvas(str(p), pagesize=letter)
    # page 1 — body repeated so mean_chars/page > 80 (the scanned threshold),
    # otherwise the sparse fixture trips mode_hint="image" despite a real text layer.
    c.drawString(72, 720, "1 Introduction")
    c.drawString(72, 700, "hello world from page one. " * 12)
    c.showPage()
    # page 2
    c.drawString(72, 720, "2 Methods")
    c.drawString(72, 700, "We applied Harmony for batch correction on the cells. " * 12)
    c.showPage()
    c.save()
    return str(p)


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_parse_pages():
    assert pdf_explore.parse_pages(None) is None
    assert pdf_explore.parse_pages("") is None
    assert pdf_explore.parse_pages("5") == [5]
    assert pdf_explore.parse_pages("5,21-25,62") == [5, 21, 22, 23, 24, 25, 62]
    assert pdf_explore.parse_pages("3-1") == [1, 2, 3]  # reversed range


def test_resolve_path_missing():
    with pytest.raises(FileNotFoundError):
        pdf_explore.resolve_path("nope-does-not-exist.pdf")


# ── extract_text ─────────────────────────────────────────────────────────────

def test_text_extract_all(fixture_pdf):
    pages = pdf_explore.extract_text(fixture_pdf)
    assert len(pages) == 2
    assert pages[0]["page"] == 1
    assert "hello world" in pages[0]["text"]
    assert "Harmony" in pages[1]["text"]


def test_text_extract_subset(fixture_pdf):
    pages = pdf_explore.extract_text(fixture_pdf, pages=[2])
    assert len(pages) == 1
    assert pages[0]["page"] == 2


# ── subcommands (capture stdout JSON) ──────────────────────────────────────

def test_cmd_info(fixture_pdf, capsys):
    pdf_explore.cmd_info(_args(path=fixture_pdf))
    out = json.loads(capsys.readouterr().out)
    assert out["n_pages"] == 2
    assert out["mode_hint"] == "text"  # has a real text layer


def test_cmd_outline(fixture_pdf, capsys):
    pdf_explore.cmd_outline(_args(path=fixture_pdf))
    outl = json.loads(capsys.readouterr().out)
    headings = [e["heading"] for e in outl]
    assert any("Introduction" in h for h in headings), headings
    assert any("Methods" in h for h in headings), headings


def test_cmd_text_writes_file(fixture_pdf, tmp_path, capsys):
    out_path = str(tmp_path / "out.txt")
    pdf_explore.cmd_text(_args(path=fixture_pdf, pages=None, mode="text", out=out_path))
    assert "wrote" in capsys.readouterr().out
    assert os.path.exists(out_path)
    content = Path(out_path).read_text()
    assert "hello world" in content
    assert "── page 1 ──" in content
    assert "── page 2 ──" in content


def test_cmd_text_pages_subset(fixture_pdf, tmp_path):
    out_path = str(tmp_path / "sec.txt")
    pdf_explore.cmd_text(_args(path=fixture_pdf, pages="2", mode="text", out=out_path))
    content = Path(out_path).read_text()
    assert "── page 2 ──" in content
    assert "── page 1 ──" not in content


def test_cmd_grep(fixture_pdf, capsys):
    pdf_explore.cmd_grep(_args(path=fixture_pdf, query="Harmony",
                               ignore_case=True, context=40))
    hits = json.loads(capsys.readouterr().out)
    assert len(hits) == 1
    assert hits[0]["page"] == 2
    assert hits[0]["n_hits"] >= 1
    assert "Harmony" in hits[0]["snippets"][0]


def test_cmd_grep_case_sensitive_miss(fixture_pdf, capsys):
    # "harmony" lowercase is in "Harmony"? No — case-sensitive "harmony" shouldn't match "Harmony"
    pdf_explore.cmd_grep(_args(path=fixture_pdf, query="harmony",
                               ignore_case=False, context=20))
    hits = json.loads(capsys.readouterr().out)
    assert hits == []


# ── render + crop ───────────────────────────────────────────────────────────

def test_render(fixture_pdf, tmp_path):
    d = str(tmp_path / "renders")
    out = pdf_explore.render_pages(fixture_pdf, [1, 2], dpi=100, out_dir=d)
    assert len(out) == 2
    for r in out:
        assert os.path.exists(r["image_path"])


def test_render_cache_hit(fixture_pdf, tmp_path):
    d = str(tmp_path / "renders")
    out1 = pdf_explore.render_pages(fixture_pdf, [1], dpi=100, out_dir=d)
    png1 = out1[0]["image_path"]
    mtime1 = os.path.getmtime(png1)
    # second call at same path+mtime+dpi reuses the existing PNG (not rewritten)
    out2 = pdf_explore.render_pages(fixture_pdf, [1], dpi=100, out_dir=d)
    assert out2[0]["image_path"] == png1
    assert os.path.getmtime(png1) == mtime1


def test_cmd_crop(fixture_pdf, tmp_path):
    out = pdf_explore.render_pages(fixture_pdf, [1], dpi=100,
                                   out_dir=str(tmp_path / "r"))
    png = out[0]["image_path"]
    from PIL import Image
    w, h = Image.open(png).size
    crop_out = str(tmp_path / "crop.png")
    pdf_explore.cmd_crop(_args(image=png, box=f"0,0,{w // 2},{h // 2}", out=crop_out))
    assert os.path.exists(crop_out)
    cw, ch = Image.open(crop_out).size
    assert cw == w // 2 and ch == h // 2


def test_cmd_crop_bad_box(fixture_pdf, tmp_path):
    out = pdf_explore.render_pages(fixture_pdf, [1], dpi=100,
                                   out_dir=str(tmp_path / "r"))
    with pytest.raises(ValueError):
        pdf_explore.cmd_crop(_args(image=out[0]["image_path"], box="1,2,3", out=None))

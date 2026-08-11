"""Tests for literature_review.py.

Run via uv (the script is stdlib-only, so just pytest):

  uv run --with pytest pytest scientific-writing/literature-review/tests/ -v
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import literature_review as lr  # noqa: E402


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_extract_dois_clean_and_markdown():
    text = ("see [Chen 2019](https://doi.org/10.1038/abc123) and "
            "10.1101/2020.01.02.xyz; also 10.1234/def</b> here")
    dois = lr.extract_dois(text)
    assert "10.1038/abc123" in dois
    assert "10.1101/2020.01.02.xyz" in dois
    assert "10.1234/def" in dois  # truncated at </


def test_extract_dois_html_entity_and_parens():
    # &#x2F; → /  (so a DOI split across an entity reassembles); trailing ) stripped
    text = "see 10.1034/abc&#x2F;def and (10.1038/zzz)"
    dois = lr.extract_dois(text)
    assert "10.1034/abc/def" in dois
    assert "10.1038/zzz" in dois


def test_extract_dois_dedupes_and_sorts():
    dois = lr.extract_dois("10.1234/aaa 10.1234/aaa 10.1234/bbb")
    assert dois == ["10.1234/aaa", "10.1234/bbb"]


def test_crossref_year():
    assert lr.crossref_year({"published": {"date-parts": [[2020]]}}) == 2020
    assert lr.crossref_year({"published": {"date-parts": [[None]]}}) is None
    assert lr.crossref_year({}) is None
    assert lr.crossref_year({"published": {}}) is None


def test_quote_doi_path():
    assert lr.quote_doi_path("10.1038/abc") == "10.1038/abc"
    assert lr.quote_doi_path("10.1038/a(b)c") == "10.1038/a%28b%29c"
    # pre-encoded stays single-encoded (unquote-then-quote)
    assert lr.quote_doi_path("10.1038/a%28b%29c") == "10.1038/a%28b%29c"


def test_html_decode():
    assert lr.html_decode("a&amp;b") == "a&b"
    assert lr.html_decode("a&#x2F;b") == "a/b"
    assert lr.html_decode("a&#47;b") == "a/b"
    assert lr.html_decode("x&lt;y&gt;z&nbsp;w") == "x<y>z w"


# ── style_pass (each code fires; clean → ok) ───────────────────────────────

def test_style_pass_clean():
    draft = "## Methods\n\nWe pooled the estimates. The effect is modest. See [Park 2020](https://doi.org/10.1038/abc).\n"
    r = lr.style_pass(draft)
    assert r["ok"] is True
    assert r["issues"] == []


def test_style_pass_emdash():
    # 10 em-dashes in ~80 words → 1000*10/80 = 125 > 8
    draft = "word — word — word — word — word — word — word — word — word — word end."
    r = lr.style_pass(draft)
    codes = [i["code"] for i in r["issues"]]
    assert "EMDASH" in codes


def test_style_pass_honest():
    r = lr.style_pass("the honest answer is that it works.")
    assert "HONEST" in [i["code"] for i in r["issues"]]


def test_style_pass_procnote():
    r = lr.style_pass("All DOIs were verified against CrossRef. No retractions.")
    assert "PROCNOTE" in [i["code"] for i in r["issues"]]


def test_style_pass_parendoi():
    r = lr.style_pass("[Author](https://doi.org/10.1038/abc(zz))")
    assert "PARENDOI" in [i["code"] for i in r["issues"]]


def test_style_pass_longhead():
    draft = ("## This is a very long heading that exceeds the word limit\n\nx\n\n"
             "## Another overly long sentence heading that goes on too long\n\ny\n")
    r = lr.style_pass(draft)
    assert "LONGHEAD" in [i["code"] for i in r["issues"]]


def test_style_pass_flatstruct():
    draft = "\n".join(f"## Heading {i}" for i in range(8)) + "\n\nbody\n"
    r = lr.style_pass(draft)
    assert "FLATSTRUCT" in [i["code"] for i in r["issues"]]


# ── litrev_contact (git-sourced; lenient) ─────────────────────────────────

def test_litrev_contact_str_or_none():
    lr.litrev_contact.cache_clear()
    result = lr.litrev_contact()
    assert result is None or (isinstance(result, str) and "@" in result and " " not in result)


# ── verify_dois (mocked network) ───────────────────────────────────────────

@pytest.fixture
def no_sleep(monkeypatch):
    """verify_dois calls time.sleep(0.06) per DOI — no-op it in tests."""
    monkeypatch.setattr(lr.time, "sleep", lambda *a, **k: None)


def test_verify_dois_crossref_hit(monkeypatch, no_sleep):
    monkeypatch.setattr(lr, "litrev_get", lambda url, timeout=15: {
        "message": {"title": ["My Paper"], "published": {"date-parts": [[2020]]},
                    "container-title": ["Nature"], "update-to": [], "subtype": ""}
    })
    monkeypatch.setattr(lr, "litrev_head", lambda url, timeout=10: None)
    out = lr.verify_dois(["10.1038/abc"])
    assert out["10.1038/abc"]["ok"] is True
    assert out["10.1038/abc"]["title"] == "My Paper"
    assert out["10.1038/abc"]["year"] == 2020
    assert out["10.1038/abc"]["journal"] == "Nature"
    assert out["10.1038/abc"]["retracted"] is False
    assert out["10.1038/abc"]["registry"] == "crossref"


def test_verify_dois_retracted(monkeypatch, no_sleep):
    monkeypatch.setattr(lr, "litrev_get", lambda url, timeout=15: {
        "message": {"title": ["Retracted Paper"],
                    "update-to": [{"type": "retraction"}],
                    "container-title": ["X"], "subtype": ""}
    })
    out = lr.verify_dois(["10.1038/r"])
    assert out["10.1038/r"]["ok"] is True
    assert out["10.1038/r"]["retracted"] is True


def test_verify_dois_retracted_by_title(monkeypatch, no_sleep):
    monkeypatch.setattr(lr, "litrev_get", lambda url, timeout=15: {
        "message": {"title": ["RETRACTED: bogus claim"],
                    "update-to": [], "container-title": ["X"], "subtype": ""}
    })
    out = lr.verify_dois(["10.1038/rt"])
    assert out["10.1038/rt"]["retracted"] is True


def test_verify_dois_doiorg_302_noncrossref(monkeypatch, no_sleep):
    # CrossRef miss → doi.org resolves → ok=True, non-crossref registry
    monkeypatch.setattr(lr, "litrev_get", lambda url, timeout=15: None)
    monkeypatch.setattr(lr, "litrev_head", lambda url, timeout=10: 302)
    out = lr.verify_dois(["10.1234/abc"])  # DataCite-style
    assert out["10.1234/abc"]["ok"] is True
    assert out["10.1234/abc"]["registry"] == "non-crossref"
    assert out["10.1234/abc"]["retracted"] is None


def test_verify_dois_doiorg_404_fabricated(monkeypatch, no_sleep):
    monkeypatch.setattr(lr, "litrev_get", lambda url, timeout=15: None)
    monkeypatch.setattr(lr, "litrev_head", lambda url, timeout=10: 404)
    out = lr.verify_dois(["10.9999/fake"])
    assert out["10.9999/fake"]["ok"] is False


def test_verify_dois_network_none_unverified(monkeypatch, no_sleep):
    monkeypatch.setattr(lr, "litrev_get", lambda url, timeout=15: None)
    monkeypatch.setattr(lr, "litrev_head", lambda url, timeout=10: None)
    out = lr.verify_dois(["10.1038/unk"])
    assert out["10.1038/unk"]["ok"] is None  # NOT fabricated — don't flag
    assert "error" in out["10.1038/unk"]


def test_verify_dois_dot_segment_rejected(monkeypatch, no_sleep):
    called = []
    monkeypatch.setattr(lr, "litrev_get", lambda *a, **k: called.append("get") or None)
    monkeypatch.setattr(lr, "litrev_head", lambda *a, **k: called.append("head") or 200)
    out = lr.verify_dois(["10.1234/../bad"])
    assert out["10.1234/../bad"]["ok"] is False
    assert out["10.1234/../bad"]["error"] == "dot-segment in DOI"
    assert called == []  # rejected up-front, no network call


# ── CLI smoke ────────────────────────────────────────────────────────────────

def test_main_help():
    r = subprocess.run([sys.executable, str(SCRIPT_DIR / "literature_review.py"), "--help"],
                        capture_output=True, text=True)
    assert r.returncode == 0
    assert "verify-dois" in r.stdout
    assert "search-openalex" in r.stdout
    assert "style-pass" in r.stdout


def test_main_bad_subcommand():
    r = subprocess.run([sys.executable, str(SCRIPT_DIR / "literature_review.py"), "bogus"],
                        capture_output=True, text=True)
    assert r.returncode != 0

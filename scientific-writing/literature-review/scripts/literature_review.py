#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""literature_review — stateless literature lookup + verification CLI.

Find, verify, and walk the citation graph of scientific papers via
CrossRef / OpenAlex / doi.org — and lint the synthesis prose. Stdlib
only (urllib/json/re/time); no third-party deps, no LLM, no API keys,
no env-var config. Claude orchestrates: run a subcommand, read the JSON,
write the synthesis.

Adapted from the literature-review skill's kernel.py (Apache-2.0). The
sidecar's `import host` is gone (Claude Code has no host SDK); the
original's `host.get_user_email()` for the CrossRef/OpenAlex polite-pool
mailto is replaced with `git config user.email` — zero-config (every
developer's git has this), cached per-process, anonymous fallback if
git is unavailable or has no email. The email goes in the API request
(UA suffix / mailto param), identifying the caller for better rate
limits; nothing is sent to the user. The battle-hardened details — DOI
dot-segment defense, doi.org no-redirect HEAD (302=registered /
404=fabricated), 3-valued `ok`, and the regex-only no-LLM `style_pass`
(injection-safe) — are preserved.

Subcommands: verify-dois | crossref-lookup | search-openalex |
expand-citations | extract-dois | style-pass
"""
import argparse
import functools
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


DOI_PATTERN = r"10\.\d{4,9}/[^\s\"'`\]\}—–&|]+"

@functools.lru_cache(maxsize=1)
def litrev_contact():
    """User email for the CrossRef/OpenAlex polite pool, read from
    `git config user.email` — zero-config. Cached per process so a 50-DOI
    verify only forks git once. Returns None if git is unavailable or has
    no email configured; fetches then run anonymously (best-effort, never
    fails). The email goes in the API request (UA suffix / mailto param);
    nothing is sent to the user."""
    try:
        r = subprocess.run(["git", "config", "user.email"],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    email = (r.stdout or "").strip()
    # basic sanity: must contain '@', no spaces, <320 chars (RFC max)
    if email and "@" in email and " " not in email and len(email) < 320:
        return email
    return None


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def litrev_get(url, timeout=15):
    """GET `url` and JSON-decode. One 2s retry on HTTP 429; None on any error."""
    c = litrev_contact()
    ua = "ClaudeScience-literature-review/1.0" + (f" (mailto:{c})" if c else "")
    ua = ua.encode("ascii", "ignore").decode("ascii")
    for attempt in (0, 1):
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(2)
                continue
            return None
        except Exception:
            return None
    return None


def litrev_head(url, timeout=10):
    """HEAD `url` WITHOUT following redirects; return the origin server's own
    status (so doi.org returns 302 for a registered DOI and 404 for an
    unregistered one — not the publisher's status). One 2s retry on 429.
    Returns None only when no status could be obtained (connection/timeout)."""
    c = litrev_contact()
    ua = ("ClaudeScience-literature-review/1.0" + (f" (mailto:{c})" if c else "")).encode(
        "ascii", "ignore"
    ).decode("ascii")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # noqa:_RET

    opener = urllib.request.build_opener(NoRedirect)
    for attempt in (0, 1):
        req = urllib.request.Request(url, headers={"User-Agent": ua}, method="HEAD")
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(2)
                continue
            return e.code
        except Exception:
            return None
    return None


def quote_doi_path(doi):
    """URL-encode a DOI path; unquote each segment first so a pre-encoded
    %28 stays single-encoded (caller may pass either form)."""
    return "/".join(
        urllib.parse.quote(urllib.parse.unquote(seg), safe="") for seg in doi.split("/")
    )


def crossref_year(m):
    """Safely extract the publication year from a CrossRef `message` record."""
    dp = (m.get("published") or {}).get("date-parts") or [[None]]
    return (dp[0] or [None])[0]


def html_decode(s):
    """Minimal HTML entity decode for DOI extraction (lt/gt/amp/nbsp/slash)."""
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"),
                 ("&nbsp;", " "), ("&#x2F;", "/"), ("&#47;", "/")):
        s = s.replace(a, b)
    return s


# ── the six operations ───────────────────────────────────────────────────────

def verify_dois(dois):
    """Resolve each DOI against CrossRef, with a doi.org HEAD fallback for
    DataCite/mEDRA/arXiv DOIs. Returns {doi: {ok, title?, year?, journal?,
    retracted?, registry?, error?}} where:
      ok=True  — resolves (CrossRef hit, or doi.org 2xx/3xx);
      ok=False — does NOT resolve (doi.org 404; likely fabricated or typo);
      ok=None  — could not be verified (network/transient/5xx); do not flag
                 as fabricated.
    `retracted` is True/False only on a CrossRef hit; None when the registry
    is non-CrossRef or the lookup was unverified."""
    out = {}
    for d in dois:
        d = d.strip()
        # No registration agency uses `.`/`..`/empty path segments in a DOI
        # suffix; reject up-front so a server/CDN that dot-segment-normalizes
        # can't make a fabricated identifier appear to resolve. Decode the WHOLE
        # string first then split, so encoded `..` (`%2E%2E`) and encoded
        # slashes carrying `..` (`a%2F..%2Fb`) both surface as a `..` segment.
        segs = urllib.parse.unquote(d).split("/")
        if any(seg in ("", ".", "..") for seg in segs[1:]):
            out[d] = {"ok": False, "error": "dot-segment in DOI"}
            continue
        enc = quote_doi_path(d)
        j = litrev_get(f"https://api.crossref.org/works/{enc}")
        time.sleep(0.06)  # CrossRef polite interval
        if j and "message" in j:
            m = j["message"]
            title = (m.get("title") or [""])[0]
            upd = [u.get("type", "") for u in (m.get("update-to") or [])]
            retracted = (
                any("retract" in t.lower() for t in upd)
                or str(m.get("subtype") or "").lower() == "retraction"
                or title.upper().startswith("RETRACTED")
            )
            out[d] = {
                "ok": True,
                "title": title,
                "year": crossref_year(m),
                "journal": (m.get("container-title") or [""])[0],
                "retracted": retracted,
                "registry": "crossref",
            }
            continue
        # CrossRef miss OR transient — doi.org is the authoritative resolver
        # across all registration agencies, so its verdict decides ok.
        code = litrev_head(f"https://doi.org/{enc}")
        if code is not None and 200 <= code < 400:
            out[d] = {"ok": True, "registry": "non-crossref", "retracted": None}
        elif code == 404:
            out[d] = {"ok": False}
        else:
            out[d] = {"ok": None, "error": "unverified (network)", "retracted": None}
    return out


def crossref_lookup(ref_string):
    """Find a DOI from a free-text citation (author/title/year). Returns the
    top CrossRef match as {doi, title, year, score} or None. Use when you
    have a citation's details but not its DOI — this is the alternative to
    guessing."""
    q = urllib.parse.quote(ref_string)
    j = litrev_get(f"https://api.crossref.org/works?query.bibliographic={q}&rows=1")
    items = (j or {}).get("message", {}).get("items", [])
    if not items:
        return None
    m = items[0]
    return {
        "doi": m.get("DOI"),
        "title": (m.get("title") or [""])[0],
        "year": crossref_year(m),
        "score": m.get("score"),
    }


def search_openalex(query, n=10, filters=""):
    """Search OpenAlex (open scholarly index, ~250M works). Returns up to n
    hits as [{doi, title, year, cited_by, venue, oa_url}]. `filters` is an
    OpenAlex filter string, e.g. 'from_publication_date:2022-01-01'."""
    q = urllib.parse.quote(query)
    flt = f"&filter={filters}" if filters else ""
    c = litrev_contact()
    mailto = f"&mailto={urllib.parse.quote(c)}" if c else ""
    j = litrev_get(
        f"https://api.openalex.org/works?search={q}&per-page={min(n, 25)}"
        f"&sort=cited_by_count:desc{flt}{mailto}"
    )
    out = []
    for w in (j or {}).get("results", [])[:n]:
        loc = w.get("primary_location") or {}
        venue = ((loc.get("source") or {}) or {}).get("display_name")
        out.append({
            "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
            "title": w.get("title"),
            "year": w.get("publication_year"),
            "cited_by": w.get("cited_by_count"),
            "venue": venue,
            "oa_url": (w.get("open_access") or {}).get("oa_url"),
        })
    return out


def expand_citations(doi, n_backward=50, n_forward=15):
    """One citation-graph step in both directions via OpenAlex.
    `references` is the backward step — the paper's own bibliography (outgoing
    citations), via `filter=cited_by:<id>`, sorted most-cited first.
    `cited_by` is the forward step — papers that cite this one (incoming
    citations), via `filter=cites:<id>`. Each entry is {doi, title, year,
    cited_by}. Three OpenAlex requests total; returns empty lists when the DOI
    is unknown to OpenAlex or the list endpoint is rate-limited."""
    c = litrev_contact()
    mailto = f"&mailto={urllib.parse.quote(c)}" if c else ""
    enc = quote_doi_path(doi)
    work = litrev_get(f"https://api.openalex.org/works/doi:{enc}?select=id{mailto}")
    work_id = ((work or {}).get("id") or "").rsplit("/", 1)[-1]
    if not work_id:
        return {"references": [], "cited_by": []}

    def _rows(results):
        out = []
        for w in results or []:
            out.append({
                "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                "title": w.get("title"),
                "year": w.get("publication_year"),
                "cited_by": w.get("cited_by_count"),
            })
        return out

    def _list(filter_expr, n):
        j = litrev_get(
            f"https://api.openalex.org/works?filter={filter_expr}"
            f"&select=doi,title,publication_year,cited_by_count"
            f"&sort=cited_by_count:desc&per-page={min(n, 100)}{mailto}"
        )
        return _rows((j or {}).get("results", []))

    return {
        "references": _list(f"cited_by:{work_id}", n_backward),
        "cited_by": _list(f"cites:{work_id}", n_forward),
    }


def extract_dois(text):
    """Pull every DOI-looking string from `text` (for feeding to verify_dois).
    HTML-decoded, balanced-paren SICI, `</`-truncated, markdown/punct-stripped."""
    decoded = html_decode(text)
    out = set()
    for m in re.findall(DOI_PATTERN, decoded):
        d = m.split("</")[0]
        if d.count("<") != d.count(">"):
            d = d.split("<")[0]
        d = re.sub(r"(?:\*\*|__|[_\]\*>`,;:])+$", "", d)
        if d.endswith("."):
            d = d[:-1]
        while d.endswith(")") and d.count("(") < d.count(")"):
            d = d[:-1]
        if len(d) > 8:
            out.add(d)
    return sorted(out)


def style_pass(draft):
    """Deterministic prose lint. Returns {ok, issues:[{code,note}]} where each
    code is one of EMDASH/HONEST/PROCNOTE/PARENDOI/LONGHEAD/FLATSTRUCT.

    No LLM call by design: drafts routinely quote web/paper-retrieved
    third-party text, and a free-text fix hint the agent is instructed to
    apply would be an indirect-injection channel. The deterministic regex
    codes are the load-bearing checks."""
    issues = []
    w = len(draft.split()) or 1
    em = draft.count("—")
    if em > 6 and 1000 * em / w > 8:
        issues.append({"code": "EMDASH",
                        "note": f"{em} em-dashes ({1000*em/w:.0f}/1kw); replace most with comma/colon/period, keep at most one per paragraph"})
    m = re.search(r"\b(the\s+|an?\s+)?honest(ly)?\s+(answer|summary|read|reading|look|perspective|assessment|appraisal|take|view)\b", draft, re.I)
    if m:
        issues.append({"code": "HONEST",
                        "note": f"{m.group(0)!r}: drop the framing, write the sentence it was guarding"})
    if re.search(r"(DOIs?\s+(were\s+)?verif|verified against (CrossRef|PubMed)|no retraction|current as of)", draft, re.I):
        issues.append({"code": "PROCNOTE",
                        "note": "process-narration line present; delete it"})
    if re.search(r"\]\(https://doi\.org/[^)\s]*\([^)\s]*\)", draft):
        issues.append({"code": "PARENDOI",
                        "note": "DOI href contains literal ( ); URL-encode as %28 %29 so the markdown link survives simpler renderers"})
    h2 = [ln for ln in draft.split("\n") if ln.startswith("## ")]
    long_h2 = [ln for ln in h2 if len(ln.split()) > 8]
    if len(long_h2) >= 2:
        issues.append({"code": "LONGHEAD",
                        "note": f"{len(long_h2)} headings read as sentences; shorten to <=6-word noun phrases"})
    if len(h2) >= 7 and not any(ln.startswith("### ") for ln in draft.split("\n")):
        issues.append({"code": "FLATSTRUCT",
                        "note": f"{len(h2)} top-level sections, no subsections; group related ## under a parent and demote to ###"})
    return {"ok": len(issues) == 0, "issues": issues}


# ── input helpers ────────────────────────────────────────────────────────────

def _read_input(path):
    """Read text from a file path, or '-' / None → stdin."""
    if path and path != "-":
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_verify_dois(args):
    if args.dois:
        dois = args.dois
    elif args.from_text:
        dois = extract_dois(_read_input(args.from_text))
    elif args.from_stdin:
        dois = extract_dois(sys.stdin.read())
    else:
        print("verify-dois: pass DOIs positionally, or --from-text FILE, or --from-stdin",
              file=sys.stderr)
        sys.exit(2)
    if not dois:
        print("verify-dois: no DOIs found to verify", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(verify_dois(dois), ensure_ascii=False, indent=2))


def cmd_crossref_lookup(args):
    print(json.dumps(crossref_lookup(args.ref), ensure_ascii=False, indent=2))


def cmd_search_openalex(args):
    print(json.dumps(search_openalex(args.query, n=args.n, filters=args.filters),
                     ensure_ascii=False, indent=2))


def cmd_expand_citations(args):
    print(json.dumps(expand_citations(args.doi, n_backward=args.n_backward,
                                      n_forward=args.n_forward),
                     ensure_ascii=False, indent=2))


def cmd_extract_dois(args):
    print(json.dumps(extract_dois(_read_input(args.file)), ensure_ascii=False, indent=2))


def cmd_style_pass(args):
    print(json.dumps(style_pass(_read_input(args.file)), ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="literature_review",
        description=("Stateless literature lookup + verification — search OpenAlex, "
                     "resolve/verify DOIs against CrossRef + doi.org, walk the "
                     "citation graph, lint review prose. Stdlib only, no LLM. "
                     "See SKILL.md for the synthesis workflow."),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("verify-dois",
                       help="resolve DOIs (CrossRef + doi.org fallback); catch fabrication")
    p.add_argument("dois", nargs="*", help="DOIs to verify (positional)")
    p.add_argument("--from-text", default=None, help="read a file, extract DOIs, verify")
    p.add_argument("--from-stdin", action="store_true", help="read stdin, extract DOIs, verify")
    p.set_defaults(func=cmd_verify_dois)

    p = sub.add_parser("crossref-lookup", help="free-text citation → DOI (CrossRef)")
    p.add_argument("ref", help="citation string (author/title/year)")
    p.set_defaults(func=cmd_crossref_lookup)

    p = sub.add_parser("search-openalex", help="search OpenAlex (~250M works)")
    p.add_argument("query")
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--filters", default="", help="OpenAlex filter, e.g. from_publication_date:2022-01-01")
    p.set_defaults(func=cmd_search_openalex)

    p = sub.add_parser("expand-citations", help="one citation-graph step, both directions")
    p.add_argument("doi")
    p.add_argument("--n-backward", type=int, default=50)
    p.add_argument("--n-forward", type=int, default=15)
    p.set_defaults(func=cmd_expand_citations)

    p = sub.add_parser("extract-dois", help="pull every DOI from a text file / stdin")
    p.add_argument("file", nargs="?", help="text file (default: stdin)")
    p.set_defaults(func=cmd_extract_dois)

    p = sub.add_parser("style-pass", help="deterministic prose lint (no LLM)")
    p.add_argument("file", nargs="?", help="markdown draft (default: stdin)")
    p.set_defaults(func=cmd_style_pass)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

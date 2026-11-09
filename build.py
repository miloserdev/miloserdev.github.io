#!/usr/bin/env python3
"""Build index.html from template.html and the profile README.

Source of truth: https://github.com/miloserdev/miloserdev (README.md).
Usage: python3 build.py [path/to/README.md]   (no arg = download from GitHub)
Stdlib only.
"""
import html, json, re, sys, urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/miloserdev/miloserdev/master/README.md"
ROOT = Path(__file__).parent


def inline(t):
    """Inline markdown (GFM-like): links, `code`, **bold**/__bold__, *em*/_em_.

    Code spans and links are stashed first so emphasis never touches their
    contents (URLs, snake_case inside backticks). Underscore emphasis follows
    GFM: it only opens/closes at word boundaries, so snake_case stays intact.
    """
    stash = []

    def keep(h):
        stash.append(h)
        return f"\x00{len(stash) - 1}\x00"

    t = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{html.escape(m[1], quote=False)}</code>"), t)

    def link(m):
        label, url = m[1], m[2]
        rel = ' rel="me"' if re.fullmatch(r"https://(github\.com|t\.me)/miloserdev/?", url) else ""
        return keep(f'<a href="{html.escape(url)}"{rel}>') + label + keep("</a>")

    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)", r"<strong>\1</strong>", t)
    t = re.sub(r"\*(?=[^\s*])(.+?)(?<=[^\s*])\*", r"<em>\1</em>", t)
    t = re.sub(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)", r"<em>\1</em>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m[1])], t)


def cell(t):
    """Table cell: inline markdown plus the only raw HTML we allow: <br> and <img src alt>."""
    out = []
    for part in re.split(r"(<br\s*/?>|<img\s[^>]*>)", t.strip(), flags=re.I):
        if re.fullmatch(r"<br\s*/?>", part, flags=re.I):
            out.append("<br>")
        elif part.lower().startswith("<img"):
            src = re.search(r'src\s*=\s*"([^"]+)"', part)
            alt = re.search(r'alt\s*=\s*"([^"]*)"', part)
            if not src or not src[1].startswith("https://"):
                continue
            if "jwt=" in src[1]:  # GitHub private-user-images links expire in minutes
                print(f"warning: skipped expiring image URL (jwt=...): {src[1][:70]}...", file=sys.stderr)
                continue
            out.append(f'<img src="{html.escape(src[1])}" alt="{html.escape(alt[1] if alt else "")}" loading="lazy">')
        else:
            out.append(inline(part))
    return "".join(out)


def split_row(ln):
    ln = ln.strip()
    ln = ln[1:] if ln.startswith("|") else ln
    ln = ln[:-1] if ln.endswith("|") and not ln.endswith("\\|") else ln
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", ln)]


def table(rows):
    cells = [split_row(r) for r in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)]  # separator
    cells = [r for r in cells if any(c for c in r)]  # empty header / blank rows
    cards = []
    for r in cells:
        inner = "\n".join(
            f'  <div class="{"shot" if c.lower().startswith("<img") else "txt"}">{h}</div>'
            for c in r if c for h in [cell(c)] if h)
        cards.append(f'<article class="card">\n{inner}\n</article>')
    return '<div class="projects">\n' + "\n".join(cards) + "\n</div>"


def split_sections(lines):
    head, secs, cur = [], [], None
    for ln in lines:
        if ln.startswith("## "):
            cur = [ln[3:].strip(), []]
            secs.append(cur)
        elif cur is None:
            head.append(ln)
        else:
            cur[1].append(ln)
    return head, secs


def blocks(lines, skills):
    """Render generic markdown subset: ###, paragraphs, lists, *meta* lines."""
    out, para, items = [], [], []

    def flush():
        nonlocal para, items
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para = []
        if items:
            out.append("<ul>\n" + "\n".join(f"  <li>{inline(i)}</li>" for i in items) + "\n</ul>")
            items = []

    tbl = []

    def flush_table():
        nonlocal tbl
        if tbl:
            out.append(table(tbl))
            tbl = []

    for ln in lines:
        s = ln.strip()
        if s.startswith("|"):
            flush()
            tbl.append(s)
            continue
        flush_table()
        if not s or re.fullmatch(r"-{3,}", s):
            flush()
        elif s.startswith("### "):
            flush()
            out.append(f"<h3>{inline(s[4:])}</h3>")
        elif s.startswith("- "):
            if para:
                flush()
            items.append(s[2:])
        elif re.fullmatch(r"(\*[^*].*\*|_[^_].*_)", s):
            flush()
            out.append(f'<p class="meta">{inline(s[1:-1])}</p>')
        else:
            para.append(s)
    flush()
    flush_table()
    return "\n".join(out)


def skills_block(lines, collected):
    out, name = [], None
    for ln in lines:
        s = ln.strip()
        m = re.fullmatch(r"\*\*(.+)\*\*", s)
        if m:
            name = m[1]
        elif s and name:
            chips = re.findall(r"`([^`]+)`", s)
            collected.extend(chips)
            lis = "\n".join(f"<li>{html.escape(c, quote=False)}</li>" for c in chips)
            out.append(f'<dt>{html.escape(name, quote=False)}</dt>\n<dd>\n<ul class="chips">\n{lis}\n</ul>\n</dd>')
            name = None
    return "<dl>\n" + "\n".join(out) + "\n</dl>"


def indent(s, n):
    return "\n".join((" " * n + l) if l else l for l in s.split("\n"))


def build(md):
    head, secs = split_sections(md.splitlines())
    h1 = next(l[2:].strip() for l in head if l.startswith("# "))
    rest = [l for l in head if not l.startswith("# ")]
    paras = [l.strip() for l in rest if l.strip()]
    sub, links = paras[0], paras[1] if len(paras) > 1 else ""
    links_html = " ".join(
        f'<a href="{u}" rel="me">{html.escape(t)}</a>' for t, u in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", links))

    collected, parts = [], [
        f'<header>\n  <h1>{html.escape(h1)}</h1>\n  <p class="sub">{inline(sub)}</p>\n  <p class="links">\n    {links_html}\n  </p>\n</header>']
    for title, body in secs:
        inner = skills_block(body, collected) if title == "Skills" else blocks(body, collected)
        parts.append(f"<section>\n  <h2>{html.escape(title)}</h2>\n{indent(inner, 2)}\n</section>")
    body_html = indent("\n\n".join(parts), 4)

    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    knows = json.dumps(list(dict.fromkeys(collected)), ensure_ascii=False)
    return tpl.replace("{{KNOWS_ABOUT}}", knows).replace("{{BODY}}", body_html)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        md = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(URL, timeout=30) as r:
            md = r.read().decode("utf-8")
    (ROOT / "index.html").write_text(build(md), encoding="utf-8")

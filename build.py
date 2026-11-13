#!/usr/bin/env python3
"""Build index.html (manpage-style resume) from template.html and the profile README.

Source of truth: https://github.com/miloserdev/miloserdev (README.md).
Usage: python3 build.py [path/to/README.md]   (no arg = download from GitHub)
Stdlib only.
"""
import datetime, html, json, re, sys, urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/miloserdev/miloserdev/master/README.md"
ROOT = Path(__file__).parent


def inline(t):
    """Inline markdown: links, `code`, **bold**, *em*/_em_. Code spans and links are
    stashed first so emphasis never touches URLs or snake_case inside backticks."""
    stash = []

    def keep(h):
        stash.append(h)
        return f"\x00{len(stash) - 1}\x00"

    t = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{html.escape(m[1], quote=False)}</code>"), t)

    def link(m):
        rel = ' rel="me"' if re.fullmatch(r"https://(github\.com|t\.me)/miloserdev/?", m[2]) else ""
        return keep(f'<a href="{html.escape(m[2])}"{rel}>') + m[1] + keep("</a>")

    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)", r"<strong>\1</strong>", t)
    t = re.sub(r"\*(?=[^\s*])(.+?)(?<=[^\s*])\*", r"<em>\1</em>", t)
    t = re.sub(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)", r"<em>\1</em>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m[1])], t)


def split_row(ln):
    ln = ln.strip()
    ln = ln[1:] if ln.startswith("|") else ln
    ln = ln[:-1] if ln.endswith("|") and not ln.endswith("\\|") else ln
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", ln)]


def table(rows):
    """Projects table -> <dl>. Screenshots are dropped (terminal look); the first
    link of the text cell becomes <dt>, the rest <dd>."""
    cells = [split_row(r) for r in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)]
    out = []
    for r in cells:
        txt = " ".join(c for c in r if c and not c.lower().startswith("<img"))
        if not txt:
            continue
        m = re.match(r"\s*(?:\*\*)?\[([^\]]+)\]\(([^)\s]+)\)(?:\*\*)?\s*(.*)", txt, re.S)
        if m:
            name, url, rest = m.groups()
            rest = re.sub(r"^[—–-]\s*", "", rest.strip())
            dt = f'<a href="{html.escape(url)}"><strong>{html.escape(name.lower(), quote=False)}</strong></a>'
        else:
            dt, rest = None, txt
        rest = "<br>\n    ".join(inline(p) for p in re.split(r"<br\s*/?>", rest, flags=re.I) if p.strip())
        if dt:
            out.append(f"<dt>{dt}</dt>")
        out.append(f"<dd>{rest}</dd>")
    return "<dl>\n  " + "\n  ".join(out) + "\n</dl>"


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


def blocks(lines):
    """Markdown subset: ###, paragraphs, lists, *meta* lines, tables."""
    out, para, items, tbl = [], [], [], []

    def flush():
        nonlocal para, items
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para = []
        if items:
            out.append("<ul>\n" + "\n".join(f"  <li>{inline(i)}</li>" for i in items) + "\n</ul>")
            items = []

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
            out.append(f'<h3>{inline(s[4:])}</h3>')
        elif s.startswith("- "):
            if para:
                flush()
            items.append(s[2:])
        elif re.fullmatch(r"(\*[^*].*\*|_[^_].*_)", s):
            flush()
            out.append(f"<p>{inline(s)}</p>")
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
            dd = ", ".join(f"<code>{html.escape(c, quote=False)}</code>" for c in chips)
            out.append(f"<dt>{html.escape(name, quote=False)}</dt>\n<dd>{dd}</dd>")
            name = None
    return "<dl>\n" + "\n".join(out) + "\n</dl>"


# README section title -> manpage section title
ALIASES = {"About": "Description", "Contact": "Author"}
COMMAND = "λ"                      # command name shown in SYNOPSIS
SITE_URL = "https://miloser.dev/"
ALTERNATE_NAMES = ["Милосердев", "miloserdev"]
SYNOPSIS_SKIP = {"DESCRIPTION"}        # sections not listed as subcommands
# skill chip (substring) -> man page for SEE ALSO; listed only if the skill is in the README
MAN_REFS = [("VPP", "vpp", 8), ("eBPF", "bpf", 2), ("Suricata", "suricata", 1),
            ("QEMU", "qemu", 1), ("GDB", "gdb", 1)]


def indent(s, n):
    return "\n".join((" " * n + l) if l else l for l in s.split("\n"))


def build(md):
    head, secs = split_sections(md.splitlines())
    name = next(l[2:].strip() for l in head if l.startswith("# "))
    paras = [l.strip() for l in head if l.strip() and not l.startswith("# ")]
    sub = paras[0]
    link_list = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", paras[1]) if len(paras) > 1 else []
    man = f"{name.lower()}(1)"

    # NAME line, man-style: "senior C engineer, low-level ..." (lowercase lead word, "·" -> ",")
    short = re.sub(r"^([A-Z])(?=[a-z])", lambda m: m[1].lower(), sub) #.replace(" · ", ", ")

    collected, subcmds = [], []
    parts = [
        f'<h2 id="NAME">NAME</h2>\n<h1 style="margin: 0">{html.escape(name.lower(), quote=False)}</h1>\n'
        f'<h4 style="margin: 0">{inline(short)}</h4>',
    ]
    for title, body in secs:
        inner = skills_block(body, collected) if title == "Skills" else blocks(body)
        title = ALIASES.get(title, title)
        sid = re.sub(r"[^A-Z0-9]+", "-", title.upper()).strip("-")
        parts.append(f'<h2 id="{sid}">{html.escape(title.upper(), quote=False)}</h2>\n{inner}')
        if sid not in SYNOPSIS_SKIP:
            subcmds.append((sid, title.lower()))

    # SYNOPSIS: "about [--github=user] [--telegram=@user]" + "about a | b | c"
    def opt(t, u):
        val = u.rstrip("/").rsplit("/", 1)[-1]
        val = "@" + val if "t.me/" in u else val
        return (f'[<strong>--{html.escape(t.lower())}</strong>='
                f'<var><a href="{html.escape(u)}" rel="me">{html.escape(val)}</a></var>]')

    cmd = f"<strong>{COMMAND}</strong>"
    syn = (f'<h2 id="SYNOPSIS">SYNOPSIS</h2>\n<p>\n  {cmd} ' + " ".join(opt(t, u) for t, u in link_list)
           + f'<br>\n  {cmd} ' + " | ".join(f'<var><a href="#{i}">{n}</a></var>' for i, n in subcmds) + "\n</p>")
    parts.insert(1, syn)

    # SEE ALSO: man pages for tools mentioned in Skills
    refs = [f'<span class="man-ref">{n}<span class="s">({sec})</span></span>'
            for key, n, sec in MAN_REFS if any(key.lower() in c.lower() for c in collected)]
    if refs:
        parts.append('<h2 id="SEE-ALSO">SEE ALSO</h2>\n<p>' + ",\n  ".join(refs) + "</p>")
    body_html = indent("\n\n".join(parts), 2)

    esc = lambda s: html.escape(re.sub(r"[`*_]", "", s))
    sub_plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", sub)
    plain = lambda s: re.sub(r"\s+", " ", re.sub(r"[`*_]|\]\([^)]*\)|\[", "", s)).strip()
    about = next((" ".join(l.strip() for l in body if l.strip()).split("  ")[0]
                  for t, body in secs if t == "About"), sub_plain)
    # ProfilePage with the Person as mainEntity (https://developers.google.com/search/docs/appearance/structured-data/profile-page)
    data = {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "url": SITE_URL,
        "mainEntity": {
            "@type": "Person",
            "@id": SITE_URL + "#me",
            "name": name,
            "alternateName": ALTERNATE_NAMES,
            "url": SITE_URL,
            "jobTitle": plain(sub_plain),
            "description": plain(about),
            "knowsAbout": list(dict.fromkeys(collected)),
            "sameAs": [u for _, u in link_list],
        },
    }
    # json.dumps escapes quotes; "<" is escaped so README text can't close the <script> block
    jsonld = json.dumps(data, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    rep = {
        "{{MAN}}": esc(man),
        "{{NAME}}": esc(name),
        "{{TITLE}}": esc(sub_plain),
        "{{DESCRIPTION}}": esc(sub_plain),
        "{{DATE}}": datetime.date.today().strftime("%B %Y"),
        "{{JSONLD}}": jsonld,
        "{{BODY}}": body_html,
    }
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    for k, v in rep.items():
        tpl = tpl.replace(k, v)
    return tpl


if __name__ == "__main__":
    if len(sys.argv) > 1:
        md = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(URL, timeout=30) as r:
            md = r.read().decode("utf-8")
    (ROOT / "index.html").write_text(build(md), encoding="utf-8")

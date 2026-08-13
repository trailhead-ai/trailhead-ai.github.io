#!/usr/bin/env python3
"""Static checks for the trailhead site: dead names, link integrity, CSS classes."""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
failures = []
notes = []

html_files = sorted(ROOT.rglob("*.html"))
html_files = [p for p in html_files if ".git" not in p.parts and ".claude" not in p.parts]

# ---- collect the classes site.css actually defines ----
css_path = ROOT / "assets" / "site.css"
css_text = css_path.read_text(encoding="utf-8")
defined = set(re.findall(r"\.([A-Za-z][\w-]*)", css_text))


class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.classes = set()
        self.links = []
        self.ids = set()
        self.title = None
        self._in_title = False
        self.stack = []
        self.unclosed = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("class"):
            self.classes.update(d["class"].split())
        if d.get("id"):
            self.ids.add(d["id"])
        for key in ("href", "src"):
            if d.get(key):
                self.links.append(d[key])
        if tag == "title":
            self._in_title = True
        if tag not in ("meta", "link", "br", "img", "hr", "input", "path", "source"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in ("meta", "link", "br", "img", "hr", "input", "path", "source"):
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.unclosed.append(self.stack.pop())
            if self.stack:
                self.stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data


pages = {}
for path in html_files:
    raw = path.read_text(encoding="utf-8")
    visible = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    c = Collector()
    c.feed(visible)
    pages[path] = (c, visible)
    rel = path.relative_to(ROOT)

    if not c.title:
        failures.append(f"{rel}: missing <title>")
    if c.stack:
        failures.append(f"{rel}: unclosed tags {c.stack}")
    if c.unclosed:
        failures.append(f"{rel}: mismatched tags {c.unclosed}")

    # Dead tool names must not appear where this site writes tool names:
    # inside <code> or as a heading. A bare word-boundary match is not enough --
    # "forge" and "landing" are also ordinary English verbs ("cannot forge a
    # review", "a reader landing on the old record") and must stay allowed.
    name_slots = re.findall(r"<code>(.*?)</code>", visible, flags=re.DOTALL)
    name_slots += re.findall(r"<h[123][^>]*>(.*?)</h[123]>", visible, flags=re.DOTALL)
    for dead in ("forge", "landing"):
        for slot in name_slots:
            if re.search(rf"(?i)\b{dead}\b", slot):
                failures.append(
                    f'{rel}: dead tool name "{dead}" used as a name in "{slot.strip()[:60]}"'
                )
                break

    # every class used must exist in the stylesheet
    unknown = sorted(cl for cl in c.classes if cl not in defined)
    if unknown:
        failures.append(f"{rel}: classes not defined in site.css: {unknown}")

# ---- link integrity ----
for path, (c, _) in pages.items():
    rel = path.relative_to(ROOT)
    for link in c.links:
        if link.startswith(("http://", "https://", "mailto:", "data:", "#")):
            continue
        target, _, frag = link.partition("#")
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        if resolved.is_dir():
            resolved = resolved / "index.html"
        if not resolved.exists():
            failures.append(f"{rel}: broken link -> {link}")
            continue
        if frag and resolved.suffix == ".html":
            tc, _ = pages.get(resolved, (None, None))
            if tc and frag not in tc.ids:
                failures.append(f"{rel}: fragment #{frag} not found in {target or rel}")

# ---- landing page must show all six tools ----
index = ROOT / "index.html"
if index in pages:
    _, visible = pages[index]
    cards = len(re.findall(r'<article class="tool">', visible))
    if cards != 6:
        failures.append(f"index.html: expected 6 tool cards, found {cards}")
    for tool in ("lore", "camp", "craft", "portage", "ranger", "outpost"):
        if not re.search(rf"<h3>{tool}</h3>", visible):
            failures.append(f"index.html: missing tool card for {tool}")

# ---- every docs page must be reachable from the sidebar ----
docs = sorted((ROOT / "docs").glob("*.html"))
nav_targets = set()
if (ROOT / "docs" / "index.html") in pages:
    c, _ = pages[ROOT / "docs" / "index.html"]
    nav_targets = {l for l in c.links if l.endswith(".html")}
for d in docs:
    if d.name not in nav_targets and d.name != "index.html":
        notes.append(f"docs/{d.name} is not linked from the docs sidebar")

print(f"checked {len(html_files)} html files, {len(defined)} css classes defined\n")
for n in notes:
    print(f"NOTE: {n}")
if failures:
    print()
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)
print("all checks passed")

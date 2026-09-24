#!/usr/bin/env python3
"""Structural checks for the site.

Three checks, matching exactly what the colophon claims is automated:

  1. malformed HTML       - container elements open and close in order
  2. duplicate element ID - an id appears at most once per page
  3. internal links       - every local href/src resolves to a file that
                            exists, and every fragment resolves to an id
                            that exists on the target page

Nothing here judges content. These checks catch the class of error that
survives a careless edit and that a reader would otherwise hit first.

Standard library only, so it runs identically in CI and on a laptop:

    python scripts/check_site.py
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag

ROOT = Path(__file__).resolve().parent.parent

# Elements that never have a closing tag.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# Elements whose end tag HTML5 allows you to omit. Tracking these on a
# stack produces false alarms, so nesting is not enforced for them.
OPTIONAL_END = {
    "p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody",
    "tfoot", "option", "optgroup", "colgroup", "rp", "rt",
}


class PageParser(HTMLParser):
    """Collects structure errors, ids, and outbound references."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []
        self.ids: dict[str, int] = {}
        self.duplicate_ids: list[tuple[str, int, int]] = []
        self.refs: list[tuple[str, str, int]] = []  # (attr, value, line)

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        attrd = {k: v for k, v in attrs if v is not None}

        if "id" in attrd:
            ident = attrd["id"]
            if ident in self.ids:
                self.duplicate_ids.append((ident, self.ids[ident], line))
            else:
                self.ids[ident] = line

        for attr in ("href", "src"):
            if attr in attrd:
                self.refs.append((attr, attrd[attr], line))

        if tag not in VOID and tag not in OPTIONAL_END:
            self.stack.append((tag, line))

    def handle_startendtag(self, tag, attrs):
        # Self-closing form, e.g. <img />. Record attributes, skip the stack.
        saved = self.stack[:]
        self.handle_starttag(tag, attrs)
        self.stack = saved

    def handle_endtag(self, tag):
        line = self.getpos()[0]
        if tag in VOID or tag in OPTIONAL_END:
            return
        if not self.stack:
            self.errors.append(f"line {line}: </{tag}> with nothing open")
            return
        if self.stack[-1][0] == tag:
            self.stack.pop()
            return
        # Tolerate an unclosed optional-ish element only if the tag we are
        # closing is somewhere on the stack; otherwise it is a stray end tag.
        for depth in range(len(self.stack) - 1, -1, -1):
            if self.stack[depth][0] == tag:
                unclosed = [f"<{t}> (line {ln})" for t, ln in self.stack[depth + 1:]]
                self.errors.append(
                    f"line {line}: </{tag}> closes an element opened on line "
                    f"{self.stack[depth][1]}, but these are still open: "
                    + ", ".join(unclosed)
                )
                del self.stack[depth:]
                return
        self.errors.append(f"line {line}: </{tag}> with no matching <{tag}>")

    def finish(self) -> None:
        for tag, line in self.stack:
            self.errors.append(f"line {line}: <{tag}> is never closed")


def page_url(path: Path) -> str:
    """The URL a file is served at, as GitHub Pages resolves it."""
    rel = path.relative_to(ROOT).as_posix()
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def resolve(ref: str, page: Path) -> Path | None:
    """Map a local href/src to a file on disk, or None if it cannot exist."""
    ref = unquote(ref)
    if ref.startswith("/"):
        target = ROOT / ref.lstrip("/")
    else:
        target = page.parent / ref
    try:
        target = target.resolve()
    except OSError:
        return None
    if target.is_dir():
        target = target / "index.html"
    elif not target.suffix:
        candidate = Path(str(target) + "/index.html")
        if candidate.exists():
            target = candidate
    return target


def main() -> int:
    pages = sorted(
        p for p in ROOT.rglob("*.html")
        if ".git" not in p.parts and "node_modules" not in p.parts
    )
    if not pages:
        print("no HTML pages found - refusing to pass vacuously")
        return 1

    parsed: dict[Path, PageParser] = {}
    failures = 0

    print(f"checking {len(pages)} pages\n")

    # Pass 1: parse every page. Structure and duplicate ids are page-local.
    for page in pages:
        parser = PageParser()
        parser.feed(page.read_text(encoding="utf-8"))
        parser.close()
        parser.finish()
        parsed[page] = parser

        rel = page.relative_to(ROOT).as_posix()
        for err in parser.errors:
            print(f"FAIL {rel}: malformed HTML: {err}")
            failures += 1
        for ident, first, second in parser.duplicate_ids:
            print(
                f"FAIL {rel}: duplicate id {ident!r} "
                f"(lines {first} and {second})"
            )
            failures += 1

    # Pass 2: links, which need every page's ids to be known first.
    for page in pages:
        rel = page.relative_to(ROOT).as_posix()
        for attr, value, line in parsed[page].refs:
            value = value.strip()
            if not value or value.startswith(
                ("http://", "https://", "mailto:", "data:", "//", "tel:", "javascript:")
            ):
                continue

            path_part, fragment = urldefrag(value)

            if not path_part:
                # Same-page fragment. "#" alone is a legitimate no-op.
                if fragment and fragment not in parsed[page].ids:
                    print(
                        f"FAIL {rel} line {line}: {attr}=\"{value}\" "
                        f"points at an id that does not exist on this page"
                    )
                    failures += 1
                continue

            target = resolve(path_part, page)
            if target is None or not target.exists():
                print(
                    f"FAIL {rel} line {line}: {attr}=\"{value}\" "
                    f"does not resolve to a file"
                )
                failures += 1
                continue

            if fragment and target in parsed and fragment not in parsed[target].ids:
                print(
                    f"FAIL {rel} line {line}: {attr}=\"{value}\" resolves to "
                    f"{page_url(target)} but that page has no id {fragment!r}"
                )
                failures += 1

    total_ids = sum(len(p.ids) for p in parsed.values())
    total_refs = sum(len(p.refs) for p in parsed.values())
    print(
        f"\n{len(pages)} pages, {total_ids} ids, {total_refs} references checked"
    )

    if failures:
        print(f"{failures} problem(s) found")
        return 1
    print("no problems found")
    return 0


if __name__ == "__main__":
    sys.exit(main())

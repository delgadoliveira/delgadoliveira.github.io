# Alan Delgado Portfolio

[![Site checks](https://github.com/delgadoliveira/delgadoliveira.github.io/actions/workflows/checks.yml/badge.svg)](https://github.com/delgadoliveira/delgadoliveira.github.io/actions/workflows/checks.yml)
[![Refresh reading list](https://github.com/delgadoliveira/delgadoliveira.github.io/actions/workflows/update-papers.yml/badge.svg)](https://github.com/delgadoliveira/delgadoliveira.github.io/actions/workflows/update-papers.yml)

A dependency-free, responsive portfolio and writing site served by GitHub Pages
at [delgadoliveira.github.io](https://delgadoliveira.github.io).

What is automated and what is judged is documented page by page in
[`/colophon/`](https://delgadoliveira.github.io/colophon/).

## Deployment

The repository is the site. Pushing to `main` publishes it via
**Settings → Pages → Deploy from a branch** (`main`, `/ (root)`).

## Preview locally

The pages reference `/assets/...` by absolute path, so opening a file directly
with `file://` will load the markup without its stylesheet. Serve the directory
instead:

```bash
python -m http.server 8000
# then open http://127.0.0.1:8000/
```

No build step and no dependencies.

## Checks

Two checks run on every push, and both are standard-library Python, so they run
the same way locally as in CI:

```bash
python scripts/check_site.py      # HTML structure, duplicate ids, internal links
python scripts/check_reading.py   # curated papers still carry editorial notes
```

`check_site.py` walks every page and fails on container elements that never
close, on an `id` used twice on one page, and on any local `href`/`src` that no
longer resolves — including fragments that point at an id which does not exist
on the target page.

`check_reading.py` defends the boundary the reading list is built on: metadata
is fetched, but the `establishes` / `unsettled` notes on curated papers are
written by hand. It fails if a curated paper loses a note, if a note is too
short to be a real assessment, or if an automatically selected paper acquires
one.

Both were tested against deliberately broken input before being relied on. A
check that cannot fail is not evidence.

## Add a new article

1. Copy `writing/evidence-stack/` to `writing/<new-slug>/`.
2. Replace the article title, description, publication date, metadata, and body.
3. Add a card to `writing/index.html` and the homepage writing section.
4. Add an item to `writing/feed.xml`.
5. Run `python scripts/check_site.py` — a new page is the most likely source of
   a broken internal link or a duplicated `id` copied from the template.

Each article should end with the public-methodology disclaimer and avoid internal product names,
metrics, thresholds, screenshots, traffic numbers, and unreleased feature details.

## Content sources

- GitHub profile and public repositories: `github.com/delgadoliveira`
- Research identity: ORCID `0000-0003-4260-5844`
- AI agents course: `delgadoliveira/topicos-especiais-ia`

Before publishing, review the professional summary and location language to ensure it matches
the level of detail you want to share publicly.

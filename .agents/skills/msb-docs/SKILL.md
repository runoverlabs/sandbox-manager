---
name: msb-docs
description: "The documentation site and the README's pictures: docs/content Markdown with title/section/order/description front matter, docs/build.py's deliberate Markdown subset and template.html, the SEO and agent outputs (canonical, Open Graph, JSON-LD, sitemap.xml, llms.txt, a .md copy per page), what --check refuses including an msbctl subcommand with no Commands-page section, and scripts/screenshots (make.sh driving real msbctl in tmux against an invented HOME, render.py drawing the SVG). Use when editing or adding a page, when --check fails on a link, anchor or missing section, or when a screen a screenshot shows has changed."
---

# Docs

Detail carved out of `AGENTS.md`, which keeps only what has to hold in
every session. Repo-specific throughout; the facts here are verified against
msb 0.7.6 and re-checked on 0.7.7.

- `docs/` — the documentation site (GitHub Pages, `.github/workflows/docs.yml`). Pages are Markdown in `docs/content/` with `title`/`section`/`order` front matter; `docs/build.py` is a stdlib-only converter for a deliberate Markdown subset (extend it rather than adding a generator), plus `template.html` and `assets/` (terminal theme, light/dark/auto, client-side search over an index it writes as a script so the site works off `file://`). `CHANGELOG.md` is rendered as a page, never copied; the logo comes from the repo-level `assets/`. The same build writes the SEO/agent outputs (canonical, Open Graph, JSON-LD, `sitemap.xml`, `llms.txt`, `llms-full.txt`, a `.md` copy of each page), all derived from the pages and `--site-url`, so a new page needs only its front matter — including the `description`, which `--check` requires. `--check` (run by `check.sh`) fails on a broken internal link or anchor and on any `msbctl` subcommand without a `### \`msbctl <name>\`` section on the Commands page. **A user-visible change updates the relevant page in the same PR**, like its changelog line.
- `assets/` — the logo: `msb-manager-mark-dotmatrix-dark.svg` (for dark grounds, also readable on light; the README's header) and `msb-manager-icon.svg`.
- `scripts/screenshots/` — `make.sh` regenerates `docs/assets/screenshots/*.svg` (used by the README): the real `msbctl`/`msb-picker` in a fixed-size tmux against an invented HOME (`world.py`), a fake `bin/msb` and a `bin/msbctl` wrapper that skips only the `/dev/kvm` preflight; `render.py` turns the captured grid into an SVG terminal (fixed cells, box lines drawn as strokes, docs palette). Needs tmux and fzf. Re-run it when a screen it shows changes; never hand-edit the SVGs or put real names, hosts or tokens in `world.py`.

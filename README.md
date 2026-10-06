# paper-readout

Turn an academic PDF into a compact bilingual annotated reading page with the OpenAI Responses API.

## What it produces

- paper-level overview: research question, motivation, method, contributions, findings, limitations
- selected important passages only
- English excerpt + Traditional Chinese translation
- AI annotation and "why it matters"
- page reference and importance score
- static HTML with a 3+/4+/5 importance filter
- fuller passages (usually 3–6 consecutive sentences) with bilingual key-phrase highlights
- LaTeX equations rendered with KaTeX (pinned CDN assets; requires internet access)
- figure guides with original figure labels, PDF page references, bilingual captions, and how-to-read explanations
- important tables transcribed into HTML tables, with bilingual captions, reading guides, and table notes
- a glossary of uncommon terms, abbreviations, and paper-specific meanings, with plain-language explanations and PDF page references

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Put your API key in `.env`:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.6-terra
OPENAI_REASONING=high
```

Terra is the default because it is a good fit for paper comprehension. Reasoning defaults to `high`; override it with `medium`, `xhigh`, or `max` when needed.

## Use

```bash
python annotate.py path/to/paper.pdf
```

For more reasoning:

```bash
python annotate.py paper.pdf --reasoning xhigh
python annotate.py paper.pdf --reasoning max
```

Output:

```text
output/pdf-<first-24-sha256-digits>/
├── paper.json
└── paper.html
```

All reading pages share `output/assets/style.css` and
`output/assets/glossary.js`. Keep the `assets/` directory with the collection
when moving or sharing it.

The ID is computed from the PDF's bytes, independently of its filename, title,
or model response. Re-running the exact same PDF updates the same JSON/HTML and
published URL. Different PDF bytes produce separate entries, including different
versions or re-exported copies of the same paper. The full SHA-256 and original
filename are saved in `paper.json` under `source`.

The model extracts this paper's DOI and arXiv ID only when confirmed in the PDF;
these appear as labels and original-paper links, and do not affect the output ID.
You can supply them explicitly when needed:

```bash
uv run python annotate.py paper.pdf --doi "10.1234/example"
uv run python annotate.py paper.pdf --arxiv-id "2307.08691v1"
```

Old JSON files without identifiers still render and publish normally.

Open `paper.html` in a browser.

## Public reading library (one command)

With Cloudflare Pages configured, the same command generates the annotation,
rebuilds a library homepage for all saved papers, publishes it, and prints the
homepage and current paper URLs:

```bash
uv run python annotate.py path/to/paper.pdf
```

One-time setup (requires a Cloudflare account and Node.js/npm):

```bash
npx --yes wrangler@4 login
npx --yes wrangler@4 pages project create YOUR_PROJECT_NAME --production-branch main
```

Choose a unique lowercase project name, then add it to `.env`:

```env
CLOUDFLARE_PAGES_PROJECT=YOUR_PROJECT_NAME
```

Your homepage is normally `https://YOUR_PROJECT_NAME.pages.dev/`, with each paper
at `/pdf-FINGERPRINT/paper.html`. If Cloudflare assigns a different domain or you use
a custom domain, also set `CLOUDFLARE_PAGES_URL=https://YOUR_ACTUAL_DOMAIN`.
See [Cloudflare's Direct Upload documentation](https://developers.cloudflare.com/pages/get-started/direct-upload/).

Each publication fetches the current cloud `library.json`, merges this computer's
local annotations, and rebuilds the complete website in a temporary directory.
The public manifest stores the generated paper data so the next computer can
retain every existing page without synchronising local `output/` directories.
The PDF itself is not uploaded. Wrangler reuses unchanged uploaded assets.

Two computers can publish **in turn** to the same Pages project. Wait for one
publication to finish before starting the next; simultaneous publications are
not supported. Removing a local paper does not remove it from the website.
The small `output/.publish-state.json` records what this computer last published,
so an unchanged old local annotation does not overwrite a newer cloud annotation.
New annotations explicitly replace the same PDF ID, including on publication retry.
If an unfamiliar local copy conflicts with the cloud copy, publication stops;
choose the local copy explicitly with `uv run python publish.py --replace PAPER_ID`.

To remove a paper from the website, use its ID from the URL or output folder:

```bash
uv run python publish.py --delete pdf-FINGERPRINT
# Multiple papers in one publication:
uv run python publish.py --delete pdf-FIRST --delete pdf-SECOND
```

This removes the paper from the list and current deployment while keeping local
files. The cloud manifest retains only a deletion marker for that ID, so stale
copies on either computer cannot add it back during ordinary publication. Both
computers must use the updated publisher. To restore it explicitly, regenerate
the same PDF or run `uv run python publish.py --replace PAPER_ID` with a local copy.
Failed deletions can be retried with `uv run python publish.py`.
An older failed publication cannot undo a deletion completed afterwards by the
other computer; issue a fresh `--replace` or regenerate to restore that paper.

The compact homepage shows the annotation update date and time (YYYY-MM-DD HH:mm)
in Taiwan time (UTC+8), using the generation-completion timestamp saved in
`paper.json` under `generation.generated_at`. The most recently generated
annotations appear first. Republishing, moving files, or restoring a saved copy
does not change this timestamp; generating a new annotation does. Legacy cloud
entries retain their existing recorded times; legacy local files without this
field fall back to the JSON modification time until regenerated.

The first publication after upgrading must run on the computer with all papers
currently on the old HTML-only site. Afterwards, either computer can publish its
own subset. Use the stable production or custom domain in `CLOUDFLARE_PAGES_URL`,
not a deployment hash URL. Cloud read failures stop publication and retain local
files. The manifest is subject to Pages' 25 MiB per-file limit.

If publishing fails, the new local JSON and HTML are kept and the command exits
with an error. Retry publishing without paying for another annotation request:

```bash
uv run python publish.py
# For a custom output collection:
uv run python publish.py --out path/to/output
```

Leave `CLOUDFLARE_PAGES_PROJECT` empty to keep generating locally, or use
`--no-publish` for a single local run. Login and project creation are needed only
once; subsequent annotation runs deploy automatically.

## Tests

Install development dependencies and the test browser once:

```bash
uv sync
uv run playwright install chromium
```

Run all Python and browser tests with one command:

```bash
uv run python -m unittest discover -v
```

Browser tests use generated local HTML and block external requests. API tests use
mock responses. To reuse an installed Edge browser instead of downloading Chromium,
set `TEST_BROWSER_CHANNEL=msedge` (PowerShell: `$env:TEST_BROWSER_CHANNEL = "msedge"`).

## Rebuild HTML

To rebuild an existing JSON file's HTML and stylesheet without calling the API:

```bash
python generate.py output/pdf-FINGERPRINT/paper.json
# Reuse the collection's shared assets:
uv run python generate.py output/pdf-FINGERPRINT/paper.json --assets output/assets
```

Each block may contain `en_highlights` and `zh_highlights`: arrays of exact
substrings of `en` and `zh`. These render as highlights; older JSON files without
them still work. Text is HTML-escaped, so model output cannot inject HTML.
Use `\( ... \)` for inline math and `\[ ... \]` for display math in text fields
(double the backslashes inside JSON strings). Highlight an entire formula,
including its delimiters, rather than part of it. Dollar signs remain plain text.
If KaTeX cannot load or parse an expression, the formula remains readable as text.

Longer excerpts, highlights, LaTeX transcription, figure/table guides, and the glossary require regenerating the
annotations with `annotate.py`; rebuilding HTML alone does not enrich old JSON.

### Glossary

The API returns a paper-level `glossary` array in the same annotation request.
Each entry contains `term` (original spelling), `zh` (Chinese name), `full_name`
(the abbreviation's expansion, or an empty string), `definition` (a plain-language
explanation), `paper_usage` (the meaning and role in this paper), and `page`
(the 1-based PDF page defining or illustrating the usage, or 0 if uncertain).

Entries focus on uncommon technical terms, abbreviations, and ordinary words with
special meanings in the paper. Unconfirmed expansions are left empty and explained
in `paper_usage`. Glossary entries supply the explanations shown from the reading
annotations. Missing or empty glossaries are omitted, so older JSON files remain
compatible.

Each excerpt block lists its matching glossary entries in a compact "本段名詞" row
inside its reading annotations, once per entry. Matching checks terms, full names, and Chinese names in
the passage, translation, annotations, and visual explanations. Hover over a term
to show its explanation nearby; moving into the popup keeps it open, and leaving
closes it. Clicking (or pressing Enter) keeps it open for touch and keyboard use;
close it with Escape or a click outside. Matching is case
sensitive, prefers longer names, avoids partial English words, and skips formulas.
Existing highlights are preserved. Rebuild HTML with `generate.py` to enable this
for existing JSON. Keep the generated CSS/JS at the paths referenced by the HTML;
annotation and publication use one shared `assets/` directory.

### Figure and table guides

Each selected passage can include `figures` and `tables` arrays. Guides appear
below that passage and follow its importance filter. Each important figure or
table is attached once, to the most relevant passage; older JSON without these
arrays still renders normally.

Both types include `label` (the original figure/table number), `page` (the 1-based
PDF page containing the visual, or 0 if uncertain), `caption_en`, `caption_zh`,
`explanation` (what it demonstrates), and `reading_tip` (how to read it).
Reading tips explain where to start, what axes/symbols/metrics mean, what to
compare, and how to interpret the result. Use the figure label and page to
consult the original PDF.

Tables additionally contain `headers`, `rows` (arrays of strings), and `notes`.
The API returns these directly within `paper.json` in the same annotation request.
Column order, values, units, missing-value symbols, and relevant footnotes are
preserved; multi-level headers are flattened with their group names. Unreadable
cells are marked `無法辨識`. If the table structure cannot be transcribed reliably,
the arrays are empty and `notes` explains why. Row widths are validated against
the headers. Important numerical comparisons should still be checked in the PDF.

Set `OPENAI_DETAIL=low`, `auto`, or `high` in `.env` to choose the default PDF
detail level. The default is `high` for dense diagrams, tables, and tiny text.
The `--detail` argument overrides this setting.
To reduce PDF image token usage:

```bash
python annotate.py paper.pdf --detail low
```

## Design choices

After completion, the terminal shows total elapsed time, including PDF upload,
the API response, cleanup, and JSON/HTML output.

New annotations store the API-reported model and token usage in `paper.json` under
`generation`. The webpage displays the model and input/output/total token counts
below the title, alongside the requested REASONING and DETAIL values.
Output tokens are also broken down into reasoning and other output (which can
include formatting tokens). Both are already included in output and total counts.
Missing reasoning details are shown as unavailable. Cached-input details remain
available in JSON. Older JSON without this metadata omits the row.

The model selects only passages worth revisiting instead of translating every paragraph. `paper.json` is the durable data layer; `generate.py` is deliberately plain stdlib HTML generation so the page can change without re-running the API.

Current MVP intentionally skips Zotero integration, RAG/vector databases, figure extraction, and writing annotations back into the PDF.

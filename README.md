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
output/<paper-name>/
├── paper.json
├── paper.html
└── style.css
```

Open `paper.html` in a browser.

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
python generate.py output/2307.08691v1/paper.json
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
for existing JSON; keep the generated `glossary.js` beside the HTML and stylesheet.

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
Output tokens include reasoning tokens; cached input and reasoning
breakdowns remain available in JSON. Older JSON without this metadata omits the row.

The model selects only passages worth revisiting instead of translating every paragraph. `paper.json` is the durable data layer; `generate.py` is deliberately plain stdlib HTML generation so the page can change without re-running the API.

Current MVP intentionally skips Zotero integration, RAG/vector databases, figure extraction, and writing annotations back into the PDF.

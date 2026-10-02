# paper-readout

Turn an academic PDF into a compact bilingual annotated reading page with the OpenAI Responses API.

## What it produces

- paper-level overview: research question, motivation, method, contributions, findings, limitations
- selected important passages only
- English excerpt + Traditional Chinese translation
- AI annotation and "why it matters"
- page reference and importance score
- static HTML with a 3+/4+/5 importance filter

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

For dense diagrams or tiny text:

```bash
python annotate.py paper.pdf --detail high
```

The default is `--detail low` to reduce PDF image token usage.

## Design choices

The model selects only passages worth revisiting instead of translating every paragraph. `paper.json` is the durable data layer; `generate.py` is deliberately plain stdlib HTML generation so the page can change without re-running the API.

Current MVP intentionally skips Zotero integration, RAG/vector databases, figure extraction, and writing annotations back into the PDF.

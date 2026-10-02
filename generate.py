#!/usr/bin/env python3
import argparse
import html
import json
from pathlib import Path

LABELS = {
    "problem": "研究缺口",
    "contribution": "貢獻",
    "concept": "核心概念",
    "method": "方法",
    "result": "結果",
    "limitation": "限制",
}


def esc(value) -> str:
    return html.escape(str(value or ""))


def list_items(items: list[str]) -> str:
    return "".join(f"<li>{esc(item)}</li>" for item in items)


def render_html(paper: dict, out: Path) -> None:
    meta = paper["meta"]
    overview = paper["overview"]
    authors = ", ".join(meta.get("authors", []))

    sections_html = []
    for section in paper.get("sections", []):
        blocks = []
        for block in section.get("blocks", []):
            kind = block["kind"]
            importance = int(block["importance"])
            page = int(block.get("page", 0))
            page_label = f"p. {page}" if page else "page ?"
            blocks.append(f"""
<article class="pair" data-importance="{importance}" data-kind="{esc(kind)}">
  <div class="source">
    <div class="meta-row"><span class="tag tag-{esc(kind)}">{esc(LABELS.get(kind, kind))}</span><span>{esc(page_label)}</span><span>重要度 {importance}/5</span></div>
    <blockquote>{esc(block["en"])}</blockquote>
    <p class="translation">{esc(block["zh"])}</p>
  </div>
  <aside class="annotation">
    <h3>這段在做什麼</h3>
    <p>{esc(block["annotation"])}</p>
    <h3>為什麼值得看</h3>
    <p>{esc(block["why_it_matters"])}</p>
  </aside>
</article>""")
        sections_html.append(f"""
<section>
  <div class="section-head">
    <h2>{esc(section["title"])}</h2>
    <p>{esc(section["summary_zh"])}</p>
  </div>
  {"".join(blocks)}
</section>""")

    doc = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(meta["title"])}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
<header class="hero">
  <p class="eyebrow">AI paper readout</p>
  <h1>{esc(meta["title"])}</h1>
  <p>{esc(authors)}</p>
  <p>{esc(meta.get("venue"))} · {esc(meta.get("year"))}</p>
</header>

<main>
<section class="overview">
  <div class="one-line"><strong>一句話：</strong>{esc(overview["one_line"])}</div>
  <div class="overview-grid">
    <div><h2>研究問題</h2><p>{esc(overview["research_question"])}</p></div>
    <div><h2>動機</h2><p>{esc(overview["motivation"])}</p></div>
    <div><h2>方法</h2><p>{esc(overview["method"])}</p></div>
    <div><h2>主要貢獻</h2><ul>{list_items(overview["contributions"])}</ul></div>
    <div><h2>主要結果</h2><ul>{list_items(overview["main_findings"])}</ul></div>
    <div><h2>限制</h2><ul>{list_items(overview["limitations"])}</ul></div>
  </div>
</section>

<div class="toolbar" role="group" aria-label="重要度篩選">
  <span>顯示重要度：</span>
  <button data-min="3">3+</button>
  <button data-min="4" class="active">4+</button>
  <button data-min="5">5</button>
</div>

{"".join(sections_html)}
</main>
<script>
const buttons = [...document.querySelectorAll('[data-min]')];
function filter(min) {{
  document.querySelectorAll('.pair').forEach(el => {{
    el.hidden = Number(el.dataset.importance) < min;
  }});
  buttons.forEach(b => b.classList.toggle('active', Number(b.dataset.min) === min));
}}
buttons.forEach(b => b.addEventListener('click', () => filter(Number(b.dataset.min))));
filter(4);
</script>
</body>
</html>"""
    out.write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render paper.json as HTML.")
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    out = args.out or args.json_file.with_suffix(".html")
    paper = json.loads(args.json_file.read_text(encoding="utf-8"))
    render_html(paper, out)
    print(out)


if __name__ == "__main__":
    main()

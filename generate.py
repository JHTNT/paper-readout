#!/usr/bin/env python3
import argparse
import html
import json
import re
import shutil
from pathlib import Path


def esc(value) -> str:
    return html.escape(str(value or ""))


def highlighted(value: str, highlights: list[str]) -> str:
    # Keep math intact so highlighting cannot split a KaTeX expression.
    parts = re.split(r"(\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])", value)
    phrases = sorted({s for s in highlights if s and s in value}, key=len, reverse=True)
    pattern = "|".join(re.escape(s) for s in phrases)
    rendered = []
    for index, part in enumerate(parts):
        if index % 2:
            rendered.append(
                f"<mark>{esc(part)}</mark>" if part in phrases else esc(part)
            )
        elif pattern:
            chunks = re.split(f"({pattern})", part)
            rendered.append(
                "".join(
                    f"<mark>{esc(chunk)}</mark>" if i % 2 else esc(chunk)
                    for i, chunk in enumerate(chunks)
                )
            )
        else:
            rendered.append(esc(part))
    return "".join(rendered)


def list_items(items: list[str]) -> str:
    return "".join(f"<li>{esc(item)}</li>" for item in items)


def render_visual_guides(block: dict) -> str:
    guides = []
    for kind in ("figures", "tables"):
        for guide in block.get(kind, []):
            label = esc(guide["label"])
            page = int(guide.get("page", 0))
            location = f"原始 PDF 第 {page} 頁" if page else "原始 PDF 頁碼待確認"
            captions = (
                f'<span lang="en">{esc(guide["caption_en"])}</span>'
                f"<span>{esc(guide['caption_zh'])}</span>"
            )
            content = f'<p class="visual-caption">{captions}</p>'
            if kind == "tables" and guide.get("rows"):
                headers = "".join(
                    f'<th scope="col">{esc(cell)}</th>' for cell in guide["headers"]
                )
                rows = "".join(
                    "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
                    for row in guide["rows"]
                )
                content = f"""<div class="table-scroll" tabindex="0" role="region" aria-label="{label} 資料表">
  <table class="data-table">
    <caption class="visual-caption">{captions}</caption>
    <thead><tr>{headers}</tr></thead><tbody>{rows}</tbody>
  </table>
</div>"""
            notes = (
                f'<p class="table-notes"><strong>表格註記：</strong>{esc(guide["notes"])}</p>'
                if guide.get("notes")
                else ""
            )
            guides.append(f"""<section class="visual-guide">
  <h3>{label}<span>{location}</span></h3>
  {content}
  {notes}
  <div class="visual-explanation">
    <div><h4>這張{"圖" if kind == "figures" else "表"}在說什麼</h4><p>{esc(guide["explanation"])}</p></div>
    <div><h4>怎麼看</h4><p>{esc(guide["reading_tip"])}</p></div>
  </div>
</section>""")
    if not guides:
        return ""
    return '<div class="visual-guides">' + "".join(guides) + "</div>"


def render_glossary(entries: list[dict]) -> str:
    if not entries:
        return ""
    items = []
    for entry in entries:
        page = int(entry.get("page", 0))
        location = f"原始 PDF 第 {page} 頁" if page else "原始 PDF 頁碼待確認"
        full_name = (
            f'<p class="term-full-name">全名：<span lang="en">{esc(entry["full_name"])}</span></p>'
            if entry.get("full_name")
            else ""
        )
        items.append(f"""<div class="glossary-entry">
  <dt><span lang="en">{esc(entry["term"])}</span><span class="term-zh">{esc(entry["zh"])}</span></dt>
  <dd>
    {full_name}
    <p class="term-label">白話解釋</p><p class="term-text">{esc(entry["definition"])}</p>
    <p class="term-label">本文用法</p><p class="term-text">{esc(entry["paper_usage"])}</p>
    <p class="term-page">{location}</p>
  </dd>
</div>""")
    return f"""<section class="glossary" id="glossary" aria-labelledby="glossary-heading">
  <h2 id="glossary-heading">名詞解釋</h2>
  <p class="glossary-intro">專有名詞、縮寫與本文中的特殊用法，共 {len(entries)} 個詞條。</p>
  <dl class="glossary-list">{"".join(items)}</dl>
</section>"""


def render_generation(generation: dict) -> str:
    if not generation:
        return ""
    items = [f"模型：{esc(generation['model'])}"]
    for key in ("reasoning", "detail"):
        if key in generation:
            items.append(f"{key.upper()}：{esc(generation[key])}")
    usage = generation.get("usage")
    if usage is not None:
        for key, label in (
            ("input_tokens", "輸入"),
            ("output_tokens", "輸出"),
            ("total_tokens", "總計"),
        ):
            items.append(f"{label}：{int(usage[key]):,} tokens")
    else:
        items.append("Token 用量：未提供")
    return f'<p aria-label="生成資訊">{" · ".join(items)}</p>'


def render_html(paper: dict, out: Path) -> None:
    meta = paper["meta"]
    overview = paper["overview"]
    authors = ", ".join(meta.get("authors", []))
    glossary_html = render_glossary(paper.get("glossary", []))
    glossary_link = (
        '<a class="overview-link glossary-link" href="#glossary">名詞解釋 <span aria-hidden="true">↗</span></a>'
        if glossary_html
        else ""
    )

    sections_html = []
    contents = []
    for index, section in enumerate(paper.get("sections", []), start=1):
        contents.append(
            f'<li><a href="#section-{index}"><span class="nav-number" aria-hidden="true">{index:02d}</span>'
            f"<span>{esc(section['title'])}</span></a></li>"
        )
        blocks = []
        for block in section.get("blocks", []):
            importance = int(block["importance"])
            page = int(block.get("page", 0))
            page_label = f"p. {page}" if page else "page ?"
            blocks.append(f"""
<article class="pair" data-importance="{importance}">
  <div class="source">
    <div class="meta-row"><span>{esc(page_label)}</span><span>重要度 {importance}/5</span></div>
    <div class="original">
      <p class="passage-label">原文 <span lang="en">SOURCE</span></p>
      <blockquote lang="en">{highlighted(block["en"], block.get("en_highlights", []))}</blockquote>
    </div>
    <div class="translated">
      <p class="passage-label">繁體中文 <span lang="en">TRANSLATION</span></p>
      <p class="translation">{highlighted(block["zh"], block.get("zh_highlights", []))}</p>
    </div>
  </div>
  <aside class="annotation">
    <p class="passage-label">閱讀批註 <span lang="en">NOTES</span></p>
    <h3>這段在做什麼</h3>
    <p>{esc(block["annotation"])}</p>
    <h3>為什麼值得看</h3>
    <p>{esc(block["why_it_matters"])}</p>
  </aside>
  {render_visual_guides(block)}
</article>""")
        sections_html.append(f"""
<section class="reading-section" id="section-{index}" aria-labelledby="heading-{index}">
  <div class="section-head">
    <span class="section-number" aria-hidden="true">{index:02d}</span>
    <h2 id="heading-{index}">{esc(section["title"])}</h2>
    <p>{esc(section["summary_zh"])}</p>
  </div>
  <p class="empty-section" hidden>此節沒有符合條件的摘錄，請調低重要度篩選。</p>
  {"".join(blocks)}
</section>""")

    doc = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(meta["title"])}</title>
  <link rel="stylesheet" href="style.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.css">
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/contrib/auto-render.min.js"
    onload="renderMathInElement(document.querySelector('main'), {{delimiters: [{{left: '\\\\[', right: '\\\\]', display: true}}, {{left: '\\\\(', right: '\\\\)', display: false}}], throwOnError: false, trust: false}})"></script>
</head>
<body>
<a class="skip-link" href="#overview">跳至閱讀內容</a>
<div class="workspace">
<aside class="sidebar">
  <nav class="contents" aria-label="章節目錄">
    <a class="overview-link" href="#overview">論文總覽 <span aria-hidden="true">↗</span></a>
    {glossary_link}
    <details open>
      <summary>章節導覽 <span>{len(contents)} 個章節</span></summary>
      <ol>{"".join(contents)}</ol>
    </details>
  </nav>
  <p class="sidebar-note">循著章節精讀，對照原文與批註。<br>用重要度篩選調整閱讀深度。</p>
</aside>

<main>
<header class="hero" id="top">
  <p class="eyebrow">RESEARCH NOTE <span>雙語閱讀 · 重點批註</span></p>
  <h1>{esc(meta["title"])}</h1>
  <div class="paper-meta"><span>{esc(authors)}</span><span>{esc(meta.get("venue"))}</span><span>{esc(meta.get("year"))}</span></div>
  {render_generation(paper.get("generation", {}))}
</header>

<section class="overview" id="overview" aria-label="論文總覽">
  <div class="one-line"><strong>一句話掌握<span lang="en">THE TAKEAWAY</span></strong><p>{esc(overview["one_line"])}</p></div>
  <div class="overview-grid">
    <div><h2>研究問題</h2><p>{esc(overview["research_question"])}</p></div>
    <div><h2>動機</h2><p>{esc(overview["motivation"])}</p></div>
    <div><h2>方法</h2><p>{esc(overview["method"])}</p></div>
    <div><h2>主要貢獻</h2><ul>{list_items(overview["contributions"])}</ul></div>
    <div><h2>主要結果</h2><ul>{list_items(overview["main_findings"])}</ul></div>
    <div><h2>限制</h2><ul>{list_items(overview["limitations"])}</ul></div>
  </div>
</section>

<div class="toolbar">
  <div class="filter-controls" role="group" aria-label="重要度篩選">
    <span class="filter-label">重要度</span>
    <button type="button" data-min="3" aria-pressed="false">3+ 補充</button>
    <button type="button" data-min="4" aria-pressed="true" class="active">4+ 重點</button>
    <button type="button" data-min="5" aria-pressed="false">5 核心</button>
  </div>
  <span class="readout-count" role="status" aria-live="polite"></span>
  <a class="back-to-top" href="#top">回到頂端 ↑</a>
</div>

{"".join(sections_html)}
{glossary_html}
</main>
</div>
<script>
const contents = document.querySelector('.contents details');
const desktop = window.matchMedia('(min-width: 1100px)');
contents.open = desktop.matches;
desktop.addEventListener('change', event => {{ contents.open = event.matches; }});
const buttons = [...document.querySelectorAll('[data-min]')];
const pairs = [...document.querySelectorAll('.pair')];
function filter(min) {{
  pairs.forEach(el => {{
    el.hidden = Number(el.dataset.importance) < min;
  }});
  buttons.forEach(b => {{
    const active = Number(b.dataset.min) === min;
    b.classList.toggle('active', active);
    b.setAttribute('aria-pressed', String(active));
  }});
  document.querySelector('.readout-count').textContent = `${{pairs.filter(el => !el.hidden).length}} / ${{pairs.length}} 段`;
  document.querySelectorAll('.reading-section').forEach(section => {{
    section.querySelector('.empty-section').hidden = [...section.querySelectorAll('.pair')].some(el => !el.hidden);
  }});
}}
buttons.forEach(b => b.addEventListener('click', () => filter(Number(b.dataset.min))));
filter(4);
</script>
</body>
</html>"""
    out.write_text(doc, encoding="utf-8")
    stylesheet = Path(__file__).with_name("style.css")
    target = out.with_name("style.css")
    if stylesheet.resolve() != target.resolve():
        shutil.copy2(stylesheet, target)


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

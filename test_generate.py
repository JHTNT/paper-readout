import json
from pathlib import Path
from tempfile import TemporaryDirectory

from annotate import Block, Paper
from generate import esc, highlighted, render_html


def test_readout():
    value = '<script>alert("x")</script> A+B A+B 中文重點'
    marked = highlighted(value, ["<script>", "A+B", "中文重點", "", "absent"])
    assert "<script>" not in marked
    assert "<mark>&lt;script&gt;</mark>" in marked
    assert marked.count("<mark>A+B</mark>") == 2
    assert "<mark>中文重點</mark>" in marked
    assert marked.replace("<mark>", "").replace("</mark>", "") == esc(value)
    assert (
        highlighted("long claim", ["long", "long claim"]) == "<mark>long claim</mark>"
    )
    math = r"\(x < y\) and \[L = m + \log(\ell)\]"
    assert highlighted(math, ["x", "log"]) == esc(math)
    assert highlighted(r"\(x\)", [r"\(x\)"]) == r"<mark>\(x\)</mark>"

    block = {
        "page": 1,
        "kind": "method",
        "importance": 4,
        "en": "Original passage.",
        "zh": "原文翻譯。",
        "annotation": "說明",
        "why_it_matters": "意義",
    }
    assert Block.model_validate(block).en_highlights == []
    paper = {
        "meta": {"title": "Test", "authors": [], "venue": "", "year": 2026},
        "overview": {
            "one_line": math,
            "research_question": "",
            "motivation": "",
            "method": "",
            "contributions": [],
            "main_findings": [],
            "limitations": [],
        },
        "sections": [{"title": "Section", "summary_zh": "", "blocks": [block]}],
    }
    with TemporaryDirectory() as directory:
        out = Path(directory) / "paper.html"
        render_html(paper, out)
        assert "<blockquote>Original passage.</blockquote>" in out.read_text("utf-8")
        block.update(
            en=math + "\nKey claim.",
            zh="重要結論。",
            en_highlights=["Key claim."],
            zh_highlights=["重要結論"],
        )
        Paper.model_validate_json(json.dumps(paper))
        render_html(paper, out)
        doc = out.read_text("utf-8")
        assert "<mark>Key claim.</mark>" in doc
        assert "<mark>重要結論</mark>" in doc
        assert esc(math) in doc
        assert "left: '\\\\('" in doc and "left: '\\\\['" in doc
        assert "throwOnError: false, trust: false" in doc
        assert (out.parent / "style.css").read_bytes() == Path("style.css").read_bytes()


if __name__ == "__main__":
    test_readout()
    print("Readout checks passed.")

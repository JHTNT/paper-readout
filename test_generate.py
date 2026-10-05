import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from annotate import Block, Paper
from generate import esc, highlighted, render_html
from test_support import HtmlTestCase, example_paper


class HighlightTests(unittest.TestCase):
    def test_escaping_repeated_and_overlapping_phrases(self):
        value = '<script>alert("x")</script> A+B A+B 中文重點'
        marked = highlighted(value, ["<script>", "A+B", "中文重點", "", "absent"])
        self.assertNotIn("<script>", marked)
        self.assertIn("<mark>&lt;script&gt;</mark>", marked)
        self.assertEqual(marked.count("<mark>A+B</mark>"), 2)
        self.assertIn("<mark>中文重點</mark>", marked)
        self.assertEqual(
            marked.replace("<mark>", "").replace("</mark>", ""), esc(value)
        )
        self.assertEqual(
            highlighted("long claim", ["long", "long claim"]),
            "<mark>long claim</mark>",
        )

    def test_math_is_highlighted_only_as_a_whole(self):
        math = r"\(x < y\) and \[L = m + \log(\ell)\]"
        self.assertEqual(highlighted(math, ["x", "log"]), esc(math))
        self.assertEqual(highlighted(r"\(x\)", [r"\(x\)"]), r"<mark>\(x\)</mark>")


class ReadoutTests(HtmlTestCase):
    def setUp(self):
        self.paper = example_paper()
        self.block = self.paper["sections"][0]["blocks"][0]

    def test_legacy_passage_without_highlights(self):
        self.assertEqual(Block.model_validate(self.block).en_highlights, [])
        doc = self.render(self.paper)
        self.assertIn(f'<blockquote lang="en">{self.block["en"]}</blockquote>', doc)

    def test_bilingual_highlights_math_and_navigation(self):
        math = r"\(x < y\) and \[L = m + \log(\ell)\]"
        self.block.update(
            en=math + "\nKey claim.",
            zh="重要結論。",
            en_highlights=["Key claim."],
            zh_highlights=["重要結論"],
        )
        Paper.model_validate(self.paper)
        doc = self.render(self.paper)
        self.assertIn('href="#section-1"', doc)
        self.assertIn('id="section-1" aria-labelledby="heading-1"', doc)
        self.assertIn('data-min="4" aria-pressed="true"', doc)
        self.assertIn('class="empty-section" hidden', doc)
        self.assertIn("<mark>Key claim.</mark>", doc)
        self.assertIn("<mark>重要結論</mark>", doc)
        self.assertIn(esc(math), doc)
        self.assertIn("left: '\\\\('", doc)
        self.assertIn("left: '\\\\['", doc)
        self.assertIn("throwOnError: false, trust: false", doc)

    def test_exported_assets_match_sources(self):
        with TemporaryDirectory() as directory:
            out = Path(directory) / "paper.html"
            render_html(self.paper, out)
            for name in ("style.css", "glossary.js"):
                with self.subTest(asset=name):
                    self.assertEqual(
                        out.with_name(name).read_bytes(),
                        Path(__file__).with_name(name).read_bytes(),
                    )


if __name__ == "__main__":
    unittest.main()

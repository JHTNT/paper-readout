import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from annotate import GlossaryEntry, Paper
from generate import esc, render_glossary, render_html
from test_visual_guides import example_paper


class GlossaryTests(unittest.TestCase):
    def setUp(self):
        self.paper = example_paper()

    def render(self):
        with TemporaryDirectory() as directory:
            out = Path(directory) / "paper.html"
            render_html(self.paper, out)
            return out.read_text("utf-8")

    def test_glossary_has_navigation_and_is_outside_filtered_passages(self):
        Paper.model_validate(self.paper)
        doc = self.render()
        self.assertIn('href="#glossary"', doc)
        self.assertIn('aria-labelledby="glossary-heading"', doc)
        self.assertIn('class="glossary" id="glossary"', doc)
        self.assertGreater(doc.index('id="glossary"'), doc.rindex("</article>"))
        self.assertEqual(doc.count('class="reading-section"'), 1)
        self.assertEqual(doc.count('class="pair"'), 1)
        self.assertIn("白話解釋", doc)
        self.assertIn("本文用法", doc)
        for field in ("term", "zh", "full_name", "definition", "paper_usage"):
            self.assertIn(self.paper["glossary"][0][field], doc)
        self.assertIn("原始 PDF 第 7 頁", doc)

    def test_missing_and_empty_glossaries_preserve_old_pages(self):
        self.paper.pop("glossary")
        for include_empty in (False, True):
            with self.subTest(include_empty=include_empty):
                if include_empty:
                    self.paper["glossary"] = []
                self.assertEqual(Paper.model_validate(self.paper).glossary, [])
                doc = self.render()
                self.assertNotIn('href="#glossary"', doc)
                self.assertNotIn('id="glossary"', doc)
                self.assertIn('class="reading-section"', doc)

    def test_contextual_term_without_expansion_and_unknown_page(self):
        entry = {
            "term": "horizon",
            "zh": "預測範圍",
            "full_name": "",
            "definition": "模型向未來預測的步數，例如預測接下來三個時間點。",
            "paper_usage": "本文用這個詞指預測步數，不是一般語意的地平線。",
            "page": 0,
        }
        GlossaryEntry.model_validate(entry)
        rendered = render_glossary([entry])
        self.assertIn(entry["paper_usage"], rendered)
        self.assertIn("原始 PDF 頁碼待確認", rendered)
        self.assertNotIn("全名：", rendered)
        with self.assertRaises(ValidationError):
            GlossaryEntry.model_validate({**entry, "page": -1})

    def test_glossary_escapes_text_and_preserves_math(self):
        hostile = '<img src=x onerror="alert(1)"> & ' + r"\(x < y\)"
        entry = {
            field: hostile
            for field in ("term", "zh", "full_name", "definition", "paper_usage")
        }
        entry["page"] = 1
        rendered = render_glossary([entry])
        self.assertNotIn("<img", rendered)
        self.assertEqual(rendered.count(esc(hostile)), 5)


if __name__ == "__main__":
    unittest.main()

import unittest

from pydantic import ValidationError

from annotate import GlossaryEntry, Paper
from generate import esc, render_glossary
from test_support import HtmlTestCase, example_paper


class GlossaryTests(HtmlTestCase):
    def setUp(self):
        self.paper = example_paper()

    def test_glossary_data_and_popup_are_available(self):
        Paper.model_validate(self.paper)
        doc = self.render(self.paper)
        self.assertIn('<template id="glossary-data">', doc)
        self.assertIn('id="glossary-term-0"', doc)
        self.assertIn('id="term-panel"', doc)
        self.assertIn('src="glossary.js"', doc)
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
                doc = self.render(self.paper)
                self.assertNotIn('id="glossary-data"', doc)
                self.assertNotIn('id="term-panel"', doc)
                self.assertNotIn('src="glossary.js"', doc)
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

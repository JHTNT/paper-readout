import json
import unittest

from openai import OpenAI
from pydantic import ValidationError

try:
    import httpx2 as httpx  # OpenAI SDK 3.x
except ImportError:
    import httpx  # OpenAI SDK 2.x

from annotate import Block, Paper, TableGuide
from generate import esc, render_visual_guides
from test_support import HtmlTestCase, example_paper


class VisualGuideTests(HtmlTestCase):
    def setUp(self):
        self.paper = example_paper()
        self.block = self.paper["sections"][0]["blocks"][0]

    def test_legacy_blocks(self):
        del self.block["figures"], self.block["tables"]
        block = Block.model_validate(self.block)
        self.assertEqual(block.figures, [])
        self.assertEqual(block.tables, [])
        self.assertEqual(render_visual_guides(self.block), "")

    def test_guides_stay_inside_filtered_passage(self):
        paper = Paper.model_validate(self.paper).model_dump(mode="json")
        doc = self.render(paper)
        article = doc.split('<article class="pair" data-importance="4">', 1)[1].split(
            "</article>", 1
        )[0]
        self.assertIn("Figure 2(b)", article)
        self.assertIn("原始 PDF 第 5 頁", article)
        self.assertIn("原始 PDF 第 7 頁", article)
        self.assertIn("p. 6", article)
        self.assertIn("這張圖在說什麼", article)
        self.assertIn("這張表在說什麼", article)
        self.assertEqual(article.count("<h4>怎麼看</h4>"), 2)
        self.assertIn(self.block["tables"][0]["reading_tip"], article)
        self.assertIn('<th scope="col">MAE ↓</th>', article)
        self.assertIn("<td>0.120 ± 0.010</td>", article)
        self.assertIn("<td>—</td>", article)
        self.assertIn("<td>0</td>", article)

    def test_all_visual_text_is_escaped_and_math_is_preserved(self):
        hostile = '<img src=x onerror="alert(1)"> & ' + r"\(x < y\)"
        for group in ("figures", "tables"):
            guide = self.block[group][0]
            for field in (
                "label",
                "caption_en",
                "caption_zh",
                "explanation",
                "reading_tip",
            ):
                guide[field] = hostile
        table = self.block["tables"][0]
        table.update(headers=[hostile], rows=[[hostile]], notes=hostile)
        rendered = render_visual_guides(self.block)
        self.assertNotIn("<img", rendered)
        self.assertEqual(rendered.count(esc(hostile)), 14)

    def test_unreadable_table_keeps_guide_and_reason(self):
        table = self.block["tables"][0]
        table.update(
            headers=[], rows=[], notes="無法可靠辨識欄列，請對照原始 PDF。", page=0
        )
        TableGuide.model_validate(table)
        rendered = render_visual_guides(self.block)
        self.assertIn(table["notes"], rendered)
        self.assertIn("原始 PDF 頁碼待確認", rendered)
        self.assertIn("Table 1", rendered)
        self.assertNotIn("<table", rendered)
        with self.assertRaises(ValidationError):
            TableGuide.model_validate({**table, "notes": " "})

    def test_invalid_table_shape_is_rejected(self):
        table = self.block["tables"][0]
        for rows in ([["missing cells"]], [["a", "b", "c", "extra"]]):
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                TableGuide.model_validate({**table, "rows": rows})

    def test_responses_sdk_structured_output_roundtrip(self):
        def respond(request):
            schema = json.loads(request.content)["text"]["format"]
            self.assertTrue(schema["strict"])
            self.assertIn("glossary", schema["schema"]["required"])
            defs = schema["schema"]["$defs"]
            self.assertIn("figures", defs["Block"]["required"])
            self.assertIn("tables", defs["Block"]["required"])
            self.assertFalse(defs["TableGuide"]["additionalProperties"])
            self.assertFalse(defs["GlossaryEntry"]["additionalProperties"])
            return httpx.Response(
                200,
                json={
                    "id": "resp_test",
                    "object": "response",
                    "created_at": 0,
                    "model": "test",
                    "output": [
                        {
                            "id": "msg_test",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(self.paper),
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                },
            )

        with OpenAI(
            api_key="test",
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        ) as client:
            result = client.responses.parse(
                model="test", input="test", text_format=Paper
            )
        self.assertEqual(
            result.output_parsed.sections[0].blocks[0].tables[0].rows[1][1],
            "0.095 ± 0.008",
        )
        self.assertEqual(
            result.output_parsed.glossary[0].full_name, "Mean Absolute Error"
        )


if __name__ == "__main__":
    unittest.main()

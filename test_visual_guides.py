import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openai import OpenAI
from pydantic import ValidationError

try:
    import httpx2 as httpx  # OpenAI SDK 3.x
except ImportError:
    import httpx  # OpenAI SDK 2.x

from annotate import Block, Paper, TableGuide
from generate import esc, render_html, render_visual_guides


def example_paper():
    figure = {
        "label": "Figure 2(b)",
        "page": 5,
        "caption_en": "Architecture of the proposed model.",
        "caption_zh": "所提模型的架構。",
        "explanation": "模型先編碼輸入，再融合特徵以產生預測。",
        "reading_tip": "從左往右看：箭頭表示資料流，先找輸入，再對照編碼器與輸出。",
    }
    table = {
        **figure,
        "label": "Table 1",
        "page": 7,
        "caption_en": "Comparison under the same evaluation protocol.",
        "caption_zh": "相同評估條件下的方法比較。",
        "explanation": "本文方法在相同資料切分下的誤差較小。",
        "reading_tip": "先看 MAE ↓ 欄，數值越低越好，再比較 Baseline 與 Ours；± 表示標準差。",
        "headers": ["Method", "MAE ↓", "Time (ms)"],
        "rows": [["Baseline", "0.120 ± 0.010", "—"], ["Ours", "0.095 ± 0.008", "0"]],
        "notes": "所有方法使用相同資料切分；— 為原表未提供數值。",
    }
    return {
        "meta": {"title": "圖表導讀示例", "authors": [], "venue": "", "year": 2026},
        "overview": {
            "one_line": "對照原始 PDF 的圖號與頁碼，搭配表格理解方法與結果。",
            "research_question": "如何改善預測誤差？",
            "motivation": "比較模型設計與實驗結果。",
            "method": "編碼輸入後融合特徵。",
            "contributions": [],
            "main_findings": [],
            "limitations": [],
        },
        "glossary": [
            {
                "term": "MAE",
                "zh": "平均絕對誤差",
                "full_name": "Mean Absolute Error",
                "definition": "把每筆預測與答案的差距取絕對值，再算平均；越小表示誤差越小。",
                "paper_usage": "本文用 MAE 比較各模型在相同測試資料上的預測誤差。",
                "page": 7,
            }
        ],
        "sections": [
            {
                "title": "方法與結果",
                "summary_zh": "圖表閱讀示例。",
                "blocks": [
                    {
                        "page": 6,
                        "kind": "result",
                        "importance": 4,
                        "en": "Our model achieves lower error under the same evaluation protocol.",
                        "zh": "在相同的評估條件下，我們的模型達到更低的誤差。",
                        "annotation": "這一段將模型設計連接到實驗結果。",
                        "why_it_matters": "比較時需要確認資料切分與評估條件一致。",
                        "figures": [figure],
                        "tables": [table],
                    }
                ],
            }
        ],
    }


class VisualGuideTests(unittest.TestCase):
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
        with TemporaryDirectory() as directory:
            out = Path(directory) / "paper.html"
            render_html(paper, out)
            doc = out.read_text("utf-8")
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

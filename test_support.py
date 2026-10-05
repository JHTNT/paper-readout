import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from generate import render_html


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


class HtmlTestCase(unittest.TestCase):
    def render(self, paper):
        with TemporaryDirectory() as directory:
            out = Path(directory) / "paper.html"
            render_html(paper, out)
            return out.read_text("utf-8")

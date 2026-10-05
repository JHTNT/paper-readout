#!/usr/bin/env python3
import argparse
import json
import logging
import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

from generate import render_html

load_dotenv(Path(__file__).with_name(".env"))
logger = logging.getLogger(__name__)


class Kind(str, Enum):
    problem = "problem"
    contribution = "contribution"
    concept = "concept"
    method = "method"
    result = "result"
    limitation = "limitation"


class Meta(BaseModel):
    title: str
    authors: list[str]
    venue: str
    year: int


class Overview(BaseModel):
    one_line: str
    research_question: str
    motivation: str
    method: str
    contributions: list[str]
    main_findings: list[str]
    limitations: list[str]


class VisualGuide(BaseModel):
    label: str = Field(
        description="Exact figure/table label, e.g. Figure 2(b) or Table 1."
    )
    page: int = Field(
        ge=0,
        description="1-based PDF page index of the figure/table itself; 0 if uncertain.",
    )
    caption_en: str = Field(description="Original caption from the PDF.")
    caption_zh: str = Field(
        description="Traditional Chinese translation of the caption."
    )
    explanation: str = Field(description="Explain what this figure/table demonstrates.")
    reading_tip: str = Field(
        description="Explain how to read it: axes, symbols, metrics, or key comparisons."
    )


class TableGuide(VisualGuide):
    headers: list[str] = Field(description="Original column names, in original order.")
    rows: list[list[str]] = Field(
        description="Complete data rows in original order, all values as strings. "
        "Each row must have exactly as many cells as headers."
    )
    notes: str = Field(
        description="Relevant table footnotes and transcription limitations in zh-TW. "
        "Explain unreadable cells or flattened headers; empty string if none."
    )

    @model_validator(mode="after")
    def check_rows(self):
        if self.rows and (
            not self.headers or any(len(row) != len(self.headers) for row in self.rows)
        ):
            raise ValueError("Table rows must match the number of headers.")
        if not self.rows and not self.notes.strip():
            raise ValueError("A table without data must explain why in notes.")
        return self


class Block(BaseModel):
    page: int = Field(
        description="1-based PDF page index. Use 0 only if genuinely uncertain."
    )
    kind: Kind
    importance: int = Field(ge=1, le=5)
    en: str = Field(
        description="A coherent verbatim passage, usually 3-6 consecutive sentences, "
        "preserving the claim, reasoning, and relevant conditions or evidence. "
        "Only mathematical notation may be transcribed into LaTeX."
    )
    zh: str = Field(
        description="Natural Traditional Chinese translation of the excerpt."
    )
    en_highlights: list[str] = Field(
        default_factory=list,
        description="1-3 short, exact substrings of en to highlight. "
        "Select key claims, mechanisms, or findings; never part of a LaTeX expression.",
    )
    zh_highlights: list[str] = Field(
        default_factory=list,
        description="1-3 short, exact substrings of zh corresponding to the English "
        "highlights; never part of a LaTeX expression.",
    )
    annotation: str = Field(
        description="Explain what this passage is doing in the paper."
    )
    why_it_matters: str = Field(
        description="Why a thesis reader should care about this passage."
    )
    figures: list[VisualGuide] = Field(
        default_factory=list,
        description="Reading guides for important figures discussed in this passage. "
        "Attach each figure only once, to the most relevant passage.",
    )
    tables: list[TableGuide] = Field(
        default_factory=list,
        description="Important tables discussed in this passage, including data and "
        "reading guides. Attach each table only once, to the most relevant passage.",
    )


class Section(BaseModel):
    title: str
    summary_zh: str
    blocks: list[Block]


class GlossaryEntry(BaseModel):
    term: str = Field(description="Term or abbreviation exactly as used in the paper.")
    zh: str = Field(description="Traditional Chinese name or contextual translation.")
    full_name: str = Field(
        description="Full form of an abbreviation, only if confirmed by the paper. "
        "Empty string for non-abbreviations or unknown expansions."
    )
    definition: str = Field(description="Plain-language explanation in zh-TW.")
    paper_usage: str = Field(
        description="How the paper uses this term, including any special meaning "
        "or distinction from its usual meaning, in zh-TW."
    )
    page: int = Field(
        ge=0,
        description="1-based PDF page where this usage is defined or illustrated; "
        "0 only if uncertain.",
    )


class Paper(BaseModel):
    meta: Meta
    overview: Overview
    sections: list[Section]
    glossary: list[GlossaryEntry] = Field(
        default_factory=list,
        description="Useful explanations of uncommon terms, abbreviations, and "
        "paper-specific meanings. Deduplicate and order by first appearance.",
    )


SYSTEM_PROMPT = r"""你是一位協助碩士生閱讀學術論文的研究助理。
請完整理解 PDF 後，整理成結構化閱讀筆記。輸出使用繁體中文（zh-TW），但保留重要英文術語。

原則：
- 只挑值得回頭看的段落，不要逐段重述全文。
- en 必須是 PDF 中實際存在的連續完整段落，通常 3–6 句，必要時保留相鄰段落。
  保留主張、推理或機制、實驗條件與證據，不要只抽一句結論；原段落較短時不必湊句數。
  不要改寫、拼接不相鄰的句子或補寫原文；唯一允許的轉寫是將數學符號忠實轉成 LaTeX。
- zh 完整翻譯 en，不要再壓縮成摘要；段落之間用換行分隔。
- 一般每個主要 section 挑 2–5 個互補的 block，涵蓋該節的關鍵論點；不重要或重複的段落可省略。
- importance 5 = 幾乎一定要讀；4 = 重要；3 = 有幫助；1-2 通常不要收錄。
- kind 依功能選 problem / contribution / concept / method / result / limitation。
- page 使用 PDF 檔案的 1-based 頁序；真的無法判斷才填 0。
- annotation 通常用 2–4 句解釋作者的推理、術語與方法如何運作，必要時解釋公式符號。
- why_it_matters 通常用 2–3 句說明與研究問題的關聯、相較基線的差異或適用條件，不要只是重述翻譯。
- en_highlights 與 zh_highlights 各選 1–3 個最值得注意的短片段，必須逐字出現在對應欄位中。
  優先標出關鍵主張、機制、結果及必要的限定條件；不要標記整段，也不要插入 HTML 或 Markdown 標記。
- 所有文字欄位的數學式使用 LaTeX：行內用 \( ... \)，獨立公式用 \[ ... \]，不用 $ 分隔。
  JSON 字串中的反斜線必須正確跳脫，例如 "\\(O(N^2)\\)"。
  重要公式應保留並在 annotation 解釋符號與用途；不要捏造原文沒有的公式。
  重點片段不可切開 LaTeX 公式；若公式本身是重點，選取包含分隔符的完整公式。
- 不自行發明引用、數值、資料集、實驗結果或作者主張。
- 對不確定的資訊直接保守描述。

圖表導讀：
- 挑選支撐核心方法與結果的重要圖表，將 figures / tables 附在最直接討論它的 block。
  同一圖表只收錄一次；優先放在 importance 4–5 的相關段落。沒有相關圖表時填空陣列。
- label 保留論文原始編號（如 Figure 2、Figure 3(b)、Table 1、Table A.1）。
  page 是圖表本身所在的 PDF 1-based 頁序，不是引用段落的頁碼；不確定才填 0。
- caption_en 忠實保留原始圖說／表說，caption_zh 完整翻譯為繁體中文。
- explanation 用 2–4 句說明圖表要表達的機制或結果，以及如何支撐相關段落。
  reading_tip 按閱讀順序說明先看哪裡、座標軸／箭頭／顏色／指標的意義，
  接著比較哪些曲線、列或欄，以及如何由觀察讀出結論；註明指標越高／越低越好、
  比較成立的實驗條件與必要限定。架構圖則沿資料流說明各模組的輸入、處理與輸出。
  讀者會用 label 與 page 對照原始 PDF；僅依可辨識的內容說明，不推測看不清的細節。
- 表格資料直接放入 tables 的 headers / rows，保留原始欄列順序、單位、正負號、
  小數位、±、↑↓、最佳值標記與必要註腳。所有儲存格都是字串，不四捨五入或計算替代值。
  多層表頭用「群組 / 欄名」展平，跨列標籤重複填入以保留對應關係，並在 notes 說明。
  保留原本缺值符號；無法辨識的儲存格填「無法辨識」，不要用 0 或原始缺值符號代替。
  每列長度必須等於 headers 長度。收錄的表格保留全部資料列，不只挑有利的數值。
- notes 以繁體中文保留解讀表格所需的註腳與轉寫限制，沒有時填空字串。
  若無法可靠辨識整張表格或欄列結構，headers / rows 都填空陣列，在 notes 說明原因；
  仍保留表號、頁碼及能確認的導讀，不捏造表格內容。

名詞解釋：
- glossary 收錄理解本文所需的不常見專有名詞、縮寫、作者自定義的名稱，
  以及字面普通但在本文有特殊技術意義或用法的詞；也涵蓋重要圖表中的指標與元件。
  只收錄論文實際出現且值得解釋的詞，不湊數或羅列一般單字，按首次出現順序排列。
- term 保留原文拼寫與大小寫，zh 提供本文語境下合適的繁體中文名稱或譯法。
  縮寫與全名指同一概念時合併為一筆；同一詞確有不同義項時分開說明並標明語境。
- full_name 只填論文能確認的縮寫全名；非縮寫或無法確認時填空字串。
  無法確認全名或定義時在 paper_usage 直接註明，不能用同名的常見縮寫含義猜補。
- definition 用 2–3 句白話說明這個概念是什麼、如何運作，必要時用短例子輔助，
  不要只翻譯名稱，也不要用更多未解釋的術語循環定義；例子應標明是輔助理解。
- paper_usage 用 1–3 句說明這個詞在本文指什麼、用在哪裡，或為何影響方法／結果的理解。
  作者賦予的特殊意義應與通常含義區分；一般背景解釋不能冒充本文提出的定義或發現。
- page 指向能查到該用法或定義的 PDF 1-based 頁序，真的無法確認才填 0。
  無需解釋的論文可回傳空 glossary；解釋中的公式沿用 LaTeX 規則。
"""

USER_PROMPT = """請把這篇論文整理成可供快速精讀的雙欄批註資料。
重點放在：研究問題、研究缺口、核心概念、方法設計、主要結果、限制。
請避免把參考文獻列表、例行背景敘述或重複內容收進 blocks。
"""


def annotate(pdf: Path, model: str, detail: str, reasoning_effort: str) -> Paper:
    client = OpenAI()
    uploaded = client.files.create(file=pdf.open("rb"), purpose="user_data")
    try:
        response = client.responses.parse(
            model=model,
            reasoning={"effort": reasoning_effort},
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_id": uploaded.id,
                            "detail": detail,
                        },
                        {"type": "input_text", "text": USER_PROMPT},
                    ],
                },
            ],
            text_format=Paper,
        )
        if response.output_parsed is None:
            raise RuntimeError("Model did not return a parsed paper annotation.")
        return response.output_parsed
    finally:
        try:
            client.files.delete(uploaded.id)
        except Exception:
            logger.exception("Failed to delete uploaded file %s", uploaded.id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn an academic PDF into an annotated reading webpage."
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5.6-terra"))
    parser.add_argument(
        "--detail",
        choices=["low", "auto", "high"],
        default=os.getenv("OPENAI_DETAIL", "high"),
    )
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default=os.getenv("OPENAI_REASONING", "high"),
    )
    parser.add_argument("--out", type=Path, default=Path("output"))
    args = parser.parse_args()

    if args.detail not in ("low", "auto", "high"):
        parser.error("OPENAI_DETAIL must be low, auto, or high")

    if args.pdf.suffix.lower() != ".pdf" or not args.pdf.is_file():
        parser.error("pdf must point to an existing .pdf file")
    if not os.getenv("OPENAI_API_KEY"):
        parser.error(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    paper = annotate(args.pdf, args.model, args.detail, args.reasoning)
    out_dir = args.out / args.pdf.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "paper.json"
    json_path.write_text(
        json.dumps(paper.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    html_path = out_dir / "paper.html"
    render_html(paper.model_dump(mode="json"), html_path)

    print(json_path)
    print(html_path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import json
import logging
import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

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


class Section(BaseModel):
    title: str
    summary_zh: str
    blocks: list[Block]


class Paper(BaseModel):
    meta: Meta
    overview: Overview
    sections: list[Section]


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
    parser.add_argument("--detail", choices=["low", "auto", "high"], default="low")
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default=os.getenv("OPENAI_REASONING", "high"),
    )
    parser.add_argument("--out", type=Path, default=Path("output"))
    args = parser.parse_args()

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

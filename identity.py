"""Stable, filesystem-safe identities for paper outputs."""

import hashlib
import re
from pathlib import Path

ARXIV = r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v[1-9]\d*)?"


def normalize_doi(value: str) -> str:
    value = re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if not re.fullmatch(r"10\.\d+(?:\.\d+)*/\S+", value):
        return ""
    # DOI equivalence folds Basic Latin letters, not arbitrary Unicode.
    return value.translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )


def normalize_arxiv(value: str) -> str:
    value = re.sub(
        r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\.pdf$", "", value, flags=re.IGNORECASE)
    return value if re.fullmatch(ARXIV, value) else ""


def paper_identity(pdf: Path, meta: dict) -> dict:
    with pdf.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    doi = normalize_doi(meta.get("doi", ""))
    arxiv = normalize_arxiv(meta.get("arxiv_id", ""))
    filename_id = normalize_arxiv(pdf.stem.removeprefix("arxiv-"))
    if filename_id and (not arxiv or arxiv == filename_id.split("v")[0]):
        arxiv = filename_id
    if not arxiv and doi.startswith("10.48550/arxiv."):
        arxiv = normalize_arxiv(doi[len("10.48550/arxiv.") :])
    return {
        "id": "pdf-" + digest[:24],
        "doi": doi,
        "arxiv_id": arxiv,
        "filename": pdf.name,
        "sha256": digest,
    }

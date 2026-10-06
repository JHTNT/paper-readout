import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from annotate import Paper, main
from identity import normalize_arxiv, normalize_doi, paper_identity
from test_support import example_paper


class IdentityTests(unittest.TestCase):
    def test_fingerprint_survives_filename_and_metadata_changes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "2307.08691v1.pdf", root / "renamed.pdf"
            first.write_bytes(b"same PDF")
            second.write_bytes(first.read_bytes())
            a = paper_identity(first, {})
            b = paper_identity(
                second, {"doi": "10.1234/example", "arxiv_id": "2307.08691v1"}
            )
            self.assertEqual(a["id"], b["id"])
            self.assertEqual(a["sha256"], b["sha256"])
            self.assertEqual(a["id"], "pdf-" + a["sha256"][:24])
            self.assertEqual(len(a["sha256"]), 64)
            second.write_bytes(b"revised PDF")
            self.assertNotEqual(a["id"], paper_identity(second, b)["id"])

    def test_identifier_normalization_preserves_version(self):
        self.assertEqual(normalize_doi(" DOI:10.1234/ABC "), "10.1234/abc")
        self.assertEqual(normalize_doi("https://doi.org/10.1234/ABC"), "10.1234/abc")
        self.assertEqual(normalize_doi("not a DOI"), "")
        self.assertEqual(
            normalize_arxiv("https://arxiv.org/pdf/2307.08691v2.pdf"), "2307.08691v2"
        )
        self.assertEqual(normalize_arxiv("arXiv:hep-th/9901001v1"), "hep-th/9901001v1")
        self.assertEqual(normalize_arxiv("2307.08691v0"), "")

    def test_repeated_annotation_replaces_one_entry_even_after_rename(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            pdf = root / "first.pdf"
            pdf.write_bytes(b"same PDF")
            paper_id = paper_identity(pdf, {})["id"]
            for number, name in enumerate(("first.pdf", "renamed.pdf")):
                target = root / name
                target.write_bytes(pdf.read_bytes())
                data = example_paper()
                data["meta"]["title"] = f"Run {number}"
                with (
                    patch.dict("os.environ", {"OPENAI_API_KEY": "test"}, clear=True),
                    patch(
                        "sys.argv",
                        [
                            "annotate.py",
                            str(target),
                            "--out",
                            str(output),
                            "--doi",
                            "10.1234/ABC",
                        ],
                    ),
                    patch("annotate.annotate", return_value=Paper.model_validate(data)),
                    patch("annotate.datetime") as clock,
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    clock.now.return_value = datetime(
                        2026, 10, 6, 12, number, tzinfo=UTC
                    )
                    main()
                saved = json.loads(
                    (output / paper_id / "paper.json").read_text("utf-8")
                )
                self.assertEqual(
                    saved["generation"]["generated_at"],
                    f"2026-10-06T12:0{number}:00+00:00",
                )
            saved = json.loads((output / paper_id / "paper.json").read_text("utf-8"))
            self.assertEqual(saved["meta"]["title"], "Run 1")
            self.assertEqual(saved["source"]["filename"], "renamed.pdf")
            self.assertEqual(saved["source"]["doi"], "10.1234/abc")
            self.assertEqual(len(list(output.glob("*/paper.json"))), 1)


if __name__ == "__main__":
    unittest.main()

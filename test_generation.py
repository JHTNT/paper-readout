import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.responses import ResponseUsage

from annotate import Paper, main
from generate import render_generation, render_html
from test_visual_guides import example_paper


class GenerationTests(unittest.TestCase):
    def test_api_usage_survives_json_and_html_rebuild(self):
        usage = ResponseUsage(
            input_tokens=1200,
            output_tokens=300,
            total_tokens=1500,
            input_tokens_details={"cached_tokens": 100, "cache_write_tokens": 0},
            output_tokens_details={"reasoning_tokens": 200},
        )
        client = Mock()
        client.files.create.return_value.id = "file-test"
        client.responses.parse.return_value = SimpleNamespace(
            model="actual-model-version",
            usage=usage,
            output_parsed=Paper.model_validate(example_paper()),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "test.pdf"
            pdf.write_bytes(b"mock PDF")
            with (
                patch("annotate.OpenAI", return_value=client),
                patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
                patch(
                    "sys.argv",
                    [
                        "annotate.py",
                        str(pdf),
                        "--out",
                        str(root),
                        "--reasoning",
                        "medium",
                        "--detail",
                        "low",
                    ],
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                main()
            data = json.loads((root / "test" / "paper.json").read_text("utf-8"))
            self.assertEqual(data["generation"]["model"], "actual-model-version")
            self.assertEqual(data["generation"]["usage"], usage.model_dump())
            self.assertEqual(data["generation"]["reasoning"], "medium")
            self.assertEqual(data["generation"]["detail"], "low")
            self.assertNotIn("generation", Paper.model_json_schema()["properties"])
            rebuilt = root / "rebuilt.html"
            render_html(data, rebuilt)
            html = rebuilt.read_text("utf-8")
            self.assertIn("actual-model-version", html)
            self.assertIn("REASONING：medium", html)
            self.assertIn("DETAIL：low", html)
            for count in ("1,200", "300", "1,500"):
                self.assertIn(f"{count} tokens", html)
            client.files.delete.assert_called_once_with("file-test")

    def test_missing_usage_is_not_displayed_as_zero(self):
        html = render_generation({"model": "model", "usage": None})
        self.assertIn("未提供", html)
        self.assertNotIn("0 tokens", html)

    def test_legacy_data_and_model_escaping(self):
        self.assertEqual(render_generation({}), "")
        html = render_generation({"model": "<script>bad</script>", "usage": None})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()

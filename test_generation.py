import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.responses import ResponseUsage

from annotate import Paper, main
from generate import render_generation, render_html
from identity import paper_identity
from test_support import example_paper


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
                patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True),
                patch(
                    "socket.socket.connect",
                    side_effect=AssertionError("Unexpected network request"),
                ),
                patch("annotate.monotonic", side_effect=[100.0, 112.3]),
                patch("annotate.datetime") as clock,
                patch(
                    "sys.argv",
                    [
                        "annotate.py",
                        str(pdf),
                        "--out",
                        str(root),
                        "--model",
                        "requested-model",
                        "--reasoning",
                        "medium",
                        "--detail",
                        "low",
                    ],
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()) as stderr,
            ):
                clock.now.return_value = datetime(2026, 10, 5, 18, 30, tzinfo=UTC)
                main()
            self.assertEqual(stderr.getvalue(), "總耗時：12.3s\n")
            client.responses.parse.assert_called_once()
            request = client.responses.parse.call_args.kwargs
            self.assertEqual(request["model"], "requested-model")
            self.assertEqual(request["reasoning"], {"effort": "medium"})
            self.assertEqual(
                request["input"][1]["content"][0],
                {"type": "input_file", "file_id": "file-test", "detail": "low"},
            )
            paper_id = paper_identity(pdf, {})["id"]
            data = json.loads((root / paper_id / "paper.json").read_text("utf-8"))
            self.assertEqual(data["generation"]["model"], "actual-model-version")
            self.assertEqual(data["generation"]["usage"], usage.model_dump())
            self.assertEqual(data["generation"]["reasoning"], "medium")
            self.assertEqual(data["generation"]["detail"], "low")
            self.assertEqual(
                data["generation"]["generated_at"], "2026-10-05T18:30:00+00:00"
            )
            self.assertNotIn("generation", Paper.model_json_schema()["properties"])
            rebuilt = root / "rebuilt.html"
            render_html(data, rebuilt)
            html = rebuilt.read_text("utf-8")
            self.assertIn("actual-model-version", html)
            self.assertIn("REASONING：medium", html)
            self.assertIn("DETAIL：low", html)
            for label, count in (
                ("輸入", "1,200"),
                ("輸出", "300"),
                ("思考", "200"),
                ("其他輸出", "100"),
                ("總計", "1,500"),
            ):
                self.assertIn(f"{label}：{count} tokens", html)
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

    def test_missing_reasoning_breakdown_does_not_guess(self):
        usage = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        for details in (None, {}, {"reasoning_tokens": None}):
            with self.subTest(details=details):
                html = render_generation(
                    {
                        "model": "model",
                        "usage": {**usage, "output_tokens_details": details},
                    }
                )
                self.assertIn("輸出：50 tokens", html)
                self.assertIn("思考：未提供", html)
                self.assertNotIn("其他輸出：", html)

    def test_zero_reasoning_is_a_valid_breakdown(self):
        html = render_generation(
            {
                "model": "model",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            }
        )
        self.assertIn("思考：0 tokens", html)
        self.assertIn("其他輸出：50 tokens", html)
        self.assertIn("總計：150 tokens", html)


if __name__ == "__main__":
    unittest.main()

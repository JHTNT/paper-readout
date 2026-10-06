import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from annotate import Paper, main
from identity import paper_identity
from publish import build_site, publish_library
from test_support import example_paper


class PublishTests(unittest.TestCase):
    def write_paper(self, root, name, title):
        directory = root / name
        directory.mkdir(parents=True)
        paper = example_paper()
        paper["meta"]["title"] = title
        source = directory / "paper.json"
        source.write_text(json.dumps(paper, ensure_ascii=False), encoding="utf-8")
        return source

    def test_library_rebuilds_all_papers_and_ships_only_web_assets(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output, site = root / "output", root / "site"
            first = self.write_paper(output, "first", "First paper")
            second = self.write_paper(output, "中文 # &", "<script> & Second")
            os.utime(first, (100, 100))
            os.utime(second, (200, 200))
            (output / ".env").write_text("secret", encoding="utf-8")
            (second.parent / "source.pdf").write_bytes(b"PDF")
            (second.parent / "paper.html").write_text("stale", encoding="utf-8")
            build_site(output, site)
            index = (site / "index.html").read_text(encoding="utf-8")
            self.assertIn("共 2 篇", index)
            self.assertIn("%E4%B8%AD%E6%96%87%20%23%20%26/paper.html", index)
            self.assertIn("&lt;script&gt; &amp; Second", index)
            self.assertLess(index.index("Second"), index.index("First paper"))
            self.assertIn(
                "Second", (site / second.parent.name / "paper.html").read_text("utf-8")
            )
            self.assertEqual(
                {
                    p.relative_to(site).as_posix()
                    for p in site.rglob("*")
                    if p.is_file()
                },
                {
                    "index.html",
                    "404.html",
                    "library.json",
                    "_headers",
                    "assets/style.css",
                    "assets/glossary.js",
                    "first/paper.html",
                    "中文 # &/paper.html",
                },
            )
            doc = (site / "first/paper.html").read_text("utf-8")
            self.assertIn('href="../assets/style.css"', doc)
            self.assertIn('src="../assets/glossary.js"', doc)

    def test_index_omits_numbers_and_shows_taiwan_annotation_date(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            updated = datetime(2026, 10, 5, 18, 30, tzinfo=UTC).timestamp()
            paper = example_paper()
            paper["generation"] = {"generated_at": "2026-10-05T18:30:00+00:00"}
            build_site(
                root,
                root / "site",
                records={
                    "paper": {"paper": paper, "updated": 0},
                    "removed": {"deleted": True, "updated": updated + 100},
                },
            )
            index = (root / "site/index.html").read_text("utf-8")
            self.assertIn("共 1 篇", index)
            self.assertIn("更新 2026-10-06 02:30", index)
            self.assertIn('datetime="2026-10-06T02:30:00+08:00"', index)
            self.assertNotIn("library-number", index)
            self.assertNotIn("removed/paper.html", index)
            self.assertFalse((root / "site/removed").exists())
            manifest = json.loads((root / "site/library.json").read_text("utf-8"))
            self.assertEqual(manifest["papers"]["paper"]["updated"], updated)

    def test_index_sorts_by_generation_time_instead_of_upload_time(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            records = {}
            for title, timestamp, fallback in (
                ("newer", "2026-10-06T12:00:00+00:00", 100),
                ("older", "2026-10-05T12:00:00+00:00", 999),
            ):
                paper = example_paper()
                paper["meta"]["title"] = title
                paper["generation"] = {"generated_at": timestamp}
                records[title] = {"paper": paper, "updated": fallback}
            build_site(root, root / "site", records=records)
            index = (root / "site/index.html").read_text("utf-8")
            self.assertLess(index.index(">newer</a>"), index.index(">older</a>"))

    def test_all_deleted_library_has_empty_homepage_and_shared_assets(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_site(
                root,
                root / "site",
                records={
                    "removed": {"deleted": True, "updated": 100},
                },
            )
            index = (root / "site/index.html").read_text("utf-8")
            self.assertIn("共 0 篇", index)
            self.assertIn("目前沒有論文", index)
            self.assertTrue((root / "site/assets/style.css").is_file())
            self.assertTrue((root / "site/404.html").is_file())
            self.assertFalse((root / "site/removed").exists())

    def test_deploy_uses_isolated_complete_snapshot_and_production_branch(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            self.write_paper(output, "paper", "Example")
            captured = []

            def deploy(command, **kwargs):
                site = Path(command[5])
                captured.append(site)
                self.assertEqual(kwargs["cwd"], site)
                self.assertTrue((site / "index.html").is_file())
                self.assertTrue((site / "paper" / "paper.html").is_file())
                self.assertEqual(
                    command[-4:], ["--project-name", "my-library", "--branch", "main"]
                )
                return SimpleNamespace(returncode=0, stdout="deployed\n", stderr="")

            with (
                patch("publish.shutil.which", return_value="npx"),
                patch("publish.remote_records", return_value={}),
                patch("publish.subprocess.run", side_effect=deploy),
                patch.dict(
                    os.environ,
                    {"CLOUDFLARE_PAGES_URL": "https://library.example/"},
                    clear=True,
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    publish_library(output, "my-library"), "https://library.example"
                )
            self.assertFalse(captured[0].exists())

    def test_failed_deploy_preserves_saved_papers(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            source = self.write_paper(output, "paper", "Example")
            original = source.read_bytes()
            with (
                patch("publish.shutil.which", return_value="npx"),
                patch("publish.remote_records", return_value={}),
                patch(
                    "publish.subprocess.run",
                    return_value=SimpleNamespace(
                        returncode=1, stdout="", stderr="not logged in"
                    ),
                ),
                self.assertRaisesRegex(RuntimeError, "not logged in"),
            ):
                publish_library(output, "my-library")
            self.assertEqual(source.read_bytes(), original)

    def test_empty_library_is_not_deployed(self):
        with (
            TemporaryDirectory() as directory,
            patch("publish.subprocess.run") as deploy,
        ):
            with self.assertRaisesRegex(ValueError, "No paper.json"):
                build_site(Path(directory), Path(directory) / "site")
            deploy.assert_not_called()

    def test_annotation_publishes_and_failure_can_be_retried_without_generation(self):
        for error in (None, RuntimeError("offline")):
            with self.subTest(error=error), TemporaryDirectory() as directory:
                root = Path(directory)
                pdf = root / "中文 paper.pdf"
                pdf.write_bytes(b"mock PDF")
                paper_id = paper_identity(pdf, {})["id"]
                with (
                    patch.dict(
                        os.environ,
                        {
                            "OPENAI_API_KEY": "test",
                            "CLOUDFLARE_PAGES_PROJECT": "my-library",
                        },
                        clear=True,
                    ),
                    patch(
                        "sys.argv",
                        ["annotate.py", str(pdf), "--out", str(root / "output")],
                    ),
                    patch("annotate.check_publish_config"),
                    patch(
                        "annotate.annotate",
                        return_value=Paper.model_validate(example_paper()),
                    ) as annotate,
                    patch(
                        "annotate.publish_library",
                        return_value="https://my-library.pages.dev",
                        side_effect=error,
                    ) as publish,
                    redirect_stdout(io.StringIO()) as stdout,
                    redirect_stderr(io.StringIO()) as stderr,
                ):
                    if error:
                        with self.assertRaises(SystemExit) as exit:
                            main()
                        self.assertEqual(exit.exception.code, 1)
                        self.assertIn("本機成果已保留", stderr.getvalue())
                        self.assertIn("publish.py --out", stderr.getvalue())
                    else:
                        main()
                        self.assertIn(
                            "https://my-library.pages.dev/", stdout.getvalue()
                        )
                        self.assertIn(f"{paper_id}/paper.html", stdout.getvalue())
                    annotate.assert_called_once()
                    publish.assert_called_once_with(root / "output", "my-library")
                    self.assertTrue(
                        (root / "output" / paper_id / "paper.json").is_file()
                    )
                    self.assertTrue(
                        (root / "output" / paper_id / "paper.html").is_file()
                    )

    def test_no_publish_overrides_configuration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"mock PDF")
            with (
                patch.dict(
                    os.environ,
                    {
                        "OPENAI_API_KEY": "test",
                        "CLOUDFLARE_PAGES_PROJECT": "my-library",
                    },
                    clear=True,
                ),
                patch(
                    "sys.argv",
                    [
                        "annotate.py",
                        str(pdf),
                        "--out",
                        str(root / "output"),
                        "--no-publish",
                    ],
                ),
                patch(
                    "annotate.annotate",
                    return_value=Paper.model_validate(example_paper()),
                ),
                patch("annotate.publish_library") as publish,
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                main()
            publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()

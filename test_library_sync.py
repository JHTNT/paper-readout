import copy
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from library_sync import (
    annotation_timestamp,
    fetch,
    library_url,
    load_state,
    local_records,
    mark_updated,
    merge_records,
    remote_records,
    revision,
)
from publish import publish_library
from test_support import example_paper


def record(title):
    paper = example_paper()
    paper["meta"]["title"] = title
    return {"paper": paper, "updated": 100}


class LibrarySyncTests(unittest.TestCase):
    def test_legacy_pending_publication_does_not_restore_a_deleted_paper(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            (output / ".publish-state.json").write_text(
                json.dumps({"local": {}, "pending": ["paper"]}), encoding="utf-8"
            )
            state = load_state(output)
            remote = {"paper": {"deleted": True, "updated": 200}}
            self.assertEqual(
                merge_records(remote, {"paper": record("old")}, state), remote
            )
            mark_updated(output, "paper")
            self.assertNotIn("paper", load_state(output)["restore_from"])

    def test_failed_publication_retry_does_not_restore_a_later_cloud_deletion(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            path = output / "paper/paper.json"
            path.parent.mkdir()
            path.write_text(json.dumps(record("local")["paper"]), encoding="utf-8")
            mark_updated(output, "paper")
            cloud = {"paper": record("cloud")}
            uploaded = []

            def deploy(command, **kwargs):
                site = Path(command[5])
                uploaded.append(
                    json.loads((site / "library.json").read_text("utf-8"))["papers"]
                )
                failed = len(uploaded) == 1
                return SimpleNamespace(
                    returncode=int(failed),
                    stdout="",
                    stderr="offline" if failed else "",
                )

            with (
                patch("publish.shutil.which", return_value="npx"),
                patch(
                    "publish.remote_records",
                    side_effect=lambda url, local: copy.deepcopy(cloud),
                ),
                patch("publish.subprocess.run", side_effect=deploy),
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    publish_library(output, "library")
                cloud = {"paper": {"deleted": True, "updated": 200}}
                publish_library(output, "library")
                self.assertEqual(uploaded[-1], cloud)
                # A new explicit action restores the copy at the same ID.
                mark_updated(output, "paper")
                publish_library(output, "library")
                self.assertEqual(
                    uploaded[-1]["paper"]["paper"]["meta"]["title"], "local"
                )

    def test_generation_time_survives_file_timestamp_changes_and_restore(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            paper = record("saved copy")["paper"]
            paper["generation"] = {"generated_at": "2026-10-05T18:30:00+00:00"}
            timestamp = datetime(2026, 10, 5, 18, 30, tzinfo=UTC).timestamp()
            path = output / "paper/paper.json"
            path.parent.mkdir()
            path.write_text(json.dumps(paper), encoding="utf-8")
            for mtime in (100, 999):
                os.utime(path, (mtime, mtime))
                self.assertEqual(local_records(output)["paper"]["updated"], timestamp)
            remote = {"paper": {"deleted": True, "updated": timestamp + 100}}
            mark_updated(output, "paper")
            published = []

            def deploy(command, **kwargs):
                site = Path(command[5])
                published.append(
                    json.loads((site / "library.json").read_text("utf-8"))["papers"]
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("publish.shutil.which", return_value="npx"),
                patch("publish.remote_records", return_value=remote),
                patch("publish.subprocess.run", side_effect=deploy),
                redirect_stdout(io.StringIO()),
            ):
                publish_library(output, "library")
            self.assertEqual(published[0]["paper"]["updated"], timestamp)
            self.assertEqual(
                published[0]["paper"]["paper"]["generation"], paper["generation"]
            )

    def test_invalid_generation_time_is_not_guessed_from_the_machine_timezone(self):
        for value in ("2026-10-05T18:30:00", "bad timestamp", 100):
            paper = example_paper()
            paper["generation"] = {"generated_at": value}
            with self.assertRaises((ValueError, TypeError)):
                annotation_timestamp({"paper": paper, "updated": 999})

    def test_alternating_computers_keep_both_libraries_and_newer_cloud_copy(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root / "A", root / "B"
            cloud = {}

            def save(output, identifier, title):
                path = output / identifier / "paper.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record(title)["paper"]), encoding="utf-8")

            def read_cloud(url, local):
                return copy.deepcopy(cloud)

            def deploy(command, **kwargs):
                nonlocal cloud
                path = Path(command[5])
                cloud = json.loads((path / "library.json").read_text("utf-8"))["papers"]
                for identifier, entry in cloud.items():
                    self.assertEqual(
                        (path / identifier / "paper.html").is_file(),
                        not entry.get("deleted", False),
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            save(a, "paper-a", "A original")
            save(b, "paper-b", "B original")
            with (
                patch("publish.shutil.which", return_value="npx"),
                patch("publish.remote_records", side_effect=read_cloud),
                patch("publish.subprocess.run", side_effect=deploy),
                patch.dict("os.environ", {}, clear=True),
                redirect_stdout(io.StringIO()),
            ):
                publish_library(a, "library")
                publish_library(b, "library")
                self.assertEqual(set(cloud), {"paper-a", "paper-b"})
                self.assertFalse((b / "paper-a").exists())  # No output synchronisation.
                # B explicitly regenerates the same PDF ID.
                save(b, "paper-a", "B revised")
                mark_updated(b, "paper-a")
                publish_library(b, "library")
                # A's unchanged old copy must not undo B's revision.
                publish_library(a, "library")
                self.assertEqual(
                    cloud["paper-a"]["paper"]["meta"]["title"], "B revised"
                )
                # Deleting a local copy must not delete the online paper.
                (b / "paper-b" / "paper.json").unlink()
                publish_library(b, "library")
                self.assertIn("paper-b", cloud)
                self.assertEqual(load_state(b)["pending"], [])
                # A can delete a cloud-only paper, without having B's output.
                publish_library(a, "library", delete_ids=["paper-b"])
                self.assertEqual(set(cloud["paper-b"]), {"deleted", "updated"})
                save(b, "paper-b", "B stale copy")
                publish_library(b, "library")
                self.assertTrue(cloud["paper-b"]["deleted"])
                # The last active paper can be deleted while retaining local files.
                publish_library(a, "library", delete_ids=["paper-a"])
                publish_library(b, "library")
                self.assertTrue(all(entry.get("deleted") for entry in cloud.values()))
                self.assertTrue((a / "paper-a/paper.json").is_file())
                # Only explicitly regenerating/replacing the same ID restores it.
                mark_updated(b, "paper-a")
                publish_library(b, "library")
                self.assertEqual(
                    cloud["paper-a"]["paper"]["meta"]["title"], "B revised"
                )
                self.assertTrue(cloud["paper-b"]["deleted"])

    def test_deleted_cloud_paper_is_not_restored_by_an_unfamiliar_local_copy(self):
        remote = {"paper": {"deleted": True, "updated": 200}}
        self.assertEqual(
            merge_records(
                remote, {"paper": record("old copy")}, {"local": {}, "pending": []}
            ),
            remote,
        )

    def test_unchanged_annotations_keep_cloud_update_date(self):
        remote = {"paper": record("same")}
        local = {"paper": {**record("same"), "updated": 999}}
        self.assertEqual(
            merge_records(remote, local, {"local": {}, "pending": []}), remote
        )

    def test_delete_failure_can_be_retried_without_repeating_the_flag(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            cloud = {"paper": record("cloud only")}

            def deploy(command, **kwargs):
                site = Path(command[5])
                published = json.loads((site / "library.json").read_text("utf-8"))[
                    "papers"
                ]
                self.assertTrue(published["paper"]["deleted"])
                self.assertNotIn("paper", published["paper"])
                self.assertFalse((site / "paper").exists())
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("publish.shutil.which", return_value="npx"),
                patch("publish.remote_records", return_value=cloud),
                patch(
                    "publish.subprocess.run",
                    return_value=SimpleNamespace(
                        returncode=1, stdout="", stderr="offline"
                    ),
                ) as upload,
                self.assertRaisesRegex(RuntimeError, "offline"),
            ):
                publish_library(output, "library", delete_ids=["paper"])
            self.assertEqual(load_state(output)["deleted"], ["paper"])
            with (
                patch("publish.shutil.which", return_value="npx"),
                patch("publish.remote_records", return_value=cloud),
                patch("publish.subprocess.run", side_effect=deploy),
                redirect_stdout(io.StringIO()),
            ):
                publish_library(output, "library")
            self.assertEqual(load_state(output)["deleted"], [])
            upload.assert_called_once()

    def test_unknown_delete_id_stops_before_deploy_or_saving_intent(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            with (
                patch("publish.shutil.which", return_value="npx"),
                patch(
                    "publish.remote_records", return_value={"paper": record("cloud")}
                ),
                patch("publish.subprocess.run") as deploy,
                self.assertRaisesRegex(ValueError, "Unknown paper ID"),
            ):
                publish_library(output, "library", delete_ids=["typo"])
            deploy.assert_not_called()
            self.assertEqual(load_state(output)["deleted"], [])

    def test_cloud_manifest_accepts_only_content_free_deletion_markers(self):
        deleted = {"deleted": True, "updated": 100}
        content = json.dumps({"version": 1, "papers": {"paper": deleted}}).encode()
        with patch("library_sync.fetch", return_value=content):
            self.assertEqual(
                remote_records("https://library.example", {}), {"paper": deleted}
            )
        content = json.dumps(
            {"version": 1, "papers": {"paper": {**deleted, "paper": {}}}}
        ).encode()
        with (
            patch("library_sync.fetch", return_value=content),
            self.assertRaisesRegex(ValueError, "Invalid cloud"),
        ):
            remote_records("https://library.example", {})

    def test_unknown_conflict_requires_explicit_replace(self):
        remote, local = {"paper": record("cloud")}, {"paper": record("local")}
        state = {"local": {}, "pending": []}
        with self.assertRaisesRegex(ValueError, "--replace paper"):
            merge_records(remote, local, state)
        state["pending"] = ["paper"]
        self.assertEqual(merge_records(remote, local, state), local)

    def test_locally_changed_annotation_updates_cloud(self):
        state = {"local": {"paper": revision(record("old")["paper"])}, "pending": []}
        merged = merge_records(
            {"paper": record("cloud")}, {"paper": record("edited")}, state
        )
        self.assertEqual(merged["paper"]["paper"]["meta"]["title"], "edited")

    def test_bootstrap_requires_all_existing_cloud_papers(self):
        homepage = (
            b'<main class="library"><h2><a href="paper-a/paper.html">A</a></h2></main>'
        )
        with (
            patch("library_sync.fetch", side_effect=[None, homepage]),
            self.assertRaisesRegex(ValueError, "Missing: paper-a"),
        ):
            remote_records("https://library.example", {"paper-b": record("B")})
        with patch("library_sync.fetch", side_effect=[None, homepage]):
            self.assertEqual(
                set(
                    remote_records("https://library.example", {"paper-a": record("A")})
                ),
                {"paper-a"},
            )

    def test_missing_manifest_with_spa_fallback_is_bootstrapped(self):
        homepage = b'<main class="library"><a href="paper-a/paper.html">A</a></main>'
        with patch("library_sync.fetch", return_value=homepage):
            self.assertIn(
                "paper-a",
                remote_records("https://library.example", {"paper-a": record("A")}),
            )

    def test_cloud_errors_never_trigger_local_only_deploy(self):
        with TemporaryDirectory() as directory:
            for error in (URLError("offline"), ValueError("invalid JSON")):
                with (
                    patch("publish.shutil.which", return_value="npx"),
                    patch("publish.remote_records", side_effect=error),
                    patch("publish.subprocess.run") as deploy,
                    self.assertRaises((URLError, ValueError)),
                ):
                    publish_library(Path(directory), "library")
                deploy.assert_not_called()

    def test_failed_upload_preserves_pending_replacement_for_retry(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            path = output / "paper" / "paper.json"
            path.parent.mkdir()
            path.write_text(json.dumps(record("local")["paper"]), encoding="utf-8")
            mark_updated(output, "paper")
            with (
                patch("publish.shutil.which", return_value="npx"),
                patch(
                    "publish.remote_records", return_value={"paper": record("cloud")}
                ),
                patch(
                    "publish.subprocess.run",
                    return_value=SimpleNamespace(
                        returncode=1, stdout="", stderr="offline"
                    ),
                ),
                self.assertRaisesRegex(RuntimeError, "offline"),
            ):
                publish_library(output, "library")
            self.assertIn("paper", load_state(output)["pending"])

    def test_cloud_manifest_rejects_paths(self):
        for identifier in ("../outside", "assets", "bad\\path"):
            content = json.dumps(
                {"version": 1, "papers": {identifier: record("bad")}}
            ).encode()
            with (
                patch("library_sync.fetch", return_value=content),
                self.assertRaisesRegex(ValueError, "Invalid cloud"),
            ):
                remote_records("https://library.example", {})

    def test_fetch_only_treats_404_as_missing(self):
        for status in (404, 403, 500):
            error = HTTPError("https://library.example", status, "error", None, None)
            with patch("library_sync.urlopen", side_effect=error):
                if status == 404:
                    self.assertIsNone(fetch("https://library.example/library.json"))
                else:
                    with self.assertRaises(HTTPError):
                        fetch("https://library.example/library.json")

    def test_snapshot_url_uses_production_alias(self):
        self.assertEqual(
            library_url("library", "https://ff75612a.library.pages.dev/"),
            "https://library.pages.dev",
        )
        self.assertEqual(
            library_url("library", "https://papers.example.com/"),
            "https://papers.example.com",
        )
        with self.assertRaises(ValueError):
            library_url("library", "https://example.com/not-root")

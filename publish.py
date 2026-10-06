#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from dotenv import load_dotenv

from generate import esc, render_html, render_identifiers
from library_sync import (
    annotation_timestamp,
    library_url,
    load_state,
    local_records,
    mark_updated,
    merge_records,
    remote_records,
    revision,
    save_state,
)


def build_site(output: Path, site: Path, *, records: dict | None = None) -> None:
    """Build a complete library from saved JSON; only generated web assets ship."""
    if records is None:
        records = local_records(output)
        if not records:
            raise ValueError(f"No paper.json files found in {output}")
    records = {
        identifier: {**record, "updated": annotation_timestamp(record)}
        for identifier, record in records.items()
    }
    papers = sorted(
        (
            (identifier, record)
            for identifier, record in records.items()
            if not record.get("deleted")
        ),
        key=lambda item: item[1]["updated"],
        reverse=True,
    )
    site.mkdir(parents=True, exist_ok=True)
    assets = site / "assets"
    assets.mkdir(exist_ok=True)
    for filename in ("style.css", "glossary.js"):
        shutil.copy2(Path(__file__).with_name(filename), assets / filename)
    entries = []
    for identifier, record in papers:
        paper = record["paper"]
        directory = site / identifier
        directory.mkdir(parents=True, exist_ok=True)
        render_html(paper, directory / "paper.html", asset_dir=site / "assets")
        meta = paper["meta"]
        detail = " · ".join(
            str(value) for value in (meta.get("year"), meta.get("venue")) if value
        )
        link = quote(identifier, safe="") + "/paper.html"
        updated = datetime.fromtimestamp(
            record["updated"], timezone(timedelta(hours=8))
        )
        entries.append(f"""<li>
  <div class="library-meta"><span>{esc(detail)}</span>
    <time datetime="{updated.isoformat()}">更新 {updated:%Y-%m-%d %H:%M}</time>
  </div>
  <h2><a href="{link}">{esc(meta["title"])}</a></h2>
  <p>{esc(paper["overview"]["one_line"])}</p>
  {render_identifiers({**meta, **paper.get("source", {})})}
</li>""")
    (site / "index.html").write_text(
        f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>論文閱讀庫</title>
  <link rel="stylesheet" href="assets/style.css">
  <style>
    .library {{ max-width: 1000px; margin: auto; padding: clamp(20px, 3vw, 40px); }}
    .library header {{ padding-bottom: 20px; border-bottom: 3px solid var(--accent); }}
    .library h1 {{ margin: 8px 0; font: 600 clamp(1.8rem, 4vw, 2.5rem)/1.3 Georgia, "PMingLiU", serif; }}
    .library header > p:last-child {{ color: var(--muted); margin-bottom: 0; }}
    .library ul {{ list-style: none; padding: 0; margin: 0; }}
    .library li {{ padding: 16px 0; border-bottom: 1px solid var(--border); }}
    .library h2 {{ margin: 4px 0 6px; font-size: 1.15rem; line-height: 1.4; }}
    .library h2 a {{ color: var(--text); text-decoration: none; }}
    .library h2 a:hover {{ color: var(--accent); text-decoration: underline; }}
    .library li p {{ margin: 0; font-size: .9rem; line-height: 1.65; }}
    .library li .paper-meta {{ margin-top: 4px; font-size: .8rem; }}
    .library-meta {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 16px; color: var(--muted); font-size: .8rem; }}
    .library-meta time {{ white-space: nowrap; }}
  </style>
</head>
<body>
<main class="library">
  <header><p class="eyebrow" lang="en">PAPER READOUT / READING LIBRARY</p>
    <h1>論文閱讀庫</h1><p>共 {len(papers)} 篇 · 雙語摘錄、閱讀批註與圖表導讀</p></header>
  <ul>{"".join(entries)}</ul>
  {"<p>目前沒有論文。</p>" if not papers else ""}
</main>
</body>
</html>""",
        encoding="utf-8",
    )
    manifest = json.dumps({"version": 1, "papers": records}, ensure_ascii=False).encode(
        "utf-8"
    )
    if len(manifest) > 25 * 1024 * 1024:
        raise ValueError("Cloud library exceeds the Pages 25 MiB file limit")
    (site / "library.json").write_bytes(manifest)
    (site / "404.html").write_text(
        """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>找不到論文</title><link rel="stylesheet" href="/assets/style.css">
<style>main { max-width: 1000px; margin: auto; padding: clamp(20px, 3vw, 40px); }</style></head>
<body><main><h1>找不到論文</h1>
<p>這個頁面不存在，或論文已被刪除。</p><p><a href="/">返回論文閱讀庫</a></p>
</main></body></html>""",
        encoding="utf-8",
    )
    (site / "_headers").write_text(
        "/library.json\n  Cache-Control: no-store\n", encoding="utf-8"
    )


def check_publish_config(project: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,57}[a-z0-9]|[a-z0-9]", project):
        raise ValueError(
            "CLOUDFLARE_PAGES_PROJECT must be a lowercase Pages project name"
        )
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if not npx:
        raise ValueError("Publishing requires Node.js/npm (npx was not found)")
    return npx


def publish_library(
    output: Path, project: str, *, delete_ids: list[str] | None = None
) -> str:
    npx = check_publish_config(project)
    url = library_url(project, os.getenv("CLOUDFLARE_PAGES_URL", ""))
    local = local_records(output)
    state = load_state(output)
    remote = remote_records(url, local)
    if delete_ids:
        for identifier in delete_ids:
            if identifier not in remote and identifier not in local:
                raise ValueError(f"Unknown paper ID: {identifier}")
        state["deleted"] = sorted(set(state["deleted"]) | set(delete_ids))
        state["pending"] = [
            identifier
            for identifier in state["pending"]
            if identifier not in state["deleted"]
        ]
    for identifier in state["pending"]:
        if identifier in local and identifier not in state["restore_from"]:
            existing = remote.get(identifier, {})
            state["restore_from"][identifier] = (
                existing["updated"] if existing.get("deleted") is True else None
            )
    if state["pending"] or state["deleted"]:
        # Keep the observed deletion marker across retries. A fresh explicit
        # generation/replacement resets it; an older failed upload cannot restore
        # a paper deleted later by the other computer.
        save_state(output, state)
    records = merge_records(remote, local, state)
    with TemporaryDirectory(prefix="paper-readout-") as directory:
        site = Path(directory)
        build_site(output, site, records=records)
        # An isolated cwd prevents project-side Wrangler configuration/functions
        # from being picked up. Use the production branch from the one-time setup.
        result = subprocess.run(
            [
                npx,
                "--yes",
                "wrangler@4",
                "pages",
                "deploy",
                str(site),
                "--project-name",
                project,
                "--branch",
                "main",
            ],
            cwd=site,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode:
            raise RuntimeError(
                "Cloudflare deployment failed. Check Wrangler login and the Pages "
                "project.\n" + result.stdout + result.stderr
            )
        print(result.stdout, end="")
    save_state(
        output,
        {
            "local": {
                identifier: revision(record["paper"])
                for identifier, record in local.items()
            },
            "pending": [],
            "deleted": [],
            "restore_from": {},
        },
    )
    return url


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(
        description="Publish saved papers without calling the model."
    )
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument(
        "--delete",
        action="append",
        default=[],
        metavar="PAPER_ID",
        help="Remove a paper from the cloud library; keep local files.",
    )
    parser.add_argument(
        "--replace",
        action="append",
        default=[],
        metavar="PAPER_ID",
        help="Explicitly replace an existing cloud annotation with this local copy.",
    )
    args = parser.parse_args()
    project = os.getenv("CLOUDFLARE_PAGES_PROJECT", "").strip()
    if not project:
        parser.error("Set CLOUDFLARE_PAGES_PROJECT in .env first")
    if set(args.replace) & set(args.delete):
        parser.error("The same paper cannot be both replaced and deleted")
    try:
        for identifier in args.replace:
            if (
                not (args.out / identifier / "paper.json").is_file()
                or Path(identifier).name != identifier
            ):
                parser.error("--replace must name a local paper directory")
            mark_updated(args.out, identifier)
        url = publish_library(args.out, project, delete_ids=args.delete)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"發布失敗：{error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"論文閱讀庫：{url}/")


if __name__ == "__main__":
    main()

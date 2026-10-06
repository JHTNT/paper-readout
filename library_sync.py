"""Merge a public Pages library with this computer's local annotations."""

import hashlib
import json
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

STATE = ".publish-state.json"


def revision(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def library_url(project: str, configured: str = "") -> str:
    url = configured.strip() or f"https://{project}.pages.dev"
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        raise ValueError("CLOUDFLARE_PAGES_URL must be an HTTPS site root")
    # Deployment hash URLs are immutable snapshots, not the current library.
    host = re.sub(r"^[0-9a-f]{8}\.(.+\.pages\.dev)$", r"\1", parsed.netloc)
    return urlunsplit((parsed.scheme, host, "", "", ""))


def annotation_timestamp(record: dict) -> float:
    generation = record.get("paper", {}).get("generation") or {}
    value = generation.get("generated_at")
    if value is None:
        return record["updated"]  # Legacy annotations/deletion markers.
    generated = datetime.fromisoformat(value)
    if generated.tzinfo is None:
        raise ValueError("generation.generated_at must include a timezone")
    return generated.timestamp()


def local_records(output: Path) -> dict:
    records = {}
    for path in output.glob("*/paper.json"):
        record = {
            "paper": json.loads(path.read_text("utf-8")),
            "updated": path.stat().st_mtime,
        }
        record["updated"] = annotation_timestamp(record)
        records[path.parent.name] = record
    return records


def load_state(output: Path) -> dict:
    path = output / STATE
    state = (
        json.loads(path.read_text("utf-8"))
        if path.exists()
        else {"local": {}, "pending": []}
    )
    if (
        not isinstance(state, dict)
        or not {"local", "pending"}.issubset(state)
        or not set(state).issubset({"local", "pending", "deleted", "restore_from"})
        or not isinstance(state.get("local"), dict)
        or not isinstance(state.get("pending"), list)
        or not isinstance(state.get("deleted", []), list)
        or not isinstance(state.get("restore_from", {}), dict)
    ):
        raise ValueError("Invalid local publish state")
    state.setdefault("deleted", [])
    state.setdefault(
        "restore_from", {identifier: None for identifier in state["pending"]}
    )
    return state


def save_state(output: Path, state: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / (STATE + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(output / STATE)


def mark_updated(output: Path, paper_id: str) -> None:
    state = load_state(output)
    state["pending"] = sorted(set(state["pending"]) | {paper_id})
    state["restore_from"].pop(paper_id, None)
    state["deleted"] = [
        identifier for identifier in state["deleted"] if identifier != paper_id
    ]
    save_state(output, state)


def fetch(url: str) -> bytes | None:
    request = Request(
        url + "?readout=" + uuid4().hex,
        headers={"Cache-Control": "no-cache", "User-Agent": "paper-readout/0.1"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


class LibraryLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.is_library = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "main" and attrs.get("class") == "library":
            self.is_library = True
        if tag == "a":
            href = attrs.get("href", "")
            if href.endswith("/paper.html"):
                self.ids.add(unquote(href[: -len("/paper.html")]))


def remote_records(url: str, local: dict) -> dict:
    content = fetch(url + "/library.json")
    if content is not None and not content.lstrip().startswith(b"<"):
        manifest = json.loads(content)
        if (
            not isinstance(manifest, dict)
            or manifest.get("version") != 1
            or not isinstance(manifest.get("papers"), dict)
        ):
            raise ValueError("Invalid cloud library; publication stopped")
        records = manifest["papers"]
        for identifier, record in records.items():
            if (
                not identifier
                or identifier in (".", "..", "assets")
                or any(char in identifier for char in "/\\:")
                or not isinstance(record, dict)
                or (
                    set(record) != {"deleted", "updated"}
                    if record.get("deleted") is True
                    else not isinstance(record.get("paper"), dict)
                )
                or not isinstance(record.get("updated"), (int, float))
            ):
                raise ValueError("Invalid cloud paper entry; publication stopped")
        return records
    # Upgrade the old HTML-only deployment only from a computer that has every
    # paper in that deployment. A network failure is never treated as an empty site.
    homepage = fetch(url + "/")
    if homepage is None:
        return {}
    parser = LibraryLinks()
    parser.feed(homepage.decode("utf-8"))
    if not parser.is_library:
        raise ValueError("Cloud site has no readable library; publication stopped")
    missing = parser.ids - local.keys()
    if missing:
        raise ValueError(
            "First cloud-library upgrade requires the computer with all existing papers. Missing: "
            + ", ".join(sorted(missing))
        )
    return {identifier: local[identifier] for identifier in parser.ids}


def merge_records(remote: dict, local: dict, state: dict) -> dict:
    merged = dict(remote)
    for identifier, record in local.items():
        if identifier in state.get("deleted", []):
            continue
        digest = revision(record["paper"])
        existing = remote.get(identifier)
        if existing and existing.get("deleted") is True:
            if (
                identifier in state["pending"]
                and state.get("restore_from", {}).get(identifier) == existing["updated"]
            ):
                merged[identifier] = record
            continue  # Retrying an older intent must not undo a later deletion.
        if existing and digest != revision(existing["paper"]):
            if identifier in state["pending"]:
                pass  # Explicitly generated on this computer; replaces this ID.
            elif state["local"].get(identifier) == digest:
                continue  # Unchanged local copy; retain the newer cloud record.
            elif identifier not in state["local"]:
                raise ValueError(
                    f"Local and cloud annotations differ for {identifier}. Use --replace {identifier} to publish this local annotation."
                )
        elif existing:
            continue
        merged[identifier] = record
    for identifier in state.get("deleted", []):
        if identifier not in remote and identifier not in local:
            raise ValueError(f"Unknown paper ID: {identifier}")
        if not remote.get(identifier, {}).get("deleted"):
            merged[identifier] = {"deleted": True, "updated": time.time()}
    return merged

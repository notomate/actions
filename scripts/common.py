"""Shared inputs, step outputs and Markdown publication for Notomate's act runner."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ActionError(Exception):
    """A safe, user-facing error (never includes HTTP bodies or credentials)."""


def get_input(name: str, default: str = "", required: bool = False) -> str:
    value = os.environ.get("INPUT_" + name.upper().replace("-", "_"), "").strip() or default
    if required and not value:
        raise ActionError(f"Missing required input: {name}")
    return value


def positive_int(name: str, default: str, maximum: int) -> int:
    value = get_input(name, default)
    if not re.fullmatch(r"[0-9]+", value) or not 1 <= int(value) <= maximum:
        raise ActionError(f"{name} must be an integer between 1 and {maximum}.")
    return int(value)


def http_url(value: str, name: str) -> str:
    try:
        parts = urlsplit(value)
        valid = parts.scheme in {"http", "https"} and parts.hostname and not parts.username and not parts.password
        _ = parts.port
    except ValueError:
        valid = False
    if not valid or any(c.isspace() for c in value):
        raise ActionError(f"{name} must be an HTTP(S) URL without embedded credentials.")
    return value


def timezone_input() -> ZoneInfo:
    try:
        return ZoneInfo(get_input("timezone", "Asia/Taipei"))
    except (ZoneInfoNotFoundError, ValueError):
        raise ActionError("timezone must be a valid IANA time zone, for example Asia/Taipei.") from None


def now_in(zone: ZoneInfo) -> datetime:
    return datetime.now(zone)


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    workspace_id: str
    visibility: str

    @classmethod
    def read(cls) -> Settings:
        base_url = http_url(get_input("notomate-base-url", required=True), "notomate-base-url")
        parts = urlsplit(base_url)
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ActionError("notomate-base-url must be an origin, without a path, query or fragment.")
        api_key = get_input("notomate-api-key", required=True)
        visibility = get_input("note-visibility", "private")
        if visibility not in {"private", "public", "workspace"}:
            raise ActionError("note-visibility must be private, public or workspace.")
        try:
            payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
            workspace_id = payload["workspace"]["id"]
        except (KeyError, OSError, ValueError, TypeError):
            raise ActionError("GITHUB_EVENT_PATH must contain a Notomate event with workspace.id.") from None
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise ActionError("The Notomate event must contain a nonempty workspace.id.")
        if payload.get("event") in {"comment.created", "channel.room_created"}:
            raise ActionError("Use this action with schedule or workflow_dispatch, not comment/channel events.")
        return cls(base_url.rstrip("/"), api_key, workspace_id, visibility)


def output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise ActionError("GITHUB_OUTPUT is required.")
    # A random delimiter prevents user text from injecting another workflow output.
    delimiter = "nm_" + uuid.uuid4().hex
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def markdown_escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", text)


def note_outputs(title: str, content: str, data: dict) -> None:
    """Expose a rendered note and its template data; write-note publishes them."""
    output("title", title)
    output("content", content)
    output("data", json.dumps({**data, "title": title, "content": content}, ensure_ascii=False))


def annotation(kind: str, message: str) -> None:
    safe = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{kind}::{safe}")


def run(main) -> None:
    try:
        output("conclusion", "failure")
        main()
    except Exception as exc:
        # Third-party exception messages can contain URLs, payloads or credentials.
        message = str(exc) if isinstance(exc, ActionError) else f"Unexpected {type(exc).__name__}; action failed."
        annotation("error", message)
        sys.exit(1)


def fetch_feed(url: str) -> bytes:
    import requests

    for attempt in range(3):
        try:
            response = requests.get(url, timeout=(10, 30), headers={"User-Agent": "notomate-actions/1.0 (RSS reader)"})
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                response.close()
                time.sleep(2 ** attempt)
                continue
            if not response.ok:
                raise ActionError(f"RSS source returned HTTP {response.status_code}.")
            return response.content
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise ActionError("RSS source could not be reached after 3 attempts.") from None
            time.sleep(2 ** attempt)
        except requests.RequestException:
            raise ActionError("RSS request failed.") from None
    raise ActionError("RSS request failed.")


def publish(settings: Settings, title: str, content: str) -> str:
    import requests

    url = f"{settings.base_url}/api/v1/workspaces/{quote(settings.workspace_id, safe='')}/notes"
    # Never retry POST: a timeout does not prove the note was not created.
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {settings.api_key}", "X-Content-Format": "markdown"},
            json={"title": title, "content": content, "visibility": settings.visibility},
            timeout=(10, 30),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ActionError("Note publication could not be confirmed. Check Notomate before rerunning; POST was not retried.") from None
    if not 200 <= response.status_code < 300:
        raise ActionError(f"Notomate note publication returned HTTP {response.status_code}; POST was not retried.")
    try:
        body = response.json()
        note_id = body.get("id") if isinstance(body, dict) else None
    except ValueError:
        note_id = None
    if not isinstance(note_id, str) or not note_id.strip():
        raise ActionError("Note publication returned no note ID. Check Notomate before rerunning.")
    output("note-id", note_id)
    return note_id

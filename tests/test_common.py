import json
from unittest.mock import Mock

import pytest
import requests

import common


def test_publication_contract(environment, server, monkeypatch):
    monkeypatch.setenv("INPUT_NOTOMATE_BASE_URL", server["url"])
    settings = common.Settings.read()
    assert common.publish(settings, "Menu", "## Lunch\nRice") == "note-123"
    path, headers, body = server["posts"][0]
    assert path == "/api/v1/workspaces/workspace-1/notes"
    assert headers["Authorization"] == "Bearer test-secret"
    assert headers["X-Content-Format"] == "markdown"
    assert headers["Content-Type"] == "application/json"
    assert body == {"title": "Menu", "content": "## Lunch\nRice", "visibility": "private"}
    assert "note-123" in environment.read_text(encoding="utf-8")


@pytest.mark.parametrize("status,body", [(401, {"secret": "do-not-log"}), (500, {}), (302, {}), (201, {}), (201, {"id": 7})])
def test_publication_failure_never_retries(environment, server, monkeypatch, status, body):
    monkeypatch.setenv("INPUT_NOTOMATE_BASE_URL", server["url"])
    server.update(status=status, body=body)
    with pytest.raises(common.ActionError) as exc:
        common.publish(common.Settings.read(), "Title", "Body")
    assert "do-not-log" not in str(exc.value)
    assert len(server["posts"]) == 1


def test_timeout_post_not_retried(environment, monkeypatch):
    post = Mock(side_effect=requests.Timeout("test-secret"))
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(common.ActionError, match="Check Notomate"):
        common.publish(common.Settings.read(), "title", "body")
    assert post.call_count == 1


@pytest.mark.parametrize("key,value", [
    ("INPUT_NOTOMATE_API_KEY", ""), ("INPUT_NOTOMATE_BASE_URL", "https://host/api"),
    ("INPUT_NOTOMATE_BASE_URL", "https://user:password@host"),
    ("INPUT_NOTE_VISIBILITY", "everyone"),
])
def test_invalid_settings(environment, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(common.ActionError):
        common.Settings.read()


def test_invalid_timezone(monkeypatch):
    monkeypatch.setenv("INPUT_TIMEZONE", "not-a-zone")
    with pytest.raises(common.ActionError, match="timezone"):
        common.timezone_input()


def test_note_outputs_include_title_and_content_in_data(outputs):
    common.note_outputs("Title", "Body\nline", {"items": [1]})
    values = outputs()
    assert values["title"] == "Title" and values["content"] == "Body\nline"
    assert json.loads(values["data"]) == {"items": [1], "title": "Title", "content": "Body\nline"}


@pytest.mark.parametrize("payload", [{}, {"workspace": {"id": ""}}, {"workspace": {"id": 7}}, []])
def test_missing_workspace(environment, monkeypatch, tmp_path, payload):
    event = tmp_path / "bad.json"
    event.write_text(json.dumps(payload))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    with pytest.raises(common.ActionError, match="workspace.id"):
        common.Settings.read()


def test_get_retries_transient_failure(monkeypatch):
    get = Mock(side_effect=[requests.Timeout(), Mock(status_code=503), Mock(status_code=200, ok=True, content=b"feed")])
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
    assert common.fetch_feed("https://source.test") == b"feed"
    assert get.call_count == 3


def test_get_does_not_retry_forbidden(monkeypatch):
    get = Mock(return_value=Mock(status_code=403, ok=False))
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(common.ActionError, match="403"):
        common.fetch_feed("https://source.test")
    assert get.call_count == 1


def test_outputs_handle_multiline_text(environment):
    value = "foo\nEOF\nconclusion=success\n$(not-a-command)"
    common.output("prompt", value)
    lines = environment.read_text(encoding="utf-8").splitlines()
    delimiter = lines[0].split("<<")[1]
    assert lines[-1] == delimiter
    assert "\n".join(lines[1:-1]) == value

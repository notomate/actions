import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import yaml

import common
import stocks
import write_note
from common import ActionError
from rss import render_feed

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 6, 9, tzinfo=ZoneInfo("Asia/Taipei"))


def example_step(name):
    workflow = yaml.load((ROOT / "examples" / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return next(iter(workflow["jobs"].values()))["steps"][-1]["with"]


def stock_data(failures=()):
    history = pd.DataFrame({"Close": [100, 110], "Volume": [10, 20]},
                           index=pd.date_range("2026-10-02", periods=2, tz="America/New_York"))
    quotes = [stocks.extract_quote(symbol, history, {"currency": "USD"}) for symbol in ("AAPL", "2330.TW")]
    title, content, data = stocks.render_quotes(quotes, list(failures), NOW)
    return {**data, "title": title, "content": content}


def test_defaults_publish_source_title_and_content():
    assert write_note.render("{{ title }}", "{{ content }}", {"title": "T", "content": "# Body {{ not_a_tag }}\n"}) == \
        ("T", "# Body {{ not_a_tag }}\n")


def test_stock_template_loops_over_quotes():
    step = example_step("stocks-digest.yml")
    _, content = write_note.render("{{ title }}", step["template"], stock_data([("BAD", "unavailable")]))
    lines = content.splitlines()
    header = lines.index("| Symbol | Date | Close | Change % |")
    # Block tags leave no blank lines, so every quote stays inside the table.
    assert lines[header + 2:header + 4] == ["| AAPL | 2026-10-03 | 110.00 USD | +10.00 |",
                                            "| 2330\\.TW | 2026-10-03 | 110.00 USD | +10.00 |"]
    assert lines[header + 4] == ""
    assert "- BAD: unavailable" in lines


def test_stock_template_without_failures_omits_section():
    _, content = write_note.render("{{ title }}", example_step("stocks-digest.yml")["template"], stock_data())
    assert "Unavailable" not in content


def test_rss_template_loops_over_items():
    feed = b'<rss version="2.0"><channel><title>News</title><link>https://n.test</link><description>d</description>' \
           b'<item><title>A [x]</title><link>https://n.test/a</link></item><item><title>B</title></item></channel></rss>'
    title, content, data = render_feed(feed, "https://n.test/rss", 10, NOW)
    step = example_step("rss-digest.yml")
    rendered_title, body = write_note.render(step["title"], step["template"], {**data, "title": title, "content": content})
    assert rendered_title == "2026-10-06 News Headlines"
    assert "- [A \\[x\\]](<https://n.test/a>)\n- B\n" in body


def test_number_filter_handles_missing_values():
    assert write_note.render("t", "{{ a | number }} {{ b | number('+.1f') }} {{ b | number(missing='-') }}", {"a": 1234.5, "b": None}) == \
        ("t", "1,234.50 N/A -")


@pytest.mark.parametrize("title,template,data,match", [
    ("{{ title }}", "{{ missing }}", {"title": "t"}, "missing"),
    ("{{ title }}", "{% for x in %}", {"title": "t"}, "template failed"),
    ("  {{ blank }} ", "body", {"blank": ""}, "title is empty"),
    ("{{ title }}", "{{ content }}", {"title": "t", "content": ""}, "body is empty"),
    ("{{ title }}", "{% for i in items %}{{ i }}{% endfor %}\n", {"title": "t", "items": []}, "body is empty"),
    ("t", "{{ ''.__class__.__mro__ }}", {}, "template failed"),
])
def test_template_errors(title, template, data, match):
    with pytest.raises(ActionError, match=match):
        write_note.render(title, template, data)


@pytest.mark.parametrize("value", ["not json", "[1]", '"text"'])
def test_data_must_be_object(value):
    with pytest.raises(ActionError, match="JSON object"):
        common.parse_data(value)


def test_write_note_entrypoint_publishes_once(outputs, server, tmp_path):
    env = dict(os.environ, INPUT_NOTOMATE_BASE_URL=server["url"], INPUT_DATA=json.dumps({"title": "Menu", "items": ["a", "b"]}),
               INPUT_TEMPLATE="{% for i in items %}\n- {{ i }}\n{% endfor %}")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/write_note.py")], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [post[2] for post in server["posts"]] == [{"title": "Menu", "content": "- a\n- b\n", "visibility": "private"}]
    assert outputs() == {"conclusion": "success", "note-id": "note-123"}


def test_template_failure_publishes_nothing(outputs, server, tmp_path):
    env = dict(os.environ, INPUT_NOTOMATE_BASE_URL=server["url"], INPUT_DATA="{}", INPUT_TITLE="t", INPUT_TEMPLATE="{{ nope }}")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/write_note.py")], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 1 and "nope" in result.stdout
    assert not server["posts"]
    assert outputs() == {"conclusion": "failure"}

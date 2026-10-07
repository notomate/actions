import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from common import ActionError
from rss import render_feed

NOW = datetime(2026, 10, 6, 7, tzinfo=ZoneInfo("Asia/Taipei"))


def rss(items=""):
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>US News</title><link>https://news.test</link><description>News</description>{items}</channel></rss>'.encode()


def test_rss_sort_dedupe_limit_and_plain_summary():
    items = '''
    <item><guid>old</guid><title>Old</title><link>https://news.test/old</link><pubDate>Mon, 05 Oct 2026 00:00:00 GMT</pubDate></item>
    <item><guid>new</guid><title>New</title><link>https://news.test/new</link><pubDate>Tue, 06 Oct 2026 00:00:00 GMT</pubDate><description><![CDATA[<b>Actual summary</b><script>bad()</script>]]></description></item>
    <item><guid>duplicate</guid><title>Duplicate</title><link>https://news.test/new</link></item>
    <item><title>Unknown date</title></item>'''
    title, content, data = render_feed(rss(items), "https://news.test/rss", 2, NOW)
    assert title == "2026-10-06 US News News Digest"
    assert content.index("## New") < content.index("## Old")
    assert "Duplicate" not in content and "Unknown date" not in content
    assert "Actual summary" in content and "<b>" not in content and "bad()" not in content
    assert "https://news.test/new" in content
    assert data["feed_title"] == "US News" and data["date"] == "2026-10-06"
    assert data["items"][0] == {"title": "New", "summary": "Actual summary", "link": "https://news.test/new",
                                "published": "2026-10-06T00:00:00+00:00"}
    assert [item["title"] for item in data["items"]] == ["New", "Old"]


def test_escaped_html_text_is_not_parsed_twice():
    _, content, data = render_feed(rss("<item><title>a &amp;lt;b&amp;gt; c</title></item>"), "https://news.test", 10, NOW)
    assert data["items"][0]["title"] == "a <b> c"
    assert "## a \\<b\\> c" in content


def test_undated_entries_preserve_order_and_unsafe_links_removed():
    _, content, _ = render_feed(rss('<item><title>A</title><link>javascript:alert(1)</link></item><item><title>B</title></item>'), "https://news.test", 10, NOW)
    assert content.index("## A") < content.index("## B")
    assert "javascript:" not in content
    assert "Published/updated at: Not provided" in content


def test_atom_supported():
    atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><id>urn:feed</id><updated>2026-10-06T00:00:00Z</updated><entry><id>urn:1</id><title>Entry</title><updated>2026-10-06T00:00:00Z</updated><summary>Text</summary><link href="https://news.test/1"/></entry></feed>'
    assert "## Entry" in render_feed(atom, "https://news.test", 10, NOW)[1]


@pytest.mark.parametrize("data", [b"<html><body>Forbidden</body></html>", b"broken", b'<rss version="2.0"><channel>'])
def test_bad_feed_fails(data):
    with pytest.raises(ActionError):
        render_feed(data, "https://news.test", 10, NOW)


def test_empty_feed_skips():
    assert render_feed(rss(), "https://news.test", 10, NOW) is None


@pytest.mark.parametrize("empty", [False, True])
def test_rss_entrypoint_outputs_without_publishing(outputs, server, tmp_path, empty):
    server["feed"] = rss() if empty else rss('<item><title>Hello</title><description>World</description></item>')
    env = dict(os.environ, INPUT_FEED_URL=server["url"] + "/rss")
    script = Path(__file__).resolve().parents[1] / "scripts/rss.py"
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not server["posts"]
    values = outputs()
    assert values["conclusion"] == ("skipped" if empty else "success")
    if empty:
        assert "content" not in values
    else:
        assert "## Hello" in values["content"] and values["title"].endswith(" US News News Digest")
        assert json.loads(values["data"])["items"][0]["summary"] == "World"


def test_bad_feed_entrypoint_fails(outputs, server, tmp_path):
    server["feed"] = b"<html>not a feed</html>"
    env = dict(os.environ, INPUT_FEED_URL=server["url"] + "/rss")
    script = Path(__file__).resolve().parents[1] / "scripts/rss.py"
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert outputs() == {"conclusion": "failure"}

from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

import feedparser

from common import ActionError, Settings, fetch_feed, get_input, http_url, output, positive_int, publish, run


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value: str) -> str:
    parser = TextOnly()
    parser.feed(value)
    return " ".join("".join(parser.parts).split())


def markdown_text(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", plain(value))


def entry_time(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return calendar.timegm(parsed)
        except (ValueError, OverflowError, TypeError):
            pass
    return None


def render_feed(data: bytes, source: str, limit: int, now: datetime) -> tuple[str, str] | None:
    feed = feedparser.parse(data)
    if not feed.version or feed.get("bozo"):
        raise ActionError("RSS source is not a valid RSS/Atom feed (it may be an HTML error page).")
    indexed = list(enumerate(feed.entries))
    indexed.sort(key=lambda item: (entry_time(item[1]) is None, -(entry_time(item[1]) or 0), item[0]))
    entries = []
    seen_ids, seen_links = set(), set()
    for _, entry in indexed:
        identity = entry.get("id")
        link = urljoin(source, entry.get("link", "")) if entry.get("link") else ""
        try:
            if link:
                http_url(link, "article link")
        except ActionError:
            link = ""
        if (identity and identity in seen_ids) or (link and link in seen_links):
            continue
        if identity:
            seen_ids.add(identity)
        if link:
            seen_links.add(link)
        entries.append((entry, link))
        if len(entries) == limit:
            break
    if not entries:
        return None
    name = plain(feed.feed.get("title", "RSS")) or "RSS"
    title = f"{now:%Y-%m-%d} {name} News Digest"
    lines = [f"Retrieved at: {now.isoformat(timespec='seconds')}", "", f"Source: <{quote(source, safe=':/?=&%#@+~,;')}>", ""]
    for entry, link in entries:
        lines.extend([f"## {markdown_text(entry.get('title', 'Untitled'))}", ""])
        timestamp = entry_time(entry)
        date = datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp is not None else "Not provided"
        lines.extend([f"Published/updated at: {date}", "", markdown_text(entry.get("summary", "No summary provided by the source.")), ""])
        if link:
            lines.extend([f"[Read the original article](<{quote(link, safe=':/?=&%#@+~,;')}>)", ""])
    return title, "\n".join(lines)


def main():
    settings = Settings.read()
    source = http_url(get_input("feed-url", "https://www.usnews.com/rss/news"), "feed-url")
    limit = positive_int("max-items", "10", 100)
    note = render_feed(fetch_feed(source), source, limit, settings.now())
    if note is None:
        output("conclusion", "skipped")
        print("Feed is empty; no note created.")
        return
    publish(settings, *note)
    output("conclusion", "success")


if __name__ == "__main__":
    run(main)

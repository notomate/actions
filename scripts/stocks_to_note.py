from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime

from common import ActionError, Settings, annotation, get_input, output, publish, run


def parse_symbols(value: str) -> list[str]:
    symbols = list(dict.fromkeys(s.strip().upper() for s in re.split(r"[,\r\n]+", value) if s.strip()))
    if not symbols or len(symbols) > 50:
        raise ActionError("symbols must contain between 1 and 50 comma/newline-separated Yahoo Finance symbols.")
    if any(not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,31}", s) for s in symbols):
        raise ActionError("Invalid stock symbol; use Yahoo Finance codes such as AAPL, 2330.TW or ^GSPC.")
    return symbols


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


@dataclass
class Quote:
    symbol: str
    currency: str
    date: str
    close: float
    change: float | None
    percent: float | None
    volume: float | None


def extract_quote(symbol, history, metadata) -> Quote:
    if history.empty or "Close" not in history:
        raise ActionError("No daily price data available")
    # Preserve the immediately preceding row; missing prices are not silently skipped.
    close = number(history.iloc[-1].get("Close"))
    if close is None:
        raise ActionError("The latest daily bar has no price")
    previous = number(history.iloc[-2].get("Close")) if len(history) > 1 else None
    change = close - previous if previous is not None else None
    percent = change / previous * 100 if previous not in {None, 0} else None
    return Quote(symbol, str(metadata.get("currency") or "N/A"), history.index[-1].strftime("%Y-%m-%d"), close,
                 change, percent, number(history.iloc[-1].get("Volume")))


def fetch_quote(symbol: str) -> Quote:
    import yfinance as yf
    from curl_cffi.requests.exceptions import ConnectionError, Timeout
    from yfinance.exceptions import YFRateLimitError

    # yfinance otherwise prints response bodies/third-party exception messages.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="1mo", interval="1d", auto_adjust=False, timeout=20, raise_errors=True)
            # Metadata is populated by history(); no additional quote-info request is needed.
            metadata = ticker.get_history_metadata()
            return extract_quote(symbol, history, metadata or {})
        except (YFRateLimitError, ConnectionError, Timeout):
            if attempt == 2:
                raise ActionError("Rate limit or connection timeout persisted after retries") from None
            time.sleep(2 ** attempt)
        except ActionError:
            raise
        except Exception:
            raise ActionError("Unable to retrieve data; check the symbol or try again later") from None
    raise ActionError("Unable to retrieve data")


def cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def fmt(value, signed=False):
    return "N/A" if value is None else format(value, "+,.2f" if signed else ",.2f")


def render_quotes(quotes: list[Quote], failures: list[tuple[str, str]], now: datetime):
    lines = [f"Retrieved at: {now.isoformat(timespec='seconds')}", "", "Source: Yahoo Finance (via yfinance). These are the latest available daily bars, not real-time quotes.",
             "Daily data may be incomplete before the market closes; on non-trading days, the latest trading day is shown. Changes compare against the preceding daily bar, with auto_adjust disabled.", "",
             "| Symbol | Currency | Data date (exchange) | Daily price | Change | Change % | Volume |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for q in quotes:
        volume = "N/A" if q.volume is None else f"{q.volume:,.0f}"
        lines.append(f"| {cell(q.symbol)} | {cell(q.currency)} | {q.date} | {fmt(q.close)} | {fmt(q.change, True)} | {fmt(q.percent, True)} | {volume} |")
    if failures:
        lines.extend(["", "## Symbols with unavailable data", ""])
        lines.extend(f"- {cell(symbol)}: {error}" for symbol, error in failures)
    return f"{now:%Y-%m-%d} Stock Watchlist", "\n".join(lines)


def main():
    settings = Settings.read()
    symbols = parse_symbols(get_input("symbols", required=True))
    quotes, failures = [], []
    for symbol in symbols:
        try:
            quotes.append(fetch_quote(symbol))
        except ActionError as exc:
            failures.append((symbol, str(exc)))
            annotation("warning", f"{symbol}: {exc}")
    if not quotes:
        raise ActionError("All stock symbols failed; no note created.")
    publish(settings, *render_quotes(quotes, failures, settings.now()))
    output("conclusion", "success")


if __name__ == "__main__":
    run(main)

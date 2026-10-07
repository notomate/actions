from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import yfinance as yf

import stocks
from common import ActionError


def history(prices=(100, 110), volumes=(10, 20)):
    return pd.DataFrame({"Close": prices, "Volume": volumes}, index=pd.date_range("2026-10-02", periods=len(prices), tz="America/New_York"))


def test_symbol_normalization():
    assert stocks.parse_symbols("aapl,2330.TW\nAAPL\n^GSPC,BRK-B") == ["AAPL", "2330.TW", "^GSPC", "BRK-B"]


@pytest.mark.parametrize("value", ["", " ,\n", "AAPL;echo hi", "AAPL MSFT", "$(secret)", ",".join(f"S{i}" for i in range(51))])
def test_bad_symbols(value):
    with pytest.raises(ActionError):
        stocks.parse_symbols(value)


def test_change_and_exchange_date():
    q = stocks.extract_quote("AAPL", history(), {"currency": "USD"})
    assert (q.close, q.change, q.percent, q.volume) == (110, 10, 10, 20)
    assert q.date == "2026-10-03"
    _, text, data = stocks.render_quotes([q], [("BAD", "unavailable")], datetime(2026, 10, 6, tzinfo=ZoneInfo("Asia/Taipei")))
    assert "2026-10-03" in text and "Daily data may be incomplete" in text
    assert data["quotes"] == [{"symbol": "AAPL", "currency": "USD", "date": "2026-10-03", "close": 110,
                               "change": 10, "percent": 10, "volume": 20}]
    assert data["failures"] == [{"symbol": "BAD", "error": "unavailable"}]


@pytest.mark.parametrize("prices,volumes", [([100], [float("nan")]), ([float("nan"), 100], [10, None])])
def test_missing_values_not_zero(prices, volumes):
    q = stocks.extract_quote("AAPL", history(prices, volumes), {})
    assert q.change is None and q.percent is None and q.volume is None
    assert q.currency == "N/A"


def test_zero_previous_price_does_not_divide_by_zero():
    assert stocks.extract_quote("AAPL", history([0, 100]), {}).percent is None


@pytest.mark.parametrize("data", [pd.DataFrame(), history([100, float("nan")])])
def test_empty_or_latest_missing_price(data):
    with pytest.raises(ActionError):
        stocks.extract_quote("BAD", data, {})


def test_fetch_sets_unadjusted_prices_and_timeout(monkeypatch):
    ticker = Mock()
    ticker.history.return_value = history()
    ticker.get_history_metadata.return_value = {"currency": "USD"}
    monkeypatch.setattr(yf, "Ticker", Mock(return_value=ticker))
    assert stocks.fetch_quote("AAPL").close == 110
    ticker.history.assert_called_once_with(period="1mo", interval="1d", auto_adjust=False, timeout=20, raise_errors=True)


def test_rate_limit_retries(monkeypatch):
    from yfinance.exceptions import YFRateLimitError
    ticker = Mock()
    ticker.history.side_effect = [YFRateLimitError(), history()]
    ticker.get_history_metadata.return_value = {}
    monkeypatch.setattr(yf, "Ticker", Mock(return_value=ticker))
    monkeypatch.setattr(stocks.time, "sleep", lambda _: None)
    assert stocks.fetch_quote("AAPL").close == 110
    assert ticker.history.call_count == 2


@pytest.mark.parametrize("all_fail", [False, True])
def test_partial_and_total_failure(outputs, monkeypatch, all_fail):
    monkeypatch.setenv("INPUT_SYMBOLS", "AAPL,BAD")
    quote = stocks.extract_quote("AAPL", history(), {})
    monkeypatch.setattr(stocks, "fetch_quote", Mock(side_effect=[ActionError("unavailable") if all_fail else quote, ActionError("unavailable")]))
    if all_fail:
        with pytest.raises(ActionError, match="All stock symbols failed"):
            stocks.main()
        assert "content" not in outputs()
    else:
        stocks.main()
        values = outputs()
        assert "AAPL" in values["content"] and "BAD: unavailable" in values["content"]
        assert values["conclusion"] == "success" and values["title"].endswith(" Stock Watchlist")

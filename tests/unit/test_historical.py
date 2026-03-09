import pandas as pd

from historical import HistoricalCache, HistoricalDataFetcher


class _FakeClient:
    def __init__(self):
        self.calls = 0

    def get_historical_data_v2(self, **kwargs):
        self.calls += 1
        rows = []
        start = pd.to_datetime(kwargs["from_date"])
        end = pd.to_datetime(kwargs["to_date"])
        cur = start
        while cur <= end:
            rows.append(
                {
                    "datetime": cur.strftime("%Y-%m-%d"),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000,
                }
            )
            cur += pd.Timedelta(days=1)
        return {"success": True, "data": {"Success": rows}}


def test_fetch_daily_uses_single_call_and_parses():
    client = _FakeClient()
    fetcher = HistoricalDataFetcher(client, cache=HistoricalCache(ttl_seconds=600))

    df = fetcher.fetch(
        stock_code="NIFTY",
        exchange_code="NSE",
        product_type="cash",
        from_date="2025-01-01",
        to_date="2025-12-31",
        interval="1day",
    )

    assert len(df) >= 250
    assert client.calls == 1
    assert fetcher.last_api_calls == 1


def test_fetch_cache_hit_second_call_uses_zero_api_calls():
    client = _FakeClient()
    cache = HistoricalCache(ttl_seconds=600)
    fetcher = HistoricalDataFetcher(client, cache=cache)

    kwargs = dict(
        stock_code="NIFTY",
        exchange_code="NSE",
        product_type="cash",
        from_date="2025-01-01",
        to_date="2025-12-31",
        interval="1day",
    )

    df1 = fetcher.fetch(**kwargs)
    assert not df1.empty
    assert fetcher.last_api_calls == 1

    _ = fetcher.fetch(**kwargs)
    assert fetcher.last_api_calls == 0
    assert client.calls == 1


def test_intraday_chunking_is_bounded():
    client = _FakeClient()
    fetcher = HistoricalDataFetcher(client, cache=HistoricalCache(ttl_seconds=0))

    _ = fetcher.fetch(
        stock_code="NIFTY",
        exchange_code="NSE",
        product_type="cash",
        from_date="2025-01-01",
        to_date="2025-04-30",
        interval="30minute",
    )

    assert fetcher.last_api_calls <= 5


def test_fetch_converts_datetime_to_ist_timezone():
    client = _FakeClient()
    fetcher = HistoricalDataFetcher(client, cache=HistoricalCache(ttl_seconds=600))

    df = fetcher.fetch(
        stock_code="NIFTY",
        exchange_code="NSE",
        product_type="cash",
        from_date="2025-01-01",
        to_date="2025-01-03",
        interval="1day",
    )

    assert not df.empty
    assert str(df["datetime"].dt.tz) == "Asia/Kolkata"

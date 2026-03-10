from historical import HistoricalCache


def test_cache_auto_purge_runs_every_500_misses():
    cache = HistoricalCache(ttl_seconds=1)
    calls = []

    original = cache.purge_expired

    def wrapped():
        calls.append(1)
        return original()

    cache.purge_expired = wrapped  # type: ignore[method-assign]

    for i in range(500):
        assert cache.get({"k": i}) is None

    assert len(calls) == 1

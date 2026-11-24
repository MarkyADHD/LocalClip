import asyncio

import httpx

from src import usage_count


def test_counts_once_per_install_and_month_unless_turned_off(monkeypatch, tmp_path):
    hits = []

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get(self, url):
            hits.append(url)
            return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(usage_count, "_file", lambda: tmp_path / "usage_count.json")
    monkeypatch.setattr(usage_count.httpx, "AsyncClient", Client)
    monkeypatch.setenv("LOCALCLIP_NATIVE", "1")

    usage_count.set_choice(False)
    asyncio.run(usage_count.ping())  # turned off in Settings
    assert hits == []

    (tmp_path / "usage_count.json").unlink()
    asyncio.run(usage_count.ping())  # fresh install: on by default
    assert [h.rsplit("/", 1)[1][:7] for h in hits] == ["install", "active-"], hits
    asyncio.run(usage_count.ping())  # same month: nothing more
    assert len(hits) == 2

    monkeypatch.delenv("LOCALCLIP_NATIVE")  # dev / Docker never counts
    (tmp_path / "usage_count.json").unlink()
    asyncio.run(usage_count.ping())
    assert len(hits) == 2

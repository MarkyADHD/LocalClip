import asyncio

import httpx

from src import usage_count


def test_nothing_is_sent_until_the_user_says_yes(monkeypatch, tmp_path):
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

    asyncio.run(usage_count.ping())  # not asked yet
    usage_count.set_choice(False)
    asyncio.run(usage_count.ping())  # said no
    assert hits == []

    usage_count.set_choice(True)
    asyncio.run(usage_count.ping())
    assert [h.rsplit("/", 1)[1][:7] for h in hits] == ["install", "active-"], hits
    asyncio.run(usage_count.ping())  # same month: nothing more
    assert len(hits) == 2

    monkeypatch.delenv("LOCALCLIP_NATIVE")  # dev / Docker never counts
    usage_count._save({"enabled": True})
    asyncio.run(usage_count.ping())
    assert len(hits) == 2

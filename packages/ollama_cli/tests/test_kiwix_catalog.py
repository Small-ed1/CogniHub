from typing import Any, Dict

import pytest

from ollama_cli.tools.kiwix_tools import KiwixTools


class _Resp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_catalog_search_books_parses_opds_entries(monkeypatch: Any) -> None:
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Wikipedia</title>
        <link href="/content/wikipedia_en_all_nopic_2025-12" />
      </entry>
      <entry>
        <title>Python Docs</title>
        <link href="/content/python" />
      </entry>
    </feed>
    """

    kt = KiwixTools(kiwix_url="http://127.0.0.1:1")

    def fake_get(url: str, params: Dict[str, Any], timeout: int) -> _Resp:  # type: ignore[override]
        assert url.endswith("/catalog/search")
        assert params["query"] == "wikipedia"
        return _Resp(xml)

    monkeypatch.setattr(kt.session, "get", fake_get)
    out = kt.catalog_search_books("wikipedia", count=10)
    assert out[0]["zim_id"] == "wikipedia_en_all_nopic_2025-12"
    assert out[0]["title"] == "Wikipedia"
    assert out[1]["zim_id"] == "python"


def test_ping_false_on_exception(monkeypatch: Any) -> None:
    kt = KiwixTools(kiwix_url="http://127.0.0.1:1")

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("nope")

    monkeypatch.setattr(kt.session, "get", boom)
    assert kt.ping() is False


def test_search_xml_parses_rss_and_decodes_paths(monkeypatch: Any) -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Example Plus</title>
          <link>/content/wikipedia_en_all_nopic_2025-12/Example%2BPlus</link>
          <description>Some snippet</description>
        </item>
      </channel>
    </rss>
    """

    kt = KiwixTools(kiwix_url="http://127.0.0.1:1")

    def fake_get(url: str, params: Dict[str, Any], timeout: int) -> _Resp:  # type: ignore[override]
        assert url.endswith("/search")
        assert params["content"] == "wikipedia_en_all_nopic_2025-12"
        return _Resp(xml)

    monkeypatch.setattr(kt.session, "get", fake_get)
    out = kt.search_xml("example", "wikipedia_en_all_nopic_2025-12", count=3, start=0)
    assert out
    assert out[0].url == "Example+Plus"


def test_search_rss_library_wide_parses_zim_and_path(monkeypatch: Any) -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Example Title</title>
          <link>/content/archwiki/Some%20Page</link>
          <description>Snippet</description>
        </item>
      </channel>
    </rss>
    """

    kt = KiwixTools(kiwix_url="http://127.0.0.1:1")

    def fake_get(url: str, params: Dict[str, Any], timeout: int) -> _Resp:  # type: ignore[override]
        assert url.endswith("/search")
        assert "content" not in params
        return _Resp(xml)

    monkeypatch.setattr(kt.session, "get", fake_get)
    rows = kt.search_rss("example", zim=None, count=3, start=0)
    assert rows
    assert rows[0]["zim"] == "archwiki"
    assert rows[0]["path"] == "Some Page"

import json

from config.settings import load_sources


def test_load_sources_filters(tmp_path) -> None:
    data = {
        "rss_feeds": [
            {"name": "A", "url": "http://a"},
            {"name": "", "url": "http://b"},
            "notadict",
            {"url": "http://c"},
        ]
    }
    p = tmp_path / "sources.json"
    p.write_text(json.dumps(data))
    result = load_sources(p)
    assert result == [{"name": "A", "url": "http://a"}]

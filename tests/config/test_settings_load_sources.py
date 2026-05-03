import json

from config.settings import Settings, load_sources


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


def test_settings_accepts_repo_variable_names(monkeypatch) -> None:
    monkeypatch.setenv("MODELS_API_TOKEN", "token")
    monkeypatch.setenv("MODELS_BASE_URL", "https://example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    settings = Settings()  # pyright: ignore[reportCallIssue]

    assert settings.github_models_token == "token"
    assert settings.github_models_base_url == "https://example.com"

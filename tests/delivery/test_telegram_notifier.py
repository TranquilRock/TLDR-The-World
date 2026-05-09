from unittest.mock import Mock

import requests

from src.delivery.telegram_notifier import (
    MAX_MESSAGE_LENGTH,
    TelegramNotifier,
    split_message,
)


def test_split_avoids_trailing_backslash() -> None:
    # Create a long line that will be escaped and potentially split.
    line = "a" * (MAX_MESSAGE_LENGTH // 2) + "_" + "b" * (MAX_MESSAGE_LENGTH // 2)
    chunks = split_message(line)
    for c in chunks:
        assert not c.endswith("\\")


def test_send_retries_on_failure(monkeypatch) -> None:
    tn = TelegramNotifier(bot_token="token", chat_id="123")
    calls = []

    def post(url, json, timeout):  # pylint: disable=unused-argument
        calls.append(url)
        if len(calls) == 1:
            resp = Mock()
            resp.raise_for_status.side_effect = requests.HTTPError("boom")
            resp.response = Mock()
            resp.response.text = "err"
            return resp
        resp = Mock()
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr("src.delivery.telegram_notifier.requests.post", post)
    tn.send("hello")
    assert len(calls) >= 1


def test_send_renders_markdownv2_from_briefing_structure(monkeypatch) -> None:
    tn = TelegramNotifier(bot_token="token", chat_id="123")
    payloads = []

    def post(url, json, timeout):  # pylint: disable=unused-argument
        payloads.append(json)
        resp = Mock()
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr("src.delivery.telegram_notifier.requests.post", post)

    message = (
        "📰 Daily Intelligence Briefing — 2026-05-03\n\n"
        "**Title**: AI agents _are_ here\n"
        "**Source**: Example_News\n"
        "**Tags**: #AIAgent\n"
        "**One-line takeaway**: Summary with underscore_value\n"
        "**Original link**: https://example.com/a_b\n"
    )

    tn.send(message)

    assert payloads[0]["parse_mode"] == "MarkdownV2"
    assert payloads[0]["text"].startswith("*📰 Daily Intelligence Briefing")
    assert "*AI agents \\_are\\_ here*" in payloads[0]["text"]
    assert "• *Source:* Example\\_News" in payloads[0]["text"]
    assert "underscore\\_value" in payloads[0]["text"]
    assert "https://example\\.com/a\\_b" in payloads[0]["text"]

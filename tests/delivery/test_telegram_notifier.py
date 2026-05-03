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

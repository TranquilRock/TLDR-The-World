from types import SimpleNamespace

from config.settings import Settings
from src.processing.llm_summarizer import LlmSummarizer


def test_call_model_retries_on_429(monkeypatch) -> None:
    settings = SimpleNamespace(
        github_models_token="x",
        github_models_base_url="y",
        llm_model="m",
        github_models_min_interval_seconds=0,
        github_models_retry_max_attempts=3,
        github_models_retry_backoff_base_seconds=0.01,
        github_models_retry_backoff_max_seconds=0.05,
    )

    s = LlmSummarizer(settings)  # type: ignore[arg-type]

    calls = {"n": 0}

    def create(**_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            e = Exception("429 Too Many Requests")
            setattr(e, "status_code", 429)
            raise e
        return {"choices": [{"message": {"content": "Recovered"}}]}

    mock_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    s._client = mock_client  # type: ignore[attr-defined]

    slept = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("src.processing.llm_summarizer.time.sleep", fake_sleep)
    # make jitter deterministic
    monkeypatch.setattr(
        "src.processing.llm_summarizer.random.uniform", lambda a, b: 0.0
    )

    resp = s._call_model(messages=[{"role": "user", "content": "hi"}], max_tokens=10)

    assert resp == "Recovered"
    # two failures then one success -> create called 3 times
    assert calls["n"] == 3
    # sleep should have been called for the two backoff attempts
    assert len(slept) == 2

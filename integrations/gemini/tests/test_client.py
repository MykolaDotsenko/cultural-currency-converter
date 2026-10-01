from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from integrations.gemini import client as client_module
from integrations.gemini.client import GeminiStructuredClient
from integrations.gemini.errors import (
    AIConfigurationError,
    AIInvalidResponse,
    AIProviderTimeout,
    AIRateLimited,
    AIRefusal,
    AISafetyBlocked,
)


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _response(*, parsed=None, text=None, blocked=False, finish_reason="STOP"):
    return SimpleNamespace(
        parsed=parsed,
        text=text,
        prompt_feedback=SimpleNamespace(block_reason="SAFETY" if blocked else None),
        candidates=(SimpleNamespace(finish_reason=finish_reason),),
        usage_metadata=SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=5,
            total_token_count=15,
        ),
        model_version="gemini-model-snapshot",
        response_id="response-id",
    )


def _build_client(monkeypatch, outcomes, *, max_attempts=2):
    fake_models = FakeModels(outcomes)
    fake_sdk_client = SimpleNamespace(models=fake_models)
    monkeypatch.setattr(
        client_module.genai,
        "Client",
        lambda **kwargs: fake_sdk_client,
    )
    client = GeminiStructuredClient(
        api_key="server-secret",
        timeout_seconds=3,
        max_attempts=max_attempts,
    )
    return client, fake_models


def _generate(client):
    return client.generate_json(
        model="gemini-3.1-flash-lite",
        system_instruction="Use trusted facts only.",
        contents='SOURCE_PACKET {"facts":[]}',
        response_json_schema={
            "type": "object",
            "properties": {"headline": {"type": "string"}},
            "required": ["headline"],
        },
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": "", "timeout_seconds": 3, "max_attempts": 2},
        {"api_key": "key", "timeout_seconds": 0.1, "max_attempts": 2},
        {"api_key": "key", "timeout_seconds": 3, "max_attempts": 3},
    ],
)
def test_client_rejects_invalid_configuration(kwargs):
    with pytest.raises(AIConfigurationError):
        GeminiStructuredClient(**kwargs)


def test_client_returns_parsed_structured_output_and_usage(monkeypatch):
    client, fake_models = _build_client(
        monkeypatch,
        [_response(parsed={"headline": "Grounded"})],
    )

    generation = _generate(client)

    assert generation.data == {"headline": "Grounded"}
    assert generation.provider_model == "gemini-model-snapshot"
    assert generation.response_id == "response-id"
    assert generation.usage.input_tokens == 10
    assert generation.usage.output_tokens == 5
    assert generation.usage.total_tokens == 15
    assert len(fake_models.calls) == 1
    assert fake_models.calls[0]["model"] == "gemini-3.1-flash-lite"
    assert fake_models.calls[0]["config"].response_mime_type == "application/json"
    assert not getattr(fake_models.calls[0]["config"], "tools", None)


def test_client_supports_schema_constrained_ephemeral_image_input(monkeypatch):
    client, fake_models = _build_client(
        monkeypatch,
        [_response(parsed={"status": "candidate"})],
    )

    generation = client.generate_json_with_image(
        model="gemini-3.1-flash-lite",
        system_instruction="Extract one price only.",
        contents="Inspect the supplied image.",
        image_bytes=b"safe-image-bytes",
        image_mime_type="image/png",
        response_json_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        },
    )

    assert generation.data == {"status": "candidate"}
    assert len(fake_models.calls) == 1
    call = fake_models.calls[0]
    assert not isinstance(call["contents"], str)
    assert call["config"].temperature == 0.0
    assert call["config"].response_mime_type == "application/json"


@pytest.mark.parametrize(
    ("image_bytes", "mime_type"),
    [
        (b"", "image/png"),
        (b"data", "image/gif"),
        (b"data", "text/plain"),
    ],
)
def test_client_rejects_invalid_multimodal_image_input(monkeypatch, image_bytes, mime_type):
    client, fake_models = _build_client(
        monkeypatch,
        [_response(parsed={"status": "candidate"})],
    )

    with pytest.raises(AIConfigurationError):
        client.generate_json_with_image(
            model="gemini-3.1-flash-lite",
            system_instruction="Extract one price only.",
            contents="Inspect the supplied image.",
            image_bytes=image_bytes,
            image_mime_type=mime_type,
            response_json_schema={"type": "object"},
        )

    assert fake_models.calls == []


def test_client_can_decode_json_text_when_parsed_value_is_unavailable(monkeypatch):
    client, _ = _build_client(
        monkeypatch,
        [_response(text=json.dumps({"headline": "Grounded"}))],
    )

    assert _generate(client).data == {"headline": "Grounded"}


def test_malformed_or_empty_output_is_normalized(monkeypatch):
    malformed, _ = _build_client(monkeypatch, [_response(text="{bad")], max_attempts=1)
    with pytest.raises(AIInvalidResponse):
        _generate(malformed)

    empty, _ = _build_client(monkeypatch, [_response(text=None)], max_attempts=1)
    with pytest.raises(AIRefusal):
        _generate(empty)


def test_safety_block_is_normalized(monkeypatch):
    client, _ = _build_client(
        monkeypatch,
        [_response(text=None, blocked=True)],
        max_attempts=1,
    )

    with pytest.raises(AISafetyBlocked):
        _generate(client)


def test_429_never_retries(monkeypatch):
    class FakeAPIError(Exception):
        def __init__(self, code):
            self.code = code

    monkeypatch.setattr(client_module.errors, "APIError", FakeAPIError)
    client, fake_models = _build_client(
        monkeypatch,
        [FakeAPIError(429), _response(parsed={"headline": "should not run"})],
    )

    with pytest.raises(AIRateLimited):
        _generate(client)

    assert len(fake_models.calls) == 1


def test_transient_503_retries_once_then_succeeds(monkeypatch):
    class FakeAPIError(Exception):
        def __init__(self, code):
            self.code = code

    monkeypatch.setattr(client_module.errors, "APIError", FakeAPIError)
    client, fake_models = _build_client(
        monkeypatch,
        [FakeAPIError(503), _response(parsed={"headline": "Recovered"})],
    )

    assert _generate(client).data["headline"] == "Recovered"
    assert len(fake_models.calls) == 2


def test_timeout_retries_only_within_bound(monkeypatch):
    client, fake_models = _build_client(
        monkeypatch,
        [httpx.TimeoutException("slow"), httpx.TimeoutException("still slow")],
    )

    with pytest.raises(AIProviderTimeout):
        _generate(client)

    assert len(fake_models.calls) == 2


def test_authentication_error_is_configuration_failure(monkeypatch):
    class FakeAPIError(Exception):
        def __init__(self, code):
            self.code = code

    monkeypatch.setattr(client_module.errors, "APIError", FakeAPIError)
    client, fake_models = _build_client(monkeypatch, [FakeAPIError(401)])

    with pytest.raises(AIConfigurationError):
        _generate(client)

    assert len(fake_models.calls) == 1


def test_missing_usage_metadata_is_not_a_domain_failure(monkeypatch):
    response = _response(parsed={"headline": "Grounded"})
    response.usage_metadata = None
    response.response_id = None
    client, _ = _build_client(monkeypatch, [response])

    generation = _generate(client)

    assert generation.usage.input_tokens is None
    assert generation.usage.output_tokens is None
    assert generation.usage.total_tokens is None
    assert generation.response_id is None

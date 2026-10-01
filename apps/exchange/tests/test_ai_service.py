from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.test import override_settings

from apps.exchange.ai.contracts import ProviderExplanation
from apps.exchange.ai.service import (
    AITransactionPolicyError,
    RuntimeExplanationService,
    build_runtime_explanation_service,
)
from apps.exchange.domain import ObservationGranularity
from apps.exchange.models import RuntimeExplanationCache
from apps.exchange.trusted_snapshot import TrustedConversionSnapshot
from integrations.gemini.errors import AIProviderUnavailable
from integrations.gemini.models import ProviderUsage


@pytest.fixture(autouse=True)
def clear_ai_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def snapshot():
    return TrustedConversionSnapshot(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("17450"),
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.50"),
        requested_date=None,
        effective_date=date(2026, 9, 18),
        historical=False,
        observation_granularity=ObservationGranularity.DAILY,
        provider_keys=("ecb",),
        stale=False,
    )


def _payload():
    return {
        "short_answer": {
            "text": "100 EUR is approximately 17450 JPY.",
            "supporting_fact_ids": ["conversion"],
        },
        "key_factors": [
            {
                "text": "The displayed rate is 1 EUR = 174.5 JPY and attribution includes ECB.",
                "supporting_fact_ids": ["rate", "provider"],
            },
            {
                "text": "The effective observation date is 2026-09-18.",
                "supporting_fact_ids": ["effective_date"],
            },
        ],
        "watch_out_for": {
            "text": (
                "Reference exchange rates are informational; payment providers may use different "
                "rates or add fees."
            ),
            "supporting_fact_ids": ["reference_scope"],
        },
        "next_step": {
            "text": "Use this reference observation as a comparison point for any provider quote.",
            "supporting_fact_ids": ["reference_scope"],
        },
    }


class FakeDrafter:
    def __init__(self, *, payload=None, error=None):
        self.payload = payload or _payload()
        self.error = error
        self.calls = 0

    def draft(self, packet):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ProviderExplanation(
            payload=self.payload,
            provider_model="gemini-3.1-flash-lite-2026-05",
            response_id="response-1",
            usage=ProviderUsage(input_tokens=120, output_tokens=60, total_tokens=180),
        )


@pytest.mark.django_db(transaction=True)
def test_live_explanation_is_validated_persisted_reused_and_observable(snapshot, caplog):
    drafter = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    with caplog.at_level(logging.INFO, logger="cultural_currency.ai"):
        first = service.explain(snapshot)
        second = service.explain(snapshot)

    assert first.result.generated is True
    assert first.cache_status == "live"
    assert second.cache_status == "persistent_hit"
    assert drafter.calls == 1

    stored = RuntimeExplanationCache.objects.get()
    assert stored.provider == "google"
    assert stored.model == "gemini-3.1-flash-lite"
    assert stored.provider_model_version == "gemini-3.1-flash-lite-2026-05"
    assert stored.input_tokens == 120
    assert stored.output_tokens == 60
    assert stored.total_tokens == 180
    assert stored.provider_response_id == "response-1"

    success = next(
        record for record in caplog.records if record.msg == "AI runtime explanation success"
    )
    assert success.capability == "runtime_explanation"
    assert success.provider == "google"
    assert success.model == "gemini-3.1-flash-lite"
    assert success.operation == "generate"
    assert success.outcome == "success"
    assert success.latency_ms >= 0
    assert success.input_tokens == 120
    assert success.output_tokens == 60
    assert not hasattr(success, "packet_hash")
    assert not hasattr(success, "ai.input_hash")

    cache_hit = next(
        record for record in caplog.records if record.msg == "AI runtime explanation cache hit"
    )
    assert cache_hit.operation == "persistent_cache_read"
    assert cache_hit.outcome == "success"
    assert cache_hit.cache_status == "persistent_hit"


@pytest.mark.django_db(transaction=True)
def test_provider_failure_returns_deterministic_fallback_sets_cooldown_and_logs(snapshot, caplog):
    drafter = FakeDrafter(error=AIProviderUnavailable("down"))
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    with caplog.at_level(logging.WARNING, logger="cultural_currency.ai"):
        first = service.explain(snapshot)
        second = service.explain(snapshot)

    assert first.result.generated is False
    assert first.cache_status == "deterministic_fallback"
    assert "temporarily unavailable" in first.result.fallback_reason
    assert second.result.generated is False
    assert "cooling down" in second.result.fallback_reason
    assert drafter.calls == 1
    assert RuntimeExplanationCache.objects.count() == 0

    fallback = next(
        record for record in caplog.records if record.msg == "AI runtime explanation fallback"
    )
    assert fallback.capability == "runtime_explanation"
    assert fallback.provider == "google"
    assert fallback.model == "gemini-3.1-flash-lite"
    assert fallback.operation == "generate"
    assert fallback.outcome == "AIProviderUnavailable"
    assert fallback.latency_ms >= 0


@pytest.mark.django_db(transaction=True)
def test_schema_valid_but_semantically_invalid_output_falls_back(snapshot):
    payload = _payload()
    payload["short_answer"]["supporting_fact_ids"] = ["invented_fact"]
    drafter = FakeDrafter(payload=payload)
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    delivery = service.explain(snapshot)

    assert delivery.result.generated is False
    assert RuntimeExplanationCache.objects.count() == 0


@pytest.mark.django_db
def test_disabled_service_never_calls_provider(snapshot):
    drafter = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=False,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    delivery = service.explain(snapshot)

    assert delivery.result.generated is False
    assert "disabled" in delivery.result.fallback_reason
    assert drafter.calls == 0


@pytest.mark.django_db(transaction=True)
def test_corrupt_persistent_cache_is_deleted_before_live_generation(snapshot):
    drafter = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )
    service.explain(snapshot)
    stored = RuntimeExplanationCache.objects.get()
    stored.result = {
        "short_answer": {
            "text": "100 USD is better.",
            "supporting_fact_ids": ["conversion"],
        },
        "key_factors": [],
        "watch_out_for": {
            "text": "Bad cache.",
            "supporting_fact_ids": ["reference_scope"],
        },
        "next_step": {
            "text": "Bad cache.",
            "supporting_fact_ids": ["reference_scope"],
        },
    }
    stored.save(update_fields=("result",))

    replacement = FakeDrafter()
    second_service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=replacement,
    )
    delivery = second_service.explain(snapshot)

    assert delivery.cache_status == "live"
    assert replacement.calls == 1
    assert RuntimeExplanationCache.objects.count() == 1


@pytest.mark.django_db
def test_inflight_duplicate_uses_fallback_instead_of_second_provider_call(snapshot, monkeypatch):
    drafter = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )
    monkeypatch.setattr(cache, "add", lambda *args, **kwargs: False)

    delivery = service.explain(snapshot)

    assert delivery.result.generated is False
    assert "already being generated" in delivery.result.fallback_reason
    assert drafter.calls == 0


@pytest.mark.django_db(transaction=True)
def test_coordination_cache_outage_does_not_break_live_generation(snapshot, monkeypatch):
    drafter = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    deleted_keys = []

    def unavailable(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(cache, "get", unavailable)
    monkeypatch.setattr(cache, "add", unavailable)
    monkeypatch.setattr(cache, "delete", lambda key: deleted_keys.append(key))

    delivery = service.explain(snapshot)

    assert delivery.result.generated is True
    assert delivery.cache_status == "live"
    assert drafter.calls == 1
    assert deleted_keys == []
    assert RuntimeExplanationCache.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_coordination_cache_outage_preserves_provider_fallback(snapshot, monkeypatch):
    drafter = FakeDrafter(error=AIProviderUnavailable("down"))
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    deleted_keys = []

    def unavailable(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(cache, "get", unavailable)
    monkeypatch.setattr(cache, "add", unavailable)
    monkeypatch.setattr(cache, "set", unavailable)
    monkeypatch.setattr(cache, "delete", lambda key: deleted_keys.append(key))

    delivery = service.explain(snapshot)

    assert delivery.result.generated is False
    assert delivery.cache_status == "deterministic_fallback"
    assert "temporarily unavailable" in delivery.result.fallback_reason
    assert drafter.calls == 1
    assert deleted_keys == []
    assert RuntimeExplanationCache.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_persistent_cache_read_failure_does_not_break_live_generation(snapshot, caplog):
    drafter = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    with (
        caplog.at_level(logging.WARNING, logger="cultural_currency.ai"),
        patch(
            "apps.exchange.ai.service.RuntimeExplanationCache.objects.filter",
            side_effect=DatabaseError("database unavailable"),
        ),
    ):
        delivery = service.explain(snapshot)

    assert delivery.result.generated is True
    assert delivery.cache_status == "live"
    assert drafter.calls == 1
    assert RuntimeExplanationCache.objects.count() == 1
    record = next(
        record
        for record in caplog.records
        if record.msg == "AI persistent explanation cache read failed open"
    )
    assert record.dependency == "database"
    assert record.operation == "persistent_cache_read"
    assert record.cache_status == "persistent_unavailable"


@pytest.mark.django_db(transaction=True)
def test_persistent_cache_write_failure_returns_live_uncached_result(snapshot, caplog):
    drafter = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    with (
        caplog.at_level(logging.WARNING, logger="cultural_currency.ai"),
        patch(
            "apps.exchange.ai.service.RuntimeExplanationCache.objects.update_or_create",
            side_effect=DatabaseError("database unavailable"),
        ),
    ):
        delivery = service.explain(snapshot)

    assert delivery.result.generated is True
    assert delivery.cache_status == "live_uncached"
    assert drafter.calls == 1
    assert RuntimeExplanationCache.objects.count() == 0
    record = next(
        record
        for record in caplog.records
        if record.msg == "AI persistent explanation cache write failed open"
    )
    assert record.dependency == "database"
    assert record.operation == "persistent_cache_write"
    assert record.cache_status == "live_uncached"


@pytest.mark.django_db(transaction=True)
def test_invalid_persistent_cache_cleanup_failure_still_regenerates(snapshot, caplog):
    seed_service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=FakeDrafter(),
    )
    seed_service.explain(snapshot)
    stored = RuntimeExplanationCache.objects.get()
    stored.result = {
        "short_answer": {
            "text": "100 USD is better.",
            "supporting_fact_ids": ["conversion"],
        },
        "key_factors": [],
        "watch_out_for": {
            "text": "Bad cache.",
            "supporting_fact_ids": ["reference_scope"],
        },
        "next_step": {
            "text": "Bad cache.",
            "supporting_fact_ids": ["reference_scope"],
        },
    }
    stored.save(update_fields=("result",))

    replacement = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=replacement,
    )
    with (
        caplog.at_level(logging.WARNING, logger="cultural_currency.ai"),
        patch.object(
            RuntimeExplanationCache,
            "delete",
            side_effect=DatabaseError("delete unavailable"),
        ),
    ):
        delivery = service.explain(snapshot)

    assert delivery.result.generated is True
    assert delivery.cache_status == "live"
    assert replacement.calls == 1
    assert RuntimeExplanationCache.objects.count() == 1
    record = next(
        record
        for record in caplog.records
        if record.msg == "AI invalid persistent explanation cache cleanup failed"
    )
    assert record.operation == "persistent_cache_delete"
    assert record.cache_status == "invalid_persistent"


@pytest.mark.django_db(transaction=True)
def test_live_ai_call_is_rejected_inside_database_transaction(snapshot):
    drafter = FakeDrafter()
    service = RuntimeExplanationService(
        enabled=True,
        model="gemini-3.1-flash-lite",
        drafter=drafter,
    )

    with pytest.raises(AITransactionPolicyError), transaction.atomic():
        service.explain(snapshot)

    assert drafter.calls == 0


def test_service_factory_does_not_construct_provider_when_feature_disabled():
    with (
        override_settings(AI_RUNTIME_EXPLANATION_ENABLED=False),
        patch("apps.exchange.ai.service.GeminiStructuredClient") as client_factory,
    ):
        service = build_runtime_explanation_service()

    assert service.enabled is False
    client_factory.assert_not_called()


def test_service_factory_builds_configured_capability_when_enabled():
    fake_client = SimpleNamespace()
    with (
        override_settings(
            AI_RUNTIME_EXPLANATION_ENABLED=True,
            AI_TEXT_MODEL="gemini-3.1-flash-lite",
            GEMINI_API_KEY="server-secret",
            AI_TIMEOUT_SECONDS=4,
            AI_MAX_ATTEMPTS=2,
        ),
        patch(
            "apps.exchange.ai.service.GeminiStructuredClient",
            return_value=fake_client,
        ) as client_factory,
    ):
        service = build_runtime_explanation_service()

    assert service.enabled is True
    client_factory.assert_called_once_with(
        api_key="server-secret",
        timeout_seconds=4,
        max_attempts=2,
    )

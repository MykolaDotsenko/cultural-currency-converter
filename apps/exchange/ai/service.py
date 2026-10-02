from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, transaction

from apps.exchange.ai.contracts import (
    ExplanationDrafter,
    ExplanationInsight,
    ExplanationPacket,
    ExplanationResult,
)
from apps.exchange.ai.intents import ExplanationIntent, explanation_intent_spec
from apps.exchange.ai.packets import build_explanation_packet
from apps.exchange.ai.prompts import PROMPT_VERSION, SCHEMA_VERSION
from apps.exchange.ai.providers.deterministic_test import DeterministicTestExplanationDrafter
from apps.exchange.ai.providers.gemini import GeminiExplanationDrafter
from apps.exchange.ai.validation import (
    ExplanationValidationError,
    validate_provider_payload,
)
from apps.exchange.models import RuntimeExplanationCache
from apps.exchange.trusted_snapshot import TrustedConversionSnapshot
from integrations.gemini.client import GeminiStructuredClient
from integrations.gemini.errors import AIProviderError

logger = logging.getLogger("cultural_currency.ai")

_COOLDOWN_SECONDS = 120
_LOCK_SECONDS = 45  # Exceeds the configured maximum 15s x 2 provider attempt budget.


class AITransactionPolicyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExplanationDelivery:
    result: ExplanationResult
    cache_status: str
    packet_hash: str


class RuntimeExplanationService:
    def __init__(
        self,
        *,
        enabled: bool,
        model: str,
        drafter: ExplanationDrafter | None,
    ) -> None:
        self.enabled = enabled
        self.model = model
        self._drafter = drafter

    def explain(
        self,
        snapshot: TrustedConversionSnapshot,
        *,
        intent: ExplanationIntent = ExplanationIntent.OVERVIEW,
        locale: str = "en",
    ) -> ExplanationDelivery:
        packet = build_explanation_packet(snapshot, intent=intent, locale=locale)
        return self.explain_packet(
            packet,
            fallback_factory=lambda reason: _fallback_delivery(
                snapshot,
                intent=intent,
                packet_hash=packet.packet_hash,
                reason=reason,
            ).result,
            locale=locale,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            capability="runtime_explanation",
        )

    def explain_packet(
        self,
        packet: ExplanationPacket,
        *,
        fallback_factory: Callable[[str], ExplanationResult],
        locale: str = "en",
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
        capability: str = "runtime_explanation",
    ) -> ExplanationDelivery:
        cache_key = _persistent_cache_key(
            packet_hash=packet.packet_hash,
            model=self.model,
            locale=locale,
            prompt_version=prompt_version,
            schema_version=schema_version,
        )

        cached = _safe_persistent_cache_get(cache_key)
        if cached is not None:
            try:
                result = validate_provider_payload(cached.result, packet=packet)
            except ExplanationValidationError:
                logger.warning(
                    "Discarding invalid persisted AI explanation",
                    extra={
                        "capability": capability,
                        "provider": cached.provider,
                        "model": cached.model,
                        "operation": "persistent_cache_read",
                        "outcome": "invalid_cache",
                        "cache_status": "invalid_persistent",
                    },
                )
                _safe_persistent_cache_delete(cached)
            else:
                logger.info(
                    "AI grounded explanation cache hit",
                    extra={
                        "capability": capability,
                        "provider": cached.provider,
                        "model": cached.model,
                        "operation": "persistent_cache_read",
                        "outcome": "success",
                        "cache_status": "persistent_hit",
                    },
                )
                return ExplanationDelivery(
                    result=result,
                    cache_status="persistent_hit",
                    packet_hash=packet.packet_hash,
                )

        def fallback(reason: str) -> ExplanationDelivery:
            return ExplanationDelivery(
                result=fallback_factory(reason),
                cache_status="fallback",
                packet_hash=packet.packet_hash,
            )

        if not self.enabled or self._drafter is None:
            return fallback("AI explanation is disabled.")

        cooldown_key = f"ai:{capability}:cooldown:{packet.packet_hash}"
        if _safe_cache_get(cooldown_key):
            return fallback("Live AI is temporarily cooling down.")

        lock_key = f"ai:{capability}:lock:{cache_key}"
        lock_acquired = _safe_cache_add(lock_key, "1", timeout=_LOCK_SECONDS)
        if lock_acquired is False:
            return fallback("An identical explanation is already being generated.")

        try:
            connection = transaction.get_connection()
            if connection.in_atomic_block:
                raise AITransactionPolicyError(
                    "Live AI calls are forbidden inside database transactions."
                )

            started = time.perf_counter()
            try:
                provider_result = self._drafter.draft(packet)
                result = validate_provider_payload(provider_result.payload, packet=packet)
            except (AIProviderError, ExplanationValidationError) as exc:
                latency_ms = round((time.perf_counter() - started) * 1000)
                _safe_cache_set(
                    cooldown_key,
                    exc.__class__.__name__,
                    timeout=_COOLDOWN_SECONDS,
                )
                logger.warning(
                    "AI grounded explanation fallback",
                    extra={
                        "capability": capability,
                        "provider": "google",
                        "model": self.model,
                        "operation": "generate",
                        "outcome": exc.__class__.__name__,
                        "latency_ms": latency_ms,
                    },
                )
                return fallback("Live AI explanation is temporarily unavailable.")

            latency_ms = round((time.perf_counter() - started) * 1000)
            cache_status = "live"
            try:
                RuntimeExplanationCache.objects.update_or_create(
                    cache_key=cache_key,
                    defaults={
                        "packet_hash": packet.packet_hash,
                        "prompt_version": prompt_version,
                        "schema_version": schema_version,
                        "provider": "google",
                        "model": self.model,
                        "provider_model_version": provider_result.provider_model,
                        "locale": locale,
                        "result": provider_result.payload,
                        "input_tokens": provider_result.usage.input_tokens,
                        "output_tokens": provider_result.usage.output_tokens,
                        "total_tokens": provider_result.usage.total_tokens,
                        "provider_response_id": provider_result.response_id or "",
                    },
                )
            except DatabaseError:
                cache_status = "live_uncached"
                logger.warning(
                    "AI persistent explanation cache write failed open",
                    extra={
                        "capability": capability,
                        "dependency": "database",
                        "operation": "persistent_cache_write",
                        "outcome": "failure",
                        "cache_status": cache_status,
                    },
                    exc_info=True,
                )
            logger.info(
                "AI grounded explanation success",
                extra={
                    "capability": capability,
                    "provider": "google",
                    "model": self.model,
                    "operation": "generate",
                    "outcome": "success",
                    "latency_ms": latency_ms,
                    "input_tokens": provider_result.usage.input_tokens,
                    "output_tokens": provider_result.usage.output_tokens,
                    "cache_status": cache_status,
                },
            )
            return ExplanationDelivery(
                result=result,
                cache_status=cache_status,
                packet_hash=packet.packet_hash,
            )
        finally:
            if lock_acquired is True:
                _safe_cache_delete(lock_key)


def _safe_persistent_cache_get(cache_key: str) -> RuntimeExplanationCache | None:
    try:
        return RuntimeExplanationCache.objects.filter(cache_key=cache_key).first()
    except DatabaseError:
        logger.warning(
            "AI persistent explanation cache read failed open",
            extra={
                "capability": "runtime_explanation",
                "dependency": "database",
                "operation": "persistent_cache_read",
                "outcome": "failure",
                "cache_status": "persistent_unavailable",
            },
            exc_info=True,
        )
        return None


def _safe_persistent_cache_delete(cached: RuntimeExplanationCache) -> None:
    try:
        cached.delete()
    except DatabaseError:
        logger.warning(
            "AI invalid persistent explanation cache cleanup failed",
            extra={
                "capability": "runtime_explanation",
                "dependency": "database",
                "operation": "persistent_cache_delete",
                "outcome": "failure",
                "cache_status": "invalid_persistent",
            },
            exc_info=True,
        )


def _safe_cache_get(key: str) -> object | None:
    try:
        return cache.get(key)
    except Exception:
        logger.warning(
            "AI coordination cache read failed",
            extra={
                "capability": "runtime_explanation",
                "dependency": "cache",
                "cache_operation": "get",
                "outcome": "failure",
            },
            exc_info=True,
        )
        return None


def _safe_cache_add(key: str, value: object, *, timeout: int) -> bool | None:
    try:
        return bool(cache.add(key, value, timeout=timeout))
    except Exception:
        logger.warning(
            "AI coordination cache lock failed open",
            extra={
                "capability": "runtime_explanation",
                "dependency": "cache",
                "cache_operation": "add",
                "outcome": "failure",
            },
            exc_info=True,
        )
        return None


def _safe_cache_set(key: str, value: object, *, timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning(
            "AI coordination cache write failed",
            extra={
                "capability": "runtime_explanation",
                "dependency": "cache",
                "cache_operation": "set",
                "outcome": "failure",
            },
            exc_info=True,
        )


def _safe_cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:
        logger.warning(
            "AI coordination cache cleanup failed",
            extra={
                "capability": "runtime_explanation",
                "dependency": "cache",
                "cache_operation": "delete",
                "outcome": "failure",
            },
            exc_info=True,
        )


def build_runtime_explanation_service() -> RuntimeExplanationService:
    enabled = bool(settings.AI_RUNTIME_EXPLANATION_ENABLED)
    if not enabled:
        return RuntimeExplanationService(
            enabled=False,
            model=settings.AI_TEXT_MODEL,
            drafter=None,
        )

    if settings.AI_RUNTIME_TEST_FIXTURE_ENABLED:
        return RuntimeExplanationService(
            enabled=True,
            model="deterministic-browser-fixture",
            drafter=DeterministicTestExplanationDrafter(),
        )

    client = GeminiStructuredClient(
        api_key=settings.GEMINI_API_KEY,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
        max_attempts=settings.AI_MAX_ATTEMPTS,
    )
    drafter = GeminiExplanationDrafter(client=client, model=settings.AI_TEXT_MODEL)
    return RuntimeExplanationService(
        enabled=True,
        model=settings.AI_TEXT_MODEL,
        drafter=drafter,
    )


def _persistent_cache_key(
    *,
    packet_hash: str,
    model: str,
    locale: str,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    identity = "|".join((packet_hash, prompt_version, schema_version, model, locale))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _fallback_delivery(
    snapshot: TrustedConversionSnapshot,
    *,
    intent: ExplanationIntent,
    packet_hash: str,
    reason: str,
) -> ExplanationDelivery:
    spec = explanation_intent_spec(intent)
    reference_scope = ExplanationInsight(
        text=(
            "Reference exchange rates are informational. Payment providers may use different "
            "rates or add fees."
        ),
        supporting_fact_ids=("reference_scope",),
    )

    if intent is ExplanationIntent.RATE_MEANING:
        short_answer = ExplanationInsight(
            text=(
                f"The displayed reference rate is 1 {snapshot.base_currency} = "
                f"{format(snapshot.rate, 'f')} {snapshot.quote_currency}."
            ),
            supporting_fact_ids=("rate",),
        )
        key_factors = (
            ExplanationInsight(
                text=f"The effective observation date is {snapshot.effective_date.isoformat()}.",
                supporting_fact_ids=("effective_date",),
            ),
        )
        next_step = ExplanationInsight(
            text="Compare any provider quote with this reference observation and its effective date.",
            supporting_fact_ids=("reference_scope", "effective_date"),
        )
    elif intent is ExplanationIntent.PAYMENT_DIFFERENCE:
        short_answer = ExplanationInsight(
            text=(
                "The displayed exchange rate is a reference observation. A payment provider may "
                "use a different rate or add fees."
            ),
            supporting_fact_ids=("reference_scope",),
        )
        key_factors = (
            ExplanationInsight(
                text=(
                    f"The displayed reference rate is 1 {snapshot.base_currency} = "
                    f"{format(snapshot.rate, 'f')} {snapshot.quote_currency}."
                ),
                supporting_fact_ids=("rate",),
            ),
        )
        next_step = ExplanationInsight(
            text="Review the provider quote and fees alongside this reference observation.",
            supporting_fact_ids=("reference_scope",),
        )
    elif intent is ExplanationIntent.HISTORICAL_CONTEXT:
        short_answer = ExplanationInsight(
            text="This is a historical reference observation, not a current market quote.",
            supporting_fact_ids=("historical_status",),
        )
        factors = [
            ExplanationInsight(
                text=f"The accepted observation date is {snapshot.effective_date.isoformat()}.",
                supporting_fact_ids=("effective_date",),
            )
        ]
        if snapshot.requested_date is not None:
            factors.append(
                ExplanationInsight(
                    text=f"The requested historical date is {snapshot.requested_date.isoformat()}.",
                    supporting_fact_ids=("requested_date",),
                )
            )
        key_factors = tuple(factors)
        reference_scope = ExplanationInsight(
            text="Historical FX does not describe historical purchasing power.",
            supporting_fact_ids=("historical_scope",),
        )
        if snapshot.requested_date is not None:
            next_step = ExplanationInsight(
                text=(
                    "Read the requested and effective dates together when using this historical "
                    "reference."
                ),
                supporting_fact_ids=("requested_date", "effective_date"),
            )
        else:
            next_step = ExplanationInsight(
                text="Use the effective date when reading this historical reference.",
                supporting_fact_ids=("effective_date",),
            )
    elif intent is ExplanationIntent.STALE_REFERENCE:
        short_answer = ExplanationInsight(
            text=(
                "The displayed result is a labelled cached reference because a fresh provider "
                "response was unavailable."
            ),
            supporting_fact_ids=("stale_status",),
        )
        key_factors = (
            ExplanationInsight(
                text=f"The cached observation is effective {snapshot.effective_date.isoformat()}.",
                supporting_fact_ids=("effective_date",),
            ),
        )
        next_step = ExplanationInsight(
            text="Run the conversion again when a fresh reference observation is needed.",
            supporting_fact_ids=("stale_status",),
        )
    else:
        short_answer = ExplanationInsight(
            text=(
                f"{format(snapshot.input_amount, 'f')} {snapshot.base_currency} is approximately "
                f"{format(snapshot.output_amount, 'f')} {snapshot.quote_currency} at the displayed "
                "reference observation."
            ),
            supporting_fact_ids=("conversion",),
        )
        factors = [
            ExplanationInsight(
                text=(
                    f"The displayed reference rate is 1 {snapshot.base_currency} = "
                    f"{format(snapshot.rate, 'f')} {snapshot.quote_currency}."
                ),
                supporting_fact_ids=("rate",),
            )
        ]
        if snapshot.historical and snapshot.requested_date is not None:
            factors.append(
                ExplanationInsight(
                    text=(
                        f"You requested {snapshot.requested_date.isoformat()}; the accepted "
                        f"observation is {snapshot.effective_date.isoformat()}."
                    ),
                    supporting_fact_ids=("requested_date", "effective_date"),
                )
            )
            reference_scope = ExplanationInsight(
                text="Historical FX does not describe historical purchasing power.",
                supporting_fact_ids=("historical_scope",),
            )
        elif snapshot.stale:
            factors.append(
                ExplanationInsight(
                    text=(
                        "The displayed result is a labelled cached reference because a fresh "
                        "provider response was unavailable."
                    ),
                    supporting_fact_ids=("stale_status",),
                )
            )
        else:
            factors.append(
                ExplanationInsight(
                    text=f"The effective observation date is {snapshot.effective_date.isoformat()}.",
                    supporting_fact_ids=("effective_date",),
                )
            )
        key_factors = tuple(factors)
        next_step = ExplanationInsight(
            text="Use this reference observation as a comparison point for any provider quote.",
            supporting_fact_ids=("reference_scope",),
        )

    return ExplanationDelivery(
        result=ExplanationResult(
            short_answer=short_answer,
            key_factors=key_factors,
            watch_out_for=reference_scope,
            next_step=next_step,
            generated=False,
            source_label="Built-in explanation",
            fallback_reason=reason or spec.question,
        ),
        cache_status="deterministic_fallback",
        packet_hash=packet_hash,
    )

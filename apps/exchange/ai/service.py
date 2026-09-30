from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, transaction

from apps.exchange.ai.contracts import (
    ExplanationBullet,
    ExplanationDrafter,
    ExplanationResult,
)
from apps.exchange.ai.packets import build_explanation_packet
from apps.exchange.ai.prompts import PROMPT_VERSION, SCHEMA_VERSION
from apps.exchange.ai.providers.gemini import GeminiExplanationDrafter
from apps.exchange.ai.tokens import TrustedConversionSnapshot
from apps.exchange.ai.validation import (
    ExplanationValidationError,
    validate_provider_payload,
)
from apps.exchange.models import RuntimeExplanationCache
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
        locale: str = "en",
    ) -> ExplanationDelivery:
        packet = build_explanation_packet(snapshot, locale=locale)
        cache_key = _persistent_cache_key(
            packet_hash=packet.packet_hash,
            model=self.model,
            locale=locale,
        )

        cached = _safe_persistent_cache_get(cache_key)
        if cached is not None:
            try:
                result = validate_provider_payload(cached.result, packet=packet)
            except ExplanationValidationError:
                logger.warning(
                    "Discarding invalid persisted AI explanation",
                    extra={
                        "capability": "runtime_explanation",
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
                    "AI runtime explanation cache hit",
                    extra={
                        "capability": "runtime_explanation",
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

        if not self.enabled or self._drafter is None:
            return _fallback_delivery(
                snapshot,
                packet_hash=packet.packet_hash,
                reason="AI explanation is disabled.",
            )

        cooldown_key = f"ai:runtime-explanation:cooldown:{packet.packet_hash}"
        if _safe_cache_get(cooldown_key):
            return _fallback_delivery(
                snapshot,
                packet_hash=packet.packet_hash,
                reason="Live AI is temporarily cooling down.",
            )

        lock_key = f"ai:runtime-explanation:lock:{cache_key}"
        lock_acquired = _safe_cache_add(lock_key, "1", timeout=_LOCK_SECONDS)
        if lock_acquired is False:
            return _fallback_delivery(
                snapshot,
                packet_hash=packet.packet_hash,
                reason="An identical explanation is already being generated.",
            )

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
                    "AI runtime explanation fallback",
                    extra={
                        "capability": "runtime_explanation",
                        "provider": "google",
                        "model": self.model,
                        "operation": "generate",
                        "outcome": exc.__class__.__name__,
                        "latency_ms": latency_ms,
                    },
                )
                return _fallback_delivery(
                    snapshot,
                    packet_hash=packet.packet_hash,
                    reason="Live AI explanation is temporarily unavailable.",
                )

            latency_ms = round((time.perf_counter() - started) * 1000)
            cache_status = "live"
            try:
                RuntimeExplanationCache.objects.update_or_create(
                    cache_key=cache_key,
                    defaults={
                        "packet_hash": packet.packet_hash,
                        "prompt_version": PROMPT_VERSION,
                        "schema_version": SCHEMA_VERSION,
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
                        "capability": "runtime_explanation",
                        "dependency": "database",
                        "operation": "persistent_cache_write",
                        "outcome": "failure",
                        "cache_status": cache_status,
                    },
                    exc_info=True,
                )
            logger.info(
                "AI runtime explanation success",
                extra={
                    "capability": "runtime_explanation",
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


def _persistent_cache_key(*, packet_hash: str, model: str, locale: str) -> str:
    identity = "|".join((packet_hash, PROMPT_VERSION, SCHEMA_VERSION, model, locale))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _fallback_delivery(
    snapshot: TrustedConversionSnapshot,
    *,
    packet_hash: str,
    reason: str,
) -> ExplanationDelivery:
    bullet_specs: list[tuple[str, tuple[str, ...]]] = [
        (
            (
                f"{format(snapshot.input_amount, 'f')} {snapshot.base_currency} is approximately "
                f"{format(snapshot.output_amount, 'f')} {snapshot.quote_currency} at the displayed "
                "reference observation."
            ),
            ("conversion",),
        ),
        (
            (
                f"The displayed reference rate is 1 {snapshot.base_currency} = "
                f"{format(snapshot.rate, 'f')} {snapshot.quote_currency}."
            ),
            ("rate",),
        ),
    ]

    if snapshot.historical and snapshot.requested_date is not None:
        if snapshot.requested_date == snapshot.effective_date:
            bullet_specs.append(
                (
                    f"The historical observation date is {snapshot.effective_date.isoformat()}.",
                    ("effective_date", "historical_status"),
                )
            )
        else:
            bullet_specs.append(
                (
                    (
                        f"You requested {snapshot.requested_date.isoformat()}; the accepted "
                        f"observation is {snapshot.effective_date.isoformat()}."
                    ),
                    ("requested_date", "effective_date"),
                )
            )
    elif snapshot.stale:
        bullet_specs.append(
            (
                (
                    "The displayed result is a labelled cached reference because a fresh provider "
                    "response was unavailable."
                ),
                ("stale_status",),
            )
        )
    else:
        bullet_specs.append(
            (
                f"The effective observation date is {snapshot.effective_date.isoformat()}.",
                ("effective_date",),
            )
        )

    return ExplanationDelivery(
        result=ExplanationResult(
            headline="What this reference conversion means",
            bullets=tuple(
                ExplanationBullet(text=text, supporting_fact_ids=fact_ids)
                for text, fact_ids in bullet_specs
            ),
            caveat=(
                "Reference exchange rates are informational. Payment providers may use different "
                "rates or add fees."
            ),
            generated=False,
            source_label="Built-in explanation",
            fallback_reason=reason,
        ),
        cache_status="deterministic_fallback",
        packet_hash=packet_hash,
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.exchange.domain import ObservationGranularity
from apps.exchange.trusted_snapshot import TrustedConversionSnapshot


@dataclass(frozen=True, slots=True)
class RuntimeExplanationEvalCase:
    id: str
    snapshot: TrustedConversionSnapshot
    stored_output: dict[str, object]


def _insight(text: str, fact_ids: list[str]) -> dict[str, object]:
    return {"text": text, "supporting_fact_ids": fact_ids}


def _output(
    *,
    short_answer: tuple[str, list[str]],
    key_factors: list[tuple[str, list[str]]],
    watch_out_for: tuple[str, list[str]],
    next_step: tuple[str, list[str]],
) -> dict[str, object]:
    return {
        "short_answer": _insight(*short_answer),
        "key_factors": [_insight(text, fact_ids) for text, fact_ids in key_factors],
        "watch_out_for": _insight(*watch_out_for),
        "next_step": _insight(*next_step),
    }


RUNTIME_EXPLANATION_EVAL_CASES = (
    RuntimeExplanationEvalCase(
        id="current-eur-jpy",
        snapshot=TrustedConversionSnapshot(
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
        ),
        stored_output=_output(
            short_answer=("100 EUR is approximately 17450 JPY.", ["conversion"]),
            key_factors=[
                ("The displayed reference rate is 1 EUR = 174.5 JPY.", ["rate"]),
                ("The effective observation date is 2026-09-18.", ["effective_date"]),
            ],
            watch_out_for=(
                "Reference exchange rates are informational; payment providers may use different "
                "rates or add fees.",
                ["reference_scope"],
            ),
            next_step=(
                "Use this reference observation as a comparison point for any provider quote.",
                ["reference_scope"],
            ),
        ),
    ),
    RuntimeExplanationEvalCase(
        id="historical-weekend-fallback",
        snapshot=TrustedConversionSnapshot(
            input_amount=Decimal("100.00"),
            output_amount=Decimal("17450"),
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("174.50"),
            requested_date=date(1998, 6, 14),
            effective_date=date(1998, 6, 12),
            historical=True,
            observation_granularity=ObservationGranularity.DAILY,
            provider_keys=("ecb",),
            stale=False,
        ),
        stored_output=_output(
            short_answer=(
                "This is a historical reference observation, not a current market quote.",
                ["historical_status"],
            ),
            key_factors=[
                ("The requested historical date is 1998-06-14.", ["requested_date"]),
                ("The accepted observation date is 1998-06-12.", ["effective_date"]),
            ],
            watch_out_for=(
                "Historical FX does not describe historical purchasing power.",
                ["historical_scope"],
            ),
            next_step=(
                "Read the requested and effective dates together when using this historical "
                "reference.",
                ["requested_date", "effective_date"],
            ),
        ),
    ),
    RuntimeExplanationEvalCase(
        id="monthly-observation",
        snapshot=TrustedConversionSnapshot(
            input_amount=Decimal("50"),
            output_amount=Decimal("43.25"),
            base_currency="EUR",
            quote_currency="GBP",
            rate=Decimal("0.865"),
            requested_date=date(2020, 5, 31),
            effective_date=date(2020, 5, 1),
            historical=True,
            observation_granularity=ObservationGranularity.MONTHLY,
            provider_keys=("ecb",),
            stale=False,
        ),
        stored_output=_output(
            short_answer=(
                "This is a historical reference observation, not a current market quote.",
                ["historical_status"],
            ),
            key_factors=[
                ("The source observation frequency is monthly.", ["observation_frequency"]),
                ("The effective observation date is 2020-05-01.", ["effective_date"]),
            ],
            watch_out_for=(
                "Historical FX does not describe historical purchasing power.",
                ["historical_scope"],
            ),
            next_step=(
                "Read the requested and effective dates together when using this historical "
                "reference.",
                ["requested_date", "effective_date"],
            ),
        ),
    ),
    RuntimeExplanationEvalCase(
        id="labelled-stale-current",
        snapshot=TrustedConversionSnapshot(
            input_amount=Decimal("25"),
            output_amount=Decimal("29.25"),
            base_currency="EUR",
            quote_currency="USD",
            rate=Decimal("1.17"),
            requested_date=None,
            effective_date=date(2026, 9, 18),
            historical=False,
            observation_granularity=ObservationGranularity.DAILY,
            provider_keys=("ecb",),
            stale=True,
        ),
        stored_output=_output(
            short_answer=(
                "The displayed result is a labelled cached reference.",
                ["stale_status"],
            ),
            key_factors=[
                ("The displayed reference rate is 1 EUR = 1.17 USD.", ["rate"]),
                ("The effective observation date is 2026-09-18.", ["effective_date"]),
            ],
            watch_out_for=(
                "Reference exchange rates are informational; payment providers may use different "
                "rates or add fees.",
                ["reference_scope"],
            ),
            next_step=(
                "Run the conversion again when a fresh reference observation is needed.",
                ["stale_status"],
            ),
        ),
    ),
)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.exchange.trusted_snapshot import TrustedConversionSnapshot
from apps.exchange.domain import ObservationGranularity


@dataclass(frozen=True, slots=True)
class RuntimeExplanationEvalCase:
    id: str
    snapshot: TrustedConversionSnapshot
    stored_output: dict[str, object]


def _output(
    *,
    headline: str,
    bullets: list[tuple[str, list[str]]],
    caveat: str = (
        "Reference exchange rates are informational; payment providers may use different "
        "rates or add fees."
    ),
) -> dict[str, object]:
    return {
        "headline": headline,
        "bullets": [{"text": text, "supporting_fact_ids": fact_ids} for text, fact_ids in bullets],
        "caveat": caveat,
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
            headline="Reference conversion explained",
            bullets=[
                ("100 EUR is approximately 17450 JPY.", ["conversion"]),
                ("The displayed reference rate is 1 EUR = 174.5 JPY.", ["rate"]),
                ("The effective observation date is 2026-09-18.", ["effective_date"]),
            ],
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
            headline="Historical reference conversion",
            bullets=[
                ("100 EUR is approximately 17450 JPY.", ["conversion"]),
                ("The requested historical date is 1998-06-14.", ["requested_date"]),
                ("The accepted observation date is 1998-06-12.", ["effective_date"]),
            ],
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
            headline="Monthly historical reference",
            bullets=[
                ("50 EUR is approximately 43.25 GBP.", ["conversion"]),
                ("The source observation frequency is monthly.", ["observation_frequency"]),
                ("The effective observation date is 2020-05-01.", ["effective_date"]),
            ],
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
            headline="Cached reference conversion",
            bullets=[
                ("25 EUR is approximately 29.25 USD.", ["conversion"]),
                ("The displayed reference rate is 1 EUR = 1.17 USD.", ["rate"]),
                (
                    "The displayed result is a labelled cached reference.",
                    ["stale_status"],
                ),
            ],
        ),
    ),
)

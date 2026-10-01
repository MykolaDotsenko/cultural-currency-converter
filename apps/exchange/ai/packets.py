from __future__ import annotations

from apps.exchange.ai.contracts import ExplanationPacket, GroundedFact
from apps.exchange.ai.intents import ExplanationIntent, explanation_intent_spec
from apps.exchange.trusted_snapshot import TrustedConversionSnapshot

PACKET_VERSION = "exchange-conversion:v3"


def build_explanation_packet(
    snapshot: TrustedConversionSnapshot,
    *,
    intent: ExplanationIntent = ExplanationIntent.OVERVIEW,
    locale: str = "en",
) -> ExplanationPacket:
    intent_spec = explanation_intent_spec(intent)
    facts: list[GroundedFact] = [
        GroundedFact(
            id="conversion",
            statement=(
                f"{format(snapshot.input_amount, 'f')} {snapshot.base_currency} is approximately "
                f"{format(snapshot.output_amount, 'f')} {snapshot.quote_currency} using the "
                "reference observation supplied by the application."
            ),
        ),
        GroundedFact(
            id="rate",
            statement=(
                f"1 {snapshot.base_currency} = {format(snapshot.rate, 'f')} "
                f"{snapshot.quote_currency}."
            ),
        ),
        GroundedFact(
            id="effective_date",
            statement=f"The effective observation date is {snapshot.effective_date.isoformat()}.",
        ),
        GroundedFact(
            id="reference_scope",
            statement=(
                "Reference exchange-rate data is informational; payment providers may use "
                "different rates or add fees."
            ),
        ),
    ]

    if snapshot.historical and snapshot.requested_date is not None:
        facts.append(
            GroundedFact(
                id="requested_date",
                statement=f"The requested historical date is {snapshot.requested_date.isoformat()}.",
            )
        )
        facts.append(
            GroundedFact(
                id="historical_status",
                statement="This is a historical reference observation, not a current market quote.",
            )
        )
        facts.append(
            GroundedFact(
                id="historical_scope",
                statement="Historical FX does not describe historical purchasing power.",
            )
        )

    if snapshot.observation_granularity.value != "daily":
        facts.append(
            GroundedFact(
                id="observation_frequency",
                statement=(
                    f"The source observation frequency is {snapshot.observation_granularity.value}."
                ),
            )
        )

    if snapshot.provider_keys:
        facts.append(
            GroundedFact(
                id="provider",
                statement=(
                    "The application obtained this reference observation through Frankfurter "
                    "with provider attribution keys: "
                    + ", ".join(key.upper() for key in snapshot.provider_keys)
                    + "."
                ),
            )
        )
    else:
        facts.append(
            GroundedFact(
                id="provider",
                statement="This result does not require an external provider observation.",
            )
        )

    if snapshot.stale:
        facts.append(
            GroundedFact(
                id="stale_status",
                statement=(
                    "The displayed reference result is a labelled cached fallback because a fresh "
                    "provider response was unavailable."
                ),
            )
        )

    allowed_dates = [snapshot.effective_date.isoformat()]
    if snapshot.requested_date is not None:
        allowed_dates.append(snapshot.requested_date.isoformat())

    return ExplanationPacket(
        packet_version=PACKET_VERSION,
        locale=locale,
        intent_id=intent_spec.intent.value,
        intent_question=intent_spec.question,
        focus_instruction=intent_spec.focus_instruction,
        required_fact_ids=intent_spec.required_fact_ids,
        facts=tuple(facts),
        allowed_currencies=(snapshot.base_currency, snapshot.quote_currency),
        allowed_uppercase_tokens=tuple(key.upper() for key in snapshot.provider_keys),
        allowed_dates=tuple(sorted(set(allowed_dates))),
        allowed_numbers=(
            "1",
            format(snapshot.input_amount, "f"),
            format(snapshot.output_amount, "f"),
            format(snapshot.rate, "f"),
        ),
    )

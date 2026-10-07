from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.utils.formats import date_format

from apps.travel.models import SavedScenarioKind
from apps.travel.share_snapshot import ScenarioShareSnapshot


@dataclass(frozen=True, slots=True)
class ScenarioShareCard:
    kind_label: str
    scope_label: str
    input_text: str
    output_text: str
    relation_label: str
    relation_symbol: str
    rate_line: str
    status_label: str
    effective_date_label: str
    provider_label: str
    fetched_at_label: str
    trust_note: str
    title: str
    description: str
    output_font_size: int


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _output_font_size(text: str) -> int:
    length = len(text)
    if length <= 18:
        return 82
    if length <= 26:
        return 68
    if length <= 36:
        return 56
    return 46


def build_scenario_share_card(snapshot: ScenarioShareSnapshot) -> ScenarioShareCard:
    exact = snapshot.exact
    kind_label = (
        "Saved Shopping estimate"
        if snapshot.kind == SavedScenarioKind.SHOPPING
        else "Saved travel-money plan"
    )
    input_text = f"{_decimal_text(snapshot.input_amount)} {snapshot.base_currency}"
    output_text = f"{_decimal_text(snapshot.output_amount)} {snapshot.quote_currency}"
    relation_label = "equals" if exact else "approximately"
    relation_symbol = "=" if exact else "≈"
    rate_line = (
        f"1 {snapshot.base_currency} = {_decimal_text(snapshot.rate)} {snapshot.quote_currency}"
    )

    if exact:
        status_label = "Stored exact 1:1"
        provider_label = "No external rate source"
        trust_note = (
            "Stored immutable snapshot. The currencies are identical, so this uses an exact "
            "1:1 identity rate."
        )
    else:
        provider_label = ", ".join(key.upper() for key in snapshot.provider_keys)
        status_label = "Stored cached reference" if snapshot.stale else "Stored reference"
        trust_note = (
            "This is an immutable saved reference, not a live quote. Opening the link performs "
            "no rate refresh; payment providers may use different rates or add fees."
        )

    effective_date_label = date_format(snapshot.effective_date, "j M Y")
    fetched_at_label = snapshot.fetched_at.strftime("%d %b %Y · %H:%M UTC")
    title = f"{snapshot.scope_label} · {kind_label} · Cultural Currency"
    description = (
        f"{snapshot.scope_label}: {input_text} {relation_label} {output_text}. "
        f"Stored reference effective {effective_date_label}."
    )

    return ScenarioShareCard(
        kind_label=kind_label,
        scope_label=snapshot.scope_label,
        input_text=input_text,
        output_text=output_text,
        relation_label=relation_label,
        relation_symbol=relation_symbol,
        rate_line=rate_line,
        status_label=status_label,
        effective_date_label=effective_date_label,
        provider_label=provider_label,
        fetched_at_label=fetched_at_label,
        trust_note=trust_note,
        title=title,
        description=description,
        output_font_size=_output_font_size(output_text),
    )

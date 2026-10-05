from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.utils.formats import date_format

from apps.exchange.domain import ObservationGranularity
from apps.exchange.share_snapshot import ConversionShareSnapshot


@dataclass(frozen=True, slots=True)
class ConversionShareCard:
    input_text: str
    output_text: str
    relation_label: str
    relation_symbol: str
    rate_line: str
    status_label: str
    data_class: str
    effective_date_label: str
    requested_date_label: str
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
        return 84
    if length <= 26:
        return 70
    if length <= 36:
        return 58
    return 48


def build_conversion_share_card(snapshot: ConversionShareSnapshot) -> ConversionShareCard:
    exact = snapshot.exact
    periodic = snapshot.historical and snapshot.observation_granularity in {
        ObservationGranularity.MONTHLY,
        ObservationGranularity.QUARTERLY,
    }

    input_text = f"{_decimal_text(snapshot.input_amount)} {snapshot.base_currency}"
    output_amount = _decimal_text(snapshot.output_amount)
    output_text = f"{output_amount} {snapshot.quote_currency}"
    relation_label = "equals" if exact else "approximately"
    relation_symbol = "=" if exact else "≈"
    rate_line = (
        f"1 {snapshot.base_currency} = {_decimal_text(snapshot.rate)} {snapshot.quote_currency}"
    )

    if exact:
        status_label = "Exact 1:1"
        data_class = "Historical exact 1:1" if snapshot.historical else "Exact 1:1"
        provider_label = "No external rate source"
        trust_note = (
            "The currencies are identical. This shared snapshot uses an exact 1:1 identity rate."
        )
    else:
        provider_label = ", ".join(key.upper() for key in snapshot.provider_keys)
        if snapshot.historical:
            if periodic:
                period = snapshot.observation_granularity.value.capitalize()
                status_label = f"{period} historical"
                data_class = f"{period} historical observation"
            else:
                status_label = "Historical reference"
                data_class = "Historical reference"
            trust_note = (
                "Historical snapshot. The observation date and source stay attached to the shared "
                "number; it is not a current rate."
            )
        elif snapshot.stale:
            status_label = "Cached reference"
            data_class = "Cached reference"
            trust_note = (
                "Cached reference snapshot. It was already marked stale when shared and must not "
                "be treated as a current executable rate."
            )
        else:
            status_label = "Reference rate"
            data_class = "Reference rate"
            trust_note = (
                "Stored share snapshot. Reference exchange-rate data is informational; payment "
                "providers may use different rates or add fees."
            )

    effective_date_label = date_format(snapshot.effective_date, "j M Y")
    requested_date_label = (
        date_format(snapshot.requested_date, "j M Y") if snapshot.requested_date is not None else ""
    )
    fetched_at_label = snapshot.fetched_at.strftime("%d %b %Y · %H:%M UTC")
    title = f"{input_text} → {output_text} · Cultural Currency"
    description = (
        f"{input_text} {relation_label} {output_text}. "
        f"{data_class}; effective {effective_date_label}."
    )

    return ConversionShareCard(
        input_text=input_text,
        output_text=output_text,
        relation_label=relation_label,
        relation_symbol=relation_symbol,
        rate_line=rate_line,
        status_label=status_label,
        data_class=data_class,
        effective_date_label=effective_date_label,
        requested_date_label=requested_date_label,
        provider_label=provider_label,
        fetched_at_label=fetched_at_label,
        trust_note=trust_note,
        title=title,
        description=description,
        output_font_size=_output_font_size(output_text),
    )

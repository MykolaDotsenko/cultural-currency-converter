from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.countries.models import City, Country, Currency
from apps.culture.models import (
    CulturalProfile,
    StoryDatePrecision,
    StoryMoment,
    StoryMomentCategory,
    StoryMomentStatus,
    StorySourceKind,
    TypicalPrice,
    TypicalPriceCategory,
    TypicalPriceConfidence,
    TypicalPriceSourceClass,
)
from apps.culture.services import approve_story_moment, publish_story_moment

_FINLAND_EURO_SOURCE = (
    "https://economy-finance.ec.europa.eu/euro/eu-countries-and-euro/finland-and-euro_en"
)
_JAPAN_YEN_SOURCE = "https://www.boj.or.jp/en/about/education/oshiete/money/c02.htm"


def seed_demo_story_moments() -> tuple[int, int]:
    finland = Country.objects.get(iso2="FI")
    japan = Country.objects.get(iso2="JP")
    eur = Currency.objects.get(code="EUR")
    fim = Currency.objects.get(code="FIM")
    jpy = Currency.objects.get(code="JPY")

    specifications = (
        {
            "external_id": "curated:fi-euro-adoption",
            "category": StoryMomentCategory.MONETARY_UNION,
            "title": "Finland adopted the euro",
            "summary": (
                "Finland adopted the euro on 1 January 1999. During the following three-year "
                "transition, the euro was the official currency but existed only as book money."
            ),
            "start_date": date(1999, 1, 1),
            "end_date": date(1999, 1, 1),
            "date_precision": StoryDatePrecision.EXACT_DAY,
            "source_name": "European Commission",
            "source_url": _FINLAND_EURO_SOURCE,
            "relevance_weight": 96,
            "countries": (finland,),
            "currencies": (eur, fim),
        },
        {
            "external_id": "curated:fi-euro-cash-changeover",
            "category": StoryMomentCategory.CASH_CHANGEOVER,
            "title": "Euro cash arrived in Finland",
            "summary": (
                "Euro banknotes and coins entered circulation in Finland on 1 January 2002. "
                "The dual-circulation period with the Finnish markka ended on 28 February 2002."
            ),
            "start_date": date(2002, 1, 1),
            "end_date": date(2002, 2, 28),
            "date_precision": StoryDatePrecision.RANGE,
            "source_name": "European Commission",
            "source_url": _FINLAND_EURO_SOURCE,
            "relevance_weight": 100,
            "countries": (finland,),
            "currencies": (eur, fim),
        },
        {
            "external_id": "curated:jp-yen-introduction",
            "category": StoryMomentCategory.CURRENCY_INTRODUCTION,
            "title": "The yen became Japan's currency unit",
            "summary": (
                "Japan's government enacted the New Currency Act in 1871 and introduced the yen "
                "as the new currency unit."
            ),
            "start_date": date(1871, 1, 1),
            "end_date": date(1871, 12, 31),
            "date_precision": StoryDatePrecision.YEAR,
            "source_name": "Bank of Japan",
            "source_url": _JAPAN_YEN_SOURCE,
            "relevance_weight": 92,
            "countries": (japan,),
            "currencies": (jpy,),
        },
    )

    created = existing = 0
    for spec in specifications:
        moment = StoryMoment.objects.filter(
            source_kind=StorySourceKind.OFFICIAL,
            external_id=spec["external_id"],
        ).first()
        if moment is not None:
            existing += 1
            continue

        moment = StoryMoment.objects.create(
            source_kind=StorySourceKind.OFFICIAL,
            external_id=spec["external_id"],
            category=spec["category"],
            title=spec["title"],
            summary=spec["summary"],
            start_date=spec["start_date"],
            end_date=spec["end_date"],
            date_precision=spec["date_precision"],
            source_name=spec["source_name"],
            source_url=spec["source_url"],
            relevance_weight=spec["relevance_weight"],
            verified_at=timezone.now(),
            status=StoryMomentStatus.NEEDS_REVIEW,
        )
        moment.countries.set(spec["countries"])
        moment.currencies.set(spec["currencies"])
        approve_story_moment(moment)
        publish_story_moment(moment)
        created += 1

    return created, existing


_JNTO_CASHLESS_SOURCE = "https://www.japan.travel/en/plan/cashless-payments-in-japan/"
_JNTO_BUDGET_SOURCE = "https://www.japan.travel/en/guide/japan-on-a-budget/"
_JNTO_FAQ_SOURCE = "https://www.japan.travel/en/faq/"
_JNTO_CREDIT_CARD_SOURCE = "https://www.japan.travel/en/plan/credit-cards/"
_JNTO_PLAN_SOURCE = "https://www.japan.travel/en/ca/plan/"
_TOKYO_METRO_FARE_SOURCE = "https://www.tokyometro.jp/lang_en/ticket/types/regular/index.html"


def seed_demo_destination_context() -> tuple[int, int]:
    japan = Country.objects.get(iso2="JP")
    jpy = Currency.objects.get(code="JPY")
    tokyo, _tokyo_created = City.objects.update_or_create(
        country=japan,
        slug="tokyo",
        defaults={"name": "Tokyo", "is_active": True},
    )
    verified_at = timezone.now()
    observation_date = date(2026, 9, 21)

    _profile, profile_created = CulturalProfile.objects.update_or_create(
        country=japan,
        defaults={
            "summary": (
                "Cashless payments are widespread in Japan, while cash remains useful in places "
                "that do not accept cards or electronic payments."
            ),
            "payment_customs": (
                "Cards are commonly accepted at major hotels, department stores, large shopping "
                "centres and many urban restaurants. Check the merchant when acceptance matters."
            ),
            "cash_usage": (
                "Carry some cash as a fallback, especially for smaller businesses and travel "
                "outside major urban areas."
            ),
            "tipping": (
                "Tipping is generally not practiced in Japan; ordinary service does not require "
                "adding a gratuity."
            ),
            "atm_notes": (
                "International cards can be used to withdraw cash at supported Japan Post Bank "
                "and Seven Bank ATMs."
            ),
            "dcc_warning": "",
            "source_name": "Japan National Tourism Organization (JNTO)",
            "source_url": _JNTO_CASHLESS_SOURCE,
            "source_notes": (
                f"Cash/card: {_JNTO_CASHLESS_SOURCE}\n"
                f"Tipping: {_JNTO_PLAN_SOURCE}\n"
                f"ATM guidance: {_JNTO_CREDIT_CARD_SOURCE}"
            ),
            "verified_at": verified_at,
            "is_published": True,
        },
    )

    specifications = (
        {
            "city": "",
            "category": TypicalPriceCategory.COFFEE,
            "label": "Cup of coffee",
            "amount_low": Decimal("100"),
            "amount_high": Decimal("600"),
            "source_name": "Japan National Tourism Organization (JNTO)",
            "source_url": _JNTO_BUDGET_SOURCE,
            "source_class": TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL,
            "confidence": TypicalPriceConfidence.MEDIUM,
            "display_order": 10,
            "notes": "JNTO travel-budget comparison range; approximate current travel context.",
        },
        {
            "city": "",
            "category": TypicalPriceCategory.CASUAL_MEAL,
            "label": "Casual meal",
            "amount_low": Decimal("500"),
            "amount_high": Decimal("1000"),
            "source_name": "Japan National Tourism Organization (JNTO)",
            "source_url": _JNTO_FAQ_SOURCE,
            "source_class": TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL,
            "confidence": TypicalPriceConfidence.MEDIUM,
            "display_order": 20,
            "notes": "JNTO FAQ example for convenience-store or casual-restaurant meals.",
        },
        {
            "city": "Tokyo",
            "category": TypicalPriceCategory.TRANSIT,
            "label": "Tokyo Metro regular ticket",
            "amount_low": Decimal("180"),
            "amount_high": Decimal("330"),
            "source_name": "Tokyo Metro",
            "source_url": _TOKYO_METRO_FARE_SOURCE,
            "source_class": TypicalPriceSourceClass.AUTHORITATIVE,
            "confidence": TypicalPriceConfidence.HIGH,
            "display_order": 30,
            "notes": "Adult regular-ticket fare range, distance dependent.",
        },
    )

    created_prices = 0
    for spec in specifications:
        _row, created = TypicalPrice.objects.update_or_create(
            country=japan,
            city=spec["city"],
            category=spec["category"],
            label=spec["label"],
            observed_at=observation_date,
            defaults={
                "amount_low": spec["amount_low"],
                "amount_high": spec["amount_high"],
                "currency": jpy,
                "city_ref": tokyo if spec["city"] == "Tokyo" else None,
                "source_name": spec["source_name"],
                "source_url": spec["source_url"],
                "verified_at": verified_at,
                "source_class": spec["source_class"],
                "confidence": spec["confidence"],
                "notes": spec["notes"],
                "display_order": spec["display_order"],
                "is_published": True,
            },
        )
        created_prices += int(created)

    created = int(profile_created) + created_prices
    existing = 1 + len(specifications) - created
    return created, existing

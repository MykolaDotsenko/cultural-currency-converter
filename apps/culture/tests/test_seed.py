from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.culture.models import (
    CulturalProfile,
    StoryMoment,
    StoryMomentStatus,
    TypicalPrice,
    TypicalPriceCategory,
)


@pytest.mark.django_db
def test_story_seed_requires_reference_data_first():
    with pytest.raises(CommandError, match="seed_reference_data"):
        call_command("seed_story_data")


@pytest.mark.django_db
def test_story_seed_is_reviewed_published_and_idempotent():
    call_command("seed_reference_data", stdout=StringIO())

    first = StringIO()
    call_command("seed_story_data", stdout=first)
    second = StringIO()
    call_command("seed_story_data", stdout=second)

    assert StoryMoment.objects.count() == 3
    assert StoryMoment.objects.filter(status=StoryMomentStatus.PUBLISHED).count() == 3
    assert "created=3, existing=0" in first.getvalue()
    assert "created=0, existing=3" in second.getvalue()

    euro_cash = StoryMoment.objects.get(external_id="curated:fi-euro-cash-changeover")
    assert euro_cash.source_name == "European Commission"
    assert euro_cash.countries.filter(iso2="FI").exists()
    assert euro_cash.currencies.filter(code="EUR").exists()


@pytest.mark.django_db
def test_destination_context_seed_requires_reference_data_first():
    with pytest.raises(CommandError, match="seed_reference_data"):
        call_command("seed_destination_context")


@pytest.mark.django_db
def test_destination_context_seed_is_sourced_and_idempotent():
    call_command("seed_reference_data", stdout=StringIO())

    first = StringIO()
    call_command("seed_destination_context", stdout=first)
    second = StringIO()
    call_command("seed_destination_context", stdout=second)

    profile = CulturalProfile.objects.get(country__iso2="JP")
    prices = TypicalPrice.objects.filter(country__iso2="JP").order_by("display_order")

    assert profile.is_published is True
    assert profile.source_name == "Japan National Tourism Organization (JNTO)"
    assert profile.source_url.startswith("https://www.japan.travel/")
    assert prices.count() == 3
    assert list(prices.values_list("category", flat=True)) == [
        TypicalPriceCategory.COFFEE,
        TypicalPriceCategory.CASUAL_MEAL,
        TypicalPriceCategory.TRANSIT,
    ]

    transit = prices.get(category=TypicalPriceCategory.TRANSIT)
    assert transit.city == "Tokyo"
    assert transit.city_ref is not None
    assert transit.city_ref.slug == "tokyo"
    assert transit.city_ref.name == "Tokyo"
    assert transit.amount_low == 180
    assert transit.amount_high == 330
    assert transit.currency.code == "JPY"
    assert transit.source_name == "Tokyo Metro"
    assert transit.source_url.startswith("https://www.tokyometro.jp/")

    assert "created=4, existing=0" in first.getvalue()
    assert "created=0, existing=4" in second.getvalue()

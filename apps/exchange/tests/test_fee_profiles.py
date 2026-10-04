from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.countries.models import Currency
from apps.exchange.fee_profiles import (
    PaymentFeeProfileError,
    delete_payment_fee_profile,
    fee_profile_for_pair,
    fee_profiles_for_pair,
    upsert_payment_fee_profile,
)
from apps.exchange.payment_estimate import PaymentEstimateAssumptions

User = get_user_model()


@pytest.fixture
def fee_profile_data(db):
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    usd = Currency.objects.create(code="USD", name="US dollar", minor_units=2)
    user = User.objects.create_user(username="fee-owner", password="StrongPass-482!")
    other = User.objects.create_user(username="fee-other", password="StrongPass-482!")
    return user, other, eur, jpy, usd


def _assumptions(
    *,
    markup: str = "2.00",
    source_fee: str = "1.00",
    destination_fee: str = "220",
) -> PaymentEstimateAssumptions:
    return PaymentEstimateAssumptions(
        fx_markup_percent=Decimal(markup),
        source_fixed_fee=Decimal(source_fee),
        destination_fixed_fee=Decimal(destination_fee),
    )


@pytest.mark.django_db
def test_fee_profile_upsert_is_owner_scoped_and_updates_same_name(fee_profile_data):
    user, other, eur, jpy, _usd = fee_profile_data

    first = upsert_payment_fee_profile(
        user,
        name="  Travel   card  ",
        source_currency=eur,
        destination_currency=jpy,
        assumptions=_assumptions(),
    )
    updated = upsert_payment_fee_profile(
        user,
        name="Travel card",
        source_currency=eur,
        destination_currency=jpy,
        assumptions=_assumptions(markup="1.50", source_fee="0.50", destination_fee="100"),
    )

    assert updated.pk == first.pk
    assert updated.name == "Travel card"
    assert updated.fx_markup_percent == Decimal("1.50")
    assert updated.source_fixed_fee == Decimal("0.50")
    assert updated.destination_fixed_fee == Decimal("100")
    assert fee_profiles_for_pair(
        user,
        source_currency_code="EUR",
        destination_currency_code="JPY",
    ) == (updated,)

    same_name_other_pair = upsert_payment_fee_profile(
        user,
        name="Travel card",
        source_currency=eur,
        destination_currency=_usd,
        assumptions=_assumptions(markup="1.00", source_fee="0.25", destination_fee="2.00"),
    )
    assert same_name_other_pair.pk != updated.pk
    assert fee_profiles_for_pair(
        user,
        source_currency_code="EUR",
        destination_currency_code="USD",
    ) == (same_name_other_pair,)
    assert (
        fee_profiles_for_pair(
            other,
            source_currency_code="EUR",
            destination_currency_code="JPY",
        )
        == ()
    )


@pytest.mark.django_db
def test_fee_profile_lookup_requires_owner_and_exact_pair(fee_profile_data):
    user, other, eur, jpy, usd = fee_profile_data
    profile = upsert_payment_fee_profile(
        user,
        name="ATM",
        source_currency=eur,
        destination_currency=jpy,
        assumptions=_assumptions(),
    )

    resolved = fee_profile_for_pair(
        user,
        profile_id=profile.pk,
        source_currency_code="EUR",
        destination_currency_code="JPY",
    )
    assert resolved.pk == profile.pk

    with pytest.raises(PaymentFeeProfileError, match="unavailable"):
        fee_profile_for_pair(
            other,
            profile_id=profile.pk,
            source_currency_code="EUR",
            destination_currency_code="JPY",
        )
    with pytest.raises(PaymentFeeProfileError, match="unavailable"):
        fee_profile_for_pair(
            user,
            profile_id=profile.pk,
            source_currency_code="EUR",
            destination_currency_code=usd.code,
        )


@pytest.mark.django_db
def test_fee_profile_delete_is_owner_scoped(fee_profile_data):
    user, other, eur, jpy, _usd = fee_profile_data
    profile = upsert_payment_fee_profile(
        user,
        name="Card",
        source_currency=eur,
        destination_currency=jpy,
        assumptions=_assumptions(),
    )

    assert delete_payment_fee_profile(other, profile_id=profile.pk) is False
    assert delete_payment_fee_profile(user, profile_id=profile.pk) is True
    assert delete_payment_fee_profile(user, profile_id=profile.pk) is False


@pytest.mark.django_db
def test_fee_profile_rejects_same_currency_and_out_of_range_assumptions(fee_profile_data):
    user, _other, eur, _jpy, _usd = fee_profile_data

    with pytest.raises(PaymentFeeProfileError, match="two different currencies"):
        upsert_payment_fee_profile(
            user,
            name="Invalid same pair",
            source_currency=eur,
            destination_currency=eur,
            assumptions=_assumptions(),
        )

    with pytest.raises(PaymentFeeProfileError, match="FX markup exceeds"):
        upsert_payment_fee_profile(
            user,
            name="Invalid markup",
            source_currency=eur,
            destination_currency=Currency.objects.get(code="JPY"),
            assumptions=_assumptions(markup="25.01"),
        )


@pytest.mark.django_db
def test_fee_profile_limit_is_enforced(fee_profile_data):
    user, _other, eur, jpy, _usd = fee_profile_data
    for index in range(12):
        upsert_payment_fee_profile(
            user,
            name=f"Profile {index}",
            source_currency=eur,
            destination_currency=jpy,
            assumptions=_assumptions(),
        )

    with pytest.raises(PaymentFeeProfileError, match="at most 12"):
        upsert_payment_fee_profile(
            user,
            name="Profile 13",
            source_currency=eur,
            destination_currency=jpy,
            assumptions=_assumptions(),
        )

    updated = upsert_payment_fee_profile(
        user,
        name="Profile 0",
        source_currency=eur,
        destination_currency=jpy,
        assumptions=_assumptions(markup="1.00"),
    )
    assert updated.fx_markup_percent == Decimal("1.00")


@pytest.mark.django_db
def test_fee_profile_rejects_fixed_fees_beyond_currency_precision(fee_profile_data):
    user, _other, eur, jpy, _usd = fee_profile_data

    with pytest.raises(PaymentFeeProfileError, match="Source fixed fee in EUR supports at most 2"):
        upsert_payment_fee_profile(
            user,
            name="Too precise EUR",
            source_currency=eur,
            destination_currency=jpy,
            assumptions=_assumptions(source_fee="1.001"),
        )

    with pytest.raises(
        PaymentFeeProfileError,
        match="Destination fixed fee in JPY supports at most 0",
    ):
        upsert_payment_fee_profile(
            user,
            name="Fractional JPY",
            source_currency=eur,
            destination_currency=jpy,
            assumptions=_assumptions(destination_fee="0.5"),
        )

"""FX currency catalog metadata is never presented as guaranteed live pair coverage."""

from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.countries.models import Currency


@pytest.mark.django_db
def test_report_flags_seed_only_currency_coverage_without_provider_calls():
    call_command("seed_reference_data", stdout=StringIO())
    out = StringIO()
    call_command("report_fx_reference_coverage", json=True, stdout=out)
    result = json.loads(out.getvalue())
    expected = {"GBP", "CHF", "AUD", "PLN"}
    assert expected <= {row["code"] for row in result["currencies"]}
    assert {
        row["state"] for row in result["currencies"] if row["code"] in expected
    } == {"metadata_missing"}
    assert result["pair_availability"] == "not_evaluated"


@pytest.mark.django_db
def test_recent_provider_metadata_is_labeled_not_guaranteed_pair_support():
    call_command("seed_reference_data", stdout=StringIO())
    Currency.objects.filter(code="GBP").update(
        coverage_from=timezone.localdate() - timedelta(days=365),
        coverage_to=timezone.localdate(),
        coverage_source="frankfurter-v2-currencies",
        coverage_fetched_at=timezone.now(),
        coverage_to_is_terminal=False,
    )
    out = StringIO()
    call_command("report_fx_reference_coverage", json=True, stdout=out)
    data = json.loads(out.getvalue())
    rows = {row["code"]: row["state"] for row in data["currencies"]}
    assert rows["GBP"] == "metadata_recent"
    assert rows["CHF"] == "metadata_missing"
    assert data["pair_availability"] == "not_evaluated"


@pytest.mark.django_db
def test_terminal_provider_coverage_is_not_live():
    call_command("seed_reference_data", stdout=StringIO())
    Currency.objects.filter(code="AUD").update(
        coverage_from=timezone.localdate() - timedelta(days=10),
        coverage_to=timezone.localdate(),
        coverage_source="frankfurter-v2-currencies",
        coverage_fetched_at=timezone.now(),
        coverage_to_is_terminal=True,
    )
    out = StringIO()
    call_command("report_fx_reference_coverage", json=True, stdout=out)
    rows = {r["code"]: r["state"] for r in json.loads(out.getvalue())["currencies"]}
    assert rows["AUD"] == "provider_coverage_terminal"


@pytest.mark.django_db
def test_strict_report_refuses_missing_provider_metadata():
    call_command("seed_reference_data", stdout=StringIO())
    with pytest.raises(CommandError, match="incomplete or stale"):
        call_command("report_fx_reference_coverage", strict=True, stdout=StringIO())


@pytest.mark.django_db
def test_report_rejects_invalid_age_without_writes():
    with pytest.raises(CommandError, match="1–90 days"):
        call_command("report_fx_reference_coverage", max_age_days=0)
    assert Currency.objects.count() == 0

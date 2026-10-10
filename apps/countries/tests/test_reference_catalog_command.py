"""Catalog startup and one-time bootstrap safety contracts."""

from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.countries.models import Country


class ReferenceCatalogBootstrapTests(TestCase):
    def test_empty_product_database_passes_bootstrap_preflight(self) -> None:
        out = StringIO()
        call_command("check_reference_catalog", require_empty=True, stdout=out)
        self.assertIn("product tables empty", out.getvalue())

    def test_empty_reference_catalog_rejects_normal_startup(self) -> None:
        with self.assertRaisesRegex(CommandError, "Reference catalog incomplete"):
            call_command("check_reference_catalog", stdout=StringIO())

    def test_seeded_catalog_passes_normal_startup(self) -> None:
        call_command("seed_reference_data", stdout=StringIO())
        out = StringIO()
        call_command("check_reference_catalog", stdout=out)
        self.assertIn("required country/currency pairs present", out.getvalue())

    def test_partial_catalog_is_rejected_and_cannot_be_bootstrapped(self) -> None:
        Country.objects.create(
            iso2="FI",
            iso3="FIN",
            name="Finland",
            official_name="Finland",
            region="Europe",
            subregion="Northern Europe",
            is_active=True,
        )
        with self.assertRaisesRegex(CommandError, "Reference catalog incomplete"):
            call_command("check_reference_catalog", stdout=StringIO())
        with self.assertRaisesRegex(CommandError, "existing product records"):
            call_command("check_reference_catalog", require_empty=True, stdout=StringIO())

    def test_existing_user_blocks_initial_bootstrap_even_without_reference_data(self) -> None:
        get_user_model().objects.create_user(username="test-existing-owner")
        with self.assertRaisesRegex(CommandError, "existing product records"):
            call_command("check_reference_catalog", require_empty=True, stdout=StringIO())

    def test_seeding_twice_does_not_qualify_as_initial_bootstrap(self) -> None:
        call_command("seed_reference_data", stdout=StringIO())
        with self.assertRaisesRegex(CommandError, "existing product records"):
            call_command("check_reference_catalog", require_empty=True, stdout=StringIO())

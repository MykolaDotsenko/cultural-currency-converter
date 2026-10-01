from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.countries.models import Country, Currency
from apps.culture.city_seed import seed_curated_city_prices_wave1, seed_curated_city_prices_wave2
from apps.culture.seed import seed_demo_destination_context

_REQUIRED_COUNTRIES = frozenset({"JP", "FI", "SE", "DK", "NO", "DE", "SG", "CA", "NZ"})
_REQUIRED_CURRENCIES = frozenset({"JPY", "EUR", "SEK", "DKK", "NOK", "SGD", "CAD", "NZD"})


class Command(BaseCommand):
    help = "Create sourced destination context and the reviewed city-price dataset."

    @transaction.atomic
    def handle(self, *args, **options):
        countries = set(
            Country.objects.filter(iso2__in=_REQUIRED_COUNTRIES).values_list("iso2", flat=True)
        )
        currencies = set(
            Currency.objects.filter(code__in=_REQUIRED_CURRENCIES).values_list("code", flat=True)
        )
        if countries != _REQUIRED_COUNTRIES or currencies != _REQUIRED_CURRENCIES:
            raise CommandError(
                "Required country/currency reference data is missing. "
                "Run seed_reference_data first."
            )

        context_created, context_existing = seed_demo_destination_context()
        wave_one_created, wave_one_existing = seed_curated_city_prices_wave1()
        wave_two_created, wave_two_existing = seed_curated_city_prices_wave2()
        self.stdout.write(
            self.style.SUCCESS(
                "Destination context is ready: "
                f"created={context_created}, existing={context_existing}."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "City price wave 1 is ready: "
                f"created={wave_one_created}, existing={wave_one_existing}."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "City price wave 2 is ready: "
                f"created={wave_two_created}, existing={wave_two_existing}."
            )
        )

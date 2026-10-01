from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.countries.models import Country, CountryCurrency, Currency

SOURCE = "curated-demo-seed-v1"

_EURO_FINLAND_SOURCE = (
    "https://economy-finance.ec.europa.eu/euro/eu-countries-and-euro/finland-and-euro_en"
)
_EURO_GERMANY_SOURCE = (
    "https://economy-finance.ec.europa.eu/euro/eu-countries-and-euro/germany-and-euro_en"
)
_SWEDISH_KRONA_SOURCE = "https://www.riksbank.se/en-gb/payments--cash/what-is-money/"
_DANISH_KRONE_SOURCE = "https://www.nationalbanken.dk/en/what-we-do/stable-prices-monetary-policy-and-the-danish-economy/exchange-rates"
_NORWEGIAN_KRONE_SOURCE = "https://www.norges-bank.no/en/topics/Statistics/exchange_rates/"


class Command(BaseCommand):
    help = "Create the deterministic country/currency slice used by product seed data."

    @transaction.atomic
    def handle(self, *args, **options):
        countries = {
            "FI": ("FIN", "Finland"),
            "JP": ("JPN", "Japan"),
            "US": ("USA", "United States"),
            "SE": ("SWE", "Sweden"),
            "DK": ("DNK", "Denmark"),
            "NO": ("NOR", "Norway"),
            "DE": ("DEU", "Germany"),
        }
        currencies = {
            "EUR": ("Euro", "€", 2, True, None, None),
            "JPY": ("Japanese yen", "¥", 0, True, None, None),
            "USD": ("US dollar", "$", 2, True, None, None),
            "SEK": ("Swedish krona", "kr", 2, True, None, None),
            "DKK": ("Danish krone", "kr", 2, True, None, None),
            "NOK": ("Norwegian krone", "kr", 2, True, None, None),
            "FIM": ("Finnish markka", "mk", 2, False, None, date(2001, 12, 31)),
        }

        country_rows = {}
        for iso2, (iso3, name) in countries.items():
            country_rows[iso2], _ = Country.objects.update_or_create(
                iso2=iso2,
                defaults={"iso3": iso3, "name": name, "official_name": name, "is_active": True},
            )

        currency_rows = {}
        for code, (name, symbol, minor_units, active, active_from, active_to) in currencies.items():
            currency_rows[code], _ = Currency.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "symbol": symbol,
                    "minor_units": minor_units,
                    "is_active": active,
                    "active_from": active_from,
                    "active_to": active_to,
                },
            )

        relationships = [
            (
                "FI",
                "FIM",
                True,
                None,
                date(2001, 12, 31),
                "historical_primary",
                _EURO_FINLAND_SOURCE,
            ),
            (
                "FI",
                "EUR",
                True,
                date(2002, 1, 1),
                None,
                "current_primary",
                _EURO_FINLAND_SOURCE,
            ),
            (
                "JP",
                "JPY",
                True,
                None,
                None,
                "current_primary",
                "https://www.boj.or.jp/en/about/education/oshiete/money/c02.htm",
            ),
            ("US", "USD", True, None, None, "current_primary", SOURCE),
            ("SE", "SEK", True, None, None, "current_primary", _SWEDISH_KRONA_SOURCE),
            ("DK", "DKK", True, None, None, "current_primary", _DANISH_KRONE_SOURCE),
            ("NO", "NOK", True, None, None, "current_primary", _NORWEGIAN_KRONE_SOURCE),
            ("DE", "EUR", True, None, None, "current_primary", _EURO_GERMANY_SOURCE),
        ]
        for iso2, code, primary, valid_from, valid_to, role, source in relationships:
            CountryCurrency.objects.update_or_create(
                country=country_rows[iso2],
                currency=currency_rows[code],
                valid_from=valid_from,
                valid_to=valid_to,
                defaults={"is_primary": primary, "usage_role": role, "source": source},
            )

        self.stdout.write(self.style.SUCCESS("Deterministic reference data is ready."))

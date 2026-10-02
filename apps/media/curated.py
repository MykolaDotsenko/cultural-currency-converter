from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.media.models import (
    DatePrecision,
    MediaKind,
    MediaRole,
    MediaSourceKind,
)

_HISTORICAL_EVIDENCE_KINDS = {
    MediaKind.ARCHIVAL_PHOTO,
    MediaKind.ARTWORK,
    MediaKind.HERITAGE_OBJECT,
    MediaKind.MAP,
}
_DESTINATION_SUPPORTING_ROLES = {
    MediaRole.EVERYDAY_VALUE,
    MediaRole.PAYMENT_CULTURE,
    MediaRole.LOCAL_DETAIL,
}
_DESTINATION_PHOTOGRAPHIC_ROLES = {
    MediaRole.COUNTRY_HERO,
    MediaRole.COUNTRY_TEASER,
    *_DESTINATION_SUPPORTING_ROLES,
}


@dataclass(frozen=True, slots=True)
class CuratedMediaSpec:
    slug: str
    country_code: str
    currency_code: str
    city: str
    valid_from: date | None
    valid_to: date | None
    date_precision: str
    role: str
    kind: str
    source_kind: str
    external_id: str
    title: str
    alt_text: str
    caption: str
    source_name: str
    source_url: str
    source_media_url: str
    creator: str
    licence_id: str
    licence_url: str
    rights_statement: str
    attribution_text: str
    expected_width: int
    expected_height: int
    focal_x: Decimal | None = None
    focal_y: Decimal | None = None
    responsive_widths: tuple[int, ...] = ()


FINLAND_HELSINKI_TRAM_HERO = CuratedMediaSpec(
    slug="finland-helsinki-tram-2026",
    country_code="FI",
    currency_code="",
    city="Helsinki",
    valid_from=date(2026, 5, 24),
    valid_to=date(2026, 5, 24),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.COUNTRY_HERO,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Helsinki_tram_line_4_Aleksanterinkatu_2026-05-24",
    title="Helsinki tram on Aleksanterinkatu, May 2026",
    alt_text=(
        "A Helsinki tram on line 4 travelling along Aleksanterinkatu in central Helsinki "
        "on a May afternoon."
    ),
    caption="Helsinki tram on Aleksanterinkatu, photographed 24 May 2026.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Helsinki_tram_on_line_4_on_Aleksanterinkatu_in_May_2026.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/6/60/"
        "Helsinki_tram_on_line_4_on_Aleksanterinkatu_in_May_2026.jpg"
    ),
    creator="JIP",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="JIP · CC BY-SA 4.0",
    expected_width=4608,
    expected_height=3456,
    focal_x=Decimal("0.540"),
    focal_y=Decimal("0.500"),
    responsive_widths=(640, 960, 1440),
)


FINLAND_HELSINKI_COFFEE_EVERYDAY_VALUE_2025 = CuratedMediaSpec(
    slug="finland-helsinki-coffee-everyday-value-2025",
    country_code="FI",
    currency_code="",
    city="Helsinki",
    valid_from=date(2025, 1, 30),
    valid_to=date(2025, 1, 30),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.EVERYDAY_VALUE,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Cup_of_coffee_at_The_Rook.jpg",
    title="Coffee at The Rook in Helsinki, January 2025",
    alt_text="A cup of coffee on a ceramic saucer at a restaurant table in Helsinki.",
    caption="Coffee at The Rook in Punavuori, Helsinki, photographed 30 January 2025.",
    source_name="Wikimedia Commons",
    source_url="https://commons.wikimedia.org/wiki/File:Cup_of_coffee_at_The_Rook.jpg",
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/4/41/Cup_of_coffee_at_The_Rook.jpg"
    ),
    creator="JIP",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="JIP · CC BY-SA 4.0",
    expected_width=4608,
    expected_height=3456,
    focal_x=Decimal("0.520"),
    focal_y=Decimal("0.500"),
    responsive_widths=(480, 800, 1200),
)


FINLAND_HELSINKI_TICKET_MACHINE_PAYMENT_2023 = CuratedMediaSpec(
    slug="finland-helsinki-ticket-machine-payment-2023",
    country_code="FI",
    currency_code="",
    city="Helsinki",
    valid_from=date(2023, 4, 27),
    valid_to=date(2023, 4, 27),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.PAYMENT_CULTURE,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Helsinki_Regional_Transport_Authority_ticket_vending_machine_01.jpg",
    title="HSL ticket vending machine in Helsinki, April 2023",
    alt_text="An HSL ticket vending machine at the Viking Line ferry terminal in Helsinki.",
    caption="HSL ticket vending machine at the Viking Line terminal, photographed 27 April 2023.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Helsinki_Regional_Transport_Authority%27s_ticket_vending_machine_01.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/7/7e/"
        "Helsinki_Regional_Transport_Authority%27s_ticket_vending_machine_01.jpg"
    ),
    creator="Sinikka Halme",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="Sinikka Halme · CC BY-SA 4.0",
    expected_width=3256,
    expected_height=2406,
    focal_x=Decimal("0.600"),
    focal_y=Decimal("0.500"),
    responsive_widths=(480, 800, 1200),
)


FINLAND_HELSINKI_TRAM_INTERIOR_LOCAL_DETAIL_2024 = CuratedMediaSpec(
    slug="finland-helsinki-tram-interior-local-detail-2024",
    country_code="FI",
    currency_code="",
    city="Helsinki",
    valid_from=date(2024, 10, 26),
    valid_to=date(2024, 10, 26),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.LOCAL_DETAIL,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Interior_of_Helsinki_tram_on_line_13.jpg",
    title="Interior of Helsinki tram line 13, October 2024",
    alt_text="The interior of a Helsinki tram on line 13 at Kalasatama.",
    caption="Interior of Helsinki tram line 13 at Kalasatama, photographed 26 October 2024.",
    source_name="Wikimedia Commons",
    source_url=("https://commons.wikimedia.org/wiki/File:Interior_of_Helsinki_tram_on_line_13.jpg"),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/f/f5/"
        "Interior_of_Helsinki_tram_on_line_13.jpg"
    ),
    creator="JIP",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="JIP · CC BY-SA 4.0",
    expected_width=4608,
    expected_height=3456,
    focal_x=Decimal("0.500"),
    focal_y=Decimal("0.450"),
    responsive_widths=(480, 800, 1200),
)


FRANCE_RUE_LAURISTON_HERO_2024 = CuratedMediaSpec(
    slug="france-rue-lauriston-paris-2024",
    country_code="FR",
    currency_code="",
    city="Paris",
    valid_from=date(2024, 11, 16),
    valid_to=date(2024, 11, 16),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.COUNTRY_HERO,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Rue_Lauriston_-_Paris_XVI_(FR75)_-_2024-11-16_-_1.jpg",
    title="Rue Lauriston in Paris, November 2024",
    alt_text="A contemporary street view along Rue Lauriston in Paris in November 2024.",
    caption="Rue Lauriston in Paris, photographed 16 November 2024.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Rue_Lauriston_-_Paris_XVI_%28FR75%29_-_2024-11-16_-_1.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/3/39/"
        "Rue_Lauriston_-_Paris_XVI_%28FR75%29_-_2024-11-16_-_1.jpg"
    ),
    creator="Chabe01",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="Chabe01 · CC BY-SA 4.0",
    expected_width=4032,
    expected_height=3024,
    focal_x=Decimal("0.500"),
    focal_y=Decimal("0.500"),
    responsive_widths=(640, 960, 1440),
)


FRANCE_PARIS_CROISSANT_EVERYDAY_VALUE_2025 = CuratedMediaSpec(
    slug="france-paris-croissant-everyday-value-2025",
    country_code="FR",
    currency_code="",
    city="Paris",
    valid_from=date(2025, 10, 19),
    valid_to=date(2025, 10, 19),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.EVERYDAY_VALUE,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Croissant_et_Pain_au_chocolat_in_Paris.jpg",
    title="Croissant and pain au chocolat in Paris, October 2025",
    alt_text="A croissant and pain au chocolat photographed in Paris.",
    caption="Croissant and pain au chocolat in Paris, photographed 19 October 2025.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/File:Croissant_et_Pain_au_chocolat_in_Paris.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/a/aa/"
        "Croissant_et_Pain_au_chocolat_in_Paris.jpg"
    ),
    creator="Wyslijp16",
    licence_id="CC BY 4.0",
    licence_url="https://creativecommons.org/licenses/by/4.0/",
    rights_statement="Creative Commons Attribution 4.0 International",
    attribution_text="Wyslijp16 · CC BY 4.0",
    expected_width=6000,
    expected_height=4000,
    focal_x=Decimal("0.500"),
    focal_y=Decimal("0.520"),
    responsive_widths=(480, 800, 1200),
)


FRANCE_PARIS_NAVIGO_MACHINE_PAYMENT_2023 = CuratedMediaSpec(
    slug="france-paris-navigo-machine-payment-2023",
    country_code="FR",
    currency_code="",
    city="Paris",
    valid_from=date(2023, 3, 28),
    valid_to=date(2023, 3, 28),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.PAYMENT_CULTURE,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:SNCF_Ile-de-France_ticket_vending_machine_Navigo_Easy_Saint_Lazare.jpg",
    title="Navigo Easy ticket vending machine at Paris Saint-Lazare, March 2023",
    alt_text="A ticket vending machine at Paris Saint-Lazare advertising Navigo Easy pass sales.",
    caption="Ticket vending machine at Paris Saint-Lazare, photographed 28 March 2023.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:SNCF_Ile-de-France_ticket_vending_machine_supporting_issuing_Navigo_Easy_"
        "at_Gare_Saint_Lazare.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/4/4f/"
        "SNCF_Ile-de-France_ticket_vending_machine_supporting_issuing_Navigo_Easy_"
        "at_Gare_Saint_Lazare.jpg"
    ),
    creator="DominikPeters",
    licence_id="CC0 1.0",
    licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
    rights_statement="Creative Commons CC0 1.0 Universal Public Domain Dedication",
    attribution_text="DominikPeters · CC0 1.0",
    expected_width=1660,
    expected_height=2214,
    focal_x=Decimal("0.500"),
    focal_y=Decimal("0.500"),
    responsive_widths=(480, 800, 1200),
)


FRANCE_PARIS_METRO_INTERIOR_LOCAL_DETAIL_2024 = CuratedMediaSpec(
    slug="france-paris-metro-interior-local-detail-2024",
    country_code="FR",
    currency_code="",
    city="Paris",
    valid_from=date(2024, 11, 9),
    valid_to=date(2024, 11, 9),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.LOCAL_DETAIL,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Interieur_rame_MP05_ligne_1_metro_parisien.jpg",
    title="Interior of a Paris Metro line 1 MP 05 train, November 2024",
    alt_text="The interior of an MP 05 train on line 1 of the Paris Metro.",
    caption="Interior of a Paris Metro line 1 MP 05 train, photographed 9 November 2024.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Int%C3%A9rieur_d%27une_rame_MP_05_de_la_ligne_1_du_m%C3%A9tro_parisien.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/3/35/"
        "Int%C3%A9rieur_d%27une_rame_MP_05_de_la_ligne_1_du_m%C3%A9tro_parisien.jpg"
    ),
    creator="Remontees",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="Remontees · CC BY-SA 4.0",
    expected_width=5971,
    expected_height=3981,
    focal_x=Decimal("0.500"),
    focal_y=Decimal("0.500"),
    responsive_widths=(480, 800, 1200),
)


JAPAN_TOKYO_STREET_HERO_2019 = CuratedMediaSpec(
    slug="japan-tokyo-street-night-2019",
    country_code="JP",
    currency_code="",
    city="Tokyo",
    valid_from=date(2019, 11, 29),
    valid_to=date(2019, 11, 29),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.COUNTRY_HERO,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Tokyo_street_at_night,_2019_-_771.jpg",
    title="Tokyo street at night, November 2019",
    alt_text="A nighttime street scene in Tokyo photographed in November 2019.",
    caption="Tokyo street at night, photographed 29 November 2019.",
    source_name="Wikimedia Commons",
    source_url=("https://commons.wikimedia.org/wiki/File:Tokyo_street_at_night,_2019_-_771.jpg"),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/d/d6/Tokyo_street_at_night,_2019_-_771.jpg"
    ),
    creator="Another Believer",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="Another Believer · CC BY-SA 4.0",
    expected_width=4000,
    expected_height=3000,
    focal_x=Decimal("0.500"),
    focal_y=Decimal("0.520"),
    responsive_widths=(640, 960, 1440),
)


JAPAN_SHOYU_RAMEN_EVERYDAY_VALUE_2025 = CuratedMediaSpec(
    slug="japan-shoyu-ramen-everyday-value-2025",
    country_code="JP",
    currency_code="",
    city="",
    valid_from=date(2025, 5, 11),
    valid_to=date(2025, 5, 11),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.EVERYDAY_VALUE,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:shoyu-ramen-tokyo-ramen-01-2025",
    title="Shoyu ramen (Tokyo ramen style), May 2025",
    alt_text="A bowl of shoyu ramen presented in Tokyo ramen style.",
    caption="Shoyu ramen (Tokyo ramen style), photographed 11 May 2025.",
    source_name="Wikimedia Commons",
    source_url="https://commons.wikimedia.org/wiki/File:Shoyu_Ramen%EF%BC%88Tokyo_Ramen%EF%BC%89_-_01.jpg",
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/c/c3/"
        "Shoyu_Ramen%EF%BC%88Tokyo_Ramen%EF%BC%89_-_01.jpg"
    ),
    creator="Quercus acuta",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="Quercus acuta · CC BY-SA 4.0",
    expected_width=3299,
    expected_height=2474,
    focal_x=Decimal("0.520"),
    focal_y=Decimal("0.510"),
    responsive_widths=(480, 800, 1200),
)


JAPAN_SUICA_VENDING_PAYMENT_2020 = CuratedMediaSpec(
    slug="japan-suica-vending-payment-2020",
    country_code="JP",
    currency_code="",
    city="",
    valid_from=date(2020, 11, 14),
    valid_to=date(2020, 11, 14),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.PAYMENT_CULTURE,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Suica_payment_on_vending_machine_50607340823",
    title="Suica payment on a vending machine, November 2020",
    alt_text="A Suica contactless payment interaction at a vending machine in Japan.",
    caption="Suica payment at a vending machine, photographed 14 November 2020.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Suica_payment_on_vending_machine_%2850607340823%29.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/b/b3/"
        "Suica_payment_on_vending_machine_%2850607340823%29.jpg"
    ),
    creator="Real Estate Japan / Scott Kouchi",
    licence_id="CC BY 2.0",
    licence_url="https://creativecommons.org/licenses/by/2.0/",
    rights_statement="Creative Commons Attribution 2.0 Generic",
    attribution_text="Real Estate Japan / Scott Kouchi · CC BY 2.0",
    expected_width=6240,
    expected_height=4160,
    focal_x=Decimal("0.500"),
    focal_y=Decimal("0.470"),
    responsive_widths=(480, 800, 1200),
)


JAPAN_TOKYO_METRO_LOCAL_DETAIL_2021 = CuratedMediaSpec(
    slug="japan-tokyo-metro-local-detail-2021",
    country_code="JP",
    currency_code="",
    city="",
    valid_from=date(2021, 4, 20),
    valid_to=date(2021, 4, 20),
    date_precision=DatePrecision.EXACT_DAY,
    role=MediaRole.LOCAL_DETAIL,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Tokyo-Metro-13000-Digital_signage-On_the_door.jpg",
    title="Tokyo Metro 13000-series door signage, April 2021",
    alt_text="Digital passenger information signage above a door on a Tokyo Metro 13000-series train.",
    caption="Passenger information display on a Tokyo Metro 13000-series train, photographed 20 April 2021.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/File:Tokyo-Metro-13000-Digital_signage-On_the_door.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/7/76/"
        "Tokyo-Metro-13000-Digital_signage-On_the_door.jpg"
    ),
    creator="MaedaAkihiko",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="MaedaAkihiko · CC BY-SA 4.0",
    expected_width=5004,
    expected_height=3336,
    focal_x=Decimal("0.500"),
    focal_y=Decimal("0.470"),
    responsive_widths=(480, 800, 1200),
)


JAPAN_AKIHABARA_1995_THEN = CuratedMediaSpec(
    slug="jpy-akihabara-1995",
    country_code="",
    currency_code="JPY",
    city="Tokyo",
    valid_from=date(1995, 1, 1),
    valid_to=date(1995, 12, 31),
    date_precision=DatePrecision.YEAR,
    role=MediaRole.COMPARISON_THEN,
    kind=MediaKind.ARCHIVAL_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Akihabara_station_south_street_1995_Danny_Choo",
    title="Akihabara Station south street, identified as 1995",
    alt_text=(
        "A sourced archival view of the street outside Akihabara Station in Tokyo, "
        "identified by the source as 1995."
    ),
    caption=("Akihabara Station south street, Tokyo; the source identifies the scene as 1995."),
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Akihabara_station_south_street,_1995,_(by_Danny_Choo).jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/0/07/"
        "Akihabara_station_south_street%2C_1995%2C_%28by_Danny_Choo%29.jpg"
    ),
    creator="Danny Choo",
    licence_id="CC BY-SA 2.0",
    licence_url="https://creativecommons.org/licenses/by-sa/2.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 2.0 Generic",
    attribution_text="Danny Choo · CC BY-SA 2.0",
    expected_width=930,
    expected_height=622,
)


JAPAN_SERIES_D_1000_YEN_1984_2007 = CuratedMediaSpec(
    slug="jpy-series-d-1000-yen-1984-2007",
    country_code="",
    currency_code="JPY",
    city="",
    valid_from=date(1984, 11, 1),
    valid_to=date(2007, 4, 2),
    date_precision=DatePrecision.RANGE,
    role=MediaRole.COMPARISON_THEN,
    kind=MediaKind.HERITAGE_OBJECT,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Series_D_1K_Yen_Bank_of_Japan_note_-_front.jpg",
    title="Series D 1,000-yen Bank of Japan note",
    alt_text=("Front of a Series D 1,000-yen Bank of Japan note featuring Natsume Soseki."),
    caption=(
        "Series D 1,000-yen note, first issued 1 November 1984; issue suspended 2 April 2007."
    ),
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/File:Series_D_1K_Yen_Bank_of_Japan_note_-_front.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/5/5c/"
        "Series_D_1K_Yen_Bank_of_Japan_note_-_front.jpg"
    ),
    creator="Eclipse2009",
    licence_id="Public domain (Japan)",
    licence_url="",
    rights_statement=(
        "Public domain in Japan under Article 13 of the Copyright Act; "
        "see the Wikimedia Commons file page for reuse details."
    ),
    attribution_text="Eclipse2009 · public domain in Japan",
    expected_width=900,
    expected_height=456,
)


CURATED_MEDIA: dict[str, CuratedMediaSpec] = {
    FINLAND_HELSINKI_TRAM_HERO.slug: FINLAND_HELSINKI_TRAM_HERO,
    FINLAND_HELSINKI_COFFEE_EVERYDAY_VALUE_2025.slug: FINLAND_HELSINKI_COFFEE_EVERYDAY_VALUE_2025,
    FINLAND_HELSINKI_TICKET_MACHINE_PAYMENT_2023.slug: FINLAND_HELSINKI_TICKET_MACHINE_PAYMENT_2023,
    FINLAND_HELSINKI_TRAM_INTERIOR_LOCAL_DETAIL_2024.slug: FINLAND_HELSINKI_TRAM_INTERIOR_LOCAL_DETAIL_2024,
    FRANCE_RUE_LAURISTON_HERO_2024.slug: FRANCE_RUE_LAURISTON_HERO_2024,
    FRANCE_PARIS_CROISSANT_EVERYDAY_VALUE_2025.slug: FRANCE_PARIS_CROISSANT_EVERYDAY_VALUE_2025,
    FRANCE_PARIS_NAVIGO_MACHINE_PAYMENT_2023.slug: FRANCE_PARIS_NAVIGO_MACHINE_PAYMENT_2023,
    FRANCE_PARIS_METRO_INTERIOR_LOCAL_DETAIL_2024.slug: FRANCE_PARIS_METRO_INTERIOR_LOCAL_DETAIL_2024,
    JAPAN_TOKYO_STREET_HERO_2019.slug: JAPAN_TOKYO_STREET_HERO_2019,
    JAPAN_SHOYU_RAMEN_EVERYDAY_VALUE_2025.slug: JAPAN_SHOYU_RAMEN_EVERYDAY_VALUE_2025,
    JAPAN_SUICA_VENDING_PAYMENT_2020.slug: JAPAN_SUICA_VENDING_PAYMENT_2020,
    JAPAN_TOKYO_METRO_LOCAL_DETAIL_2021.slug: JAPAN_TOKYO_METRO_LOCAL_DETAIL_2021,
    JAPAN_AKIHABARA_1995_THEN.slug: JAPAN_AKIHABARA_1995_THEN,
    JAPAN_SERIES_D_1000_YEN_1984_2007.slug: JAPAN_SERIES_D_1000_YEN_1984_2007,
}


def _validate_code(value: str, *, length: int, field_name: str) -> None:
    if not value:
        return
    if len(value) != length or not value.isascii() or not value.isalpha() or value != value.upper():
        raise ValueError(f"{field_name} must be an uppercase ASCII code of length {length}.")


def validate_curated_media_spec(spec: CuratedMediaSpec) -> CuratedMediaSpec:
    _validate_code(spec.country_code, length=2, field_name="country_code")
    _validate_code(spec.currency_code, length=3, field_name="currency_code")
    if spec.role not in MediaRole.values:
        raise ValueError("Curated media role is unknown.")
    if spec.kind not in MediaKind.values:
        raise ValueError("Curated media kind is unknown.")
    if spec.source_kind not in MediaSourceKind.values:
        raise ValueError("Curated media source kind is unknown.")
    if spec.date_precision not in DatePrecision.values:
        raise ValueError("Curated media date precision is unknown.")
    if spec.expected_width < 1 or spec.expected_height < 1:
        raise ValueError("Curated media expected dimensions must be positive.")
    if spec.valid_from and spec.valid_to and spec.valid_from > spec.valid_to:
        raise ValueError("Curated media valid_from cannot be after valid_to.")

    if (spec.focal_x is None) != (spec.focal_y is None):
        raise ValueError("Curated media focal coordinates must be provided together.")
    for coordinate in (spec.focal_x, spec.focal_y):
        if coordinate is not None and not Decimal("0") <= coordinate <= Decimal("1"):
            raise ValueError("Curated media focal coordinates must be normalized to 0..1.")

    if spec.responsive_widths:
        if tuple(sorted(set(spec.responsive_widths))) != spec.responsive_widths:
            raise ValueError("Curated responsive widths must be unique and strictly increasing.")
        if any(width < 1 or width >= spec.expected_width for width in spec.responsive_widths):
            raise ValueError(
                "Curated responsive widths must be positive and smaller than the source width."
            )

    if spec.role in _DESTINATION_PHOTOGRAPHIC_ROLES:
        if spec.focal_x is None or spec.focal_y is None:
            raise ValueError("Destination curated media requires a reviewed focal point.")
        if len(spec.responsive_widths) < 2:
            raise ValueError(
                "Destination curated media requires at least two reviewed responsive widths."
            )

    if spec.role in {MediaRole.COUNTRY_HERO, MediaRole.COUNTRY_TEASER}:
        if not spec.country_code:
            raise ValueError("Country hero/teaser curated media requires country_code.")
        if spec.currency_code:
            raise ValueError("Country hero/teaser curated media must remain currency-neutral.")
        if (
            spec.kind != MediaKind.CONTEMPORARY_PHOTO
            or spec.source_kind == MediaSourceKind.GENERATED
        ):
            raise ValueError(
                "Country hero/teaser curated media requires sourced contemporary photography."
            )

    if spec.role in _DESTINATION_SUPPORTING_ROLES:
        if not spec.country_code:
            raise ValueError("Destination supporting curated media requires country_code.")
        if spec.currency_code:
            raise ValueError("Destination supporting curated media must remain currency-neutral.")
        if (
            spec.kind == MediaKind.GENERATED_ILLUSTRATION
            or spec.source_kind == MediaSourceKind.GENERATED
        ):
            raise ValueError("Curated destination supporting media requires a sourced asset.")

    if spec.role == MediaRole.COMPARISON_THEN:
        if spec.country_code:
            raise ValueError(
                "comparison_then curated media must be countryless; "
                "runtime selection is currency-scoped."
            )
        if not spec.currency_code:
            raise ValueError("comparison_then curated media requires currency_code.")
        if spec.kind not in _HISTORICAL_EVIDENCE_KINDS:
            raise ValueError(
                "comparison_then curated media requires a sourced historical evidence kind."
            )
        if spec.source_kind == MediaSourceKind.GENERATED:
            raise ValueError("comparison_then curated media cannot use a generated source.")
        if spec.date_precision == DatePrecision.UNKNOWN:
            raise ValueError("comparison_then curated media requires explicit temporal precision.")
        if spec.valid_from is None and spec.valid_to is None:
            raise ValueError("comparison_then curated media requires a temporal scope.")

    return spec


def get_curated_media_spec(slug: str) -> CuratedMediaSpec:
    try:
        spec = CURATED_MEDIA[slug]
    except KeyError as exc:
        allowed = ", ".join(sorted(CURATED_MEDIA))
        raise ValueError(f"Unknown curated media slug. Available: {allowed}.") from exc
    return validate_curated_media_spec(spec)

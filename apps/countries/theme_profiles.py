from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CountryThemeProfile:
    """Curated presentation-only atmosphere for one country.

    Theme profiles never establish financial, cultural or behavioural truth.
    They only provide restrained visual/editorial direction inside the shared
    Quiet Atlas Premium system.
    """

    country_code: str
    theme_key: str
    atmosphere: str
    accent_hex: str
    soft_hex: str
    motion_tone: str
    editorial_cues: tuple[str, ...]
    prohibited_cliches: tuple[str, ...] = (
        "flag-led identity",
        "national-costume shorthand",
        "tourism-poster landmark collage",
        "decorative stereotype",
    )


def _profile(
    country_code: str,
    atmosphere: str,
    accent_hex: str,
    soft_hex: str,
    motion_tone: str,
    *editorial_cues: str,
) -> CountryThemeProfile:
    code = country_code.upper()
    return CountryThemeProfile(
        country_code=code,
        theme_key=code.lower(),
        atmosphere=atmosphere,
        accent_hex=accent_hex,
        soft_hex=soft_hex,
        motion_tone=motion_tone,
        editorial_cues=tuple(editorial_cues),
    )


COUNTRY_THEME_PROFILES: dict[str, CountryThemeProfile] = {
    "FI": _profile(
        "FI",
        "quiet Nordic confidence + tactile minimalism",
        "#446F7D",
        "#E7F0F2",
        "cool, calm crossfade",
        "natural timber and stone",
        "tram and waterfront rhythm",
        "quiet café detail",
    ),
    "JP": _profile(
        "JP",
        "urban precision + layered calm",
        "#8C5D52",
        "#F3E9E5",
        "precise, measured transition",
        "dense but ordered streets",
        "rail and station rhythm",
        "refined everyday detail",
    ),
    "FR": _profile(
        "FR",
        "understated elegance + cultured restraint",
        "#6E675E",
        "#F1EEE8",
        "soft editorial dissolve",
        "stone and metal urban texture",
        "café and market detail",
        "transit interiors",
    ),
    "US": _profile(
        "US",
        "cosmopolitan confidence + metropolitan scale",
        "#56677A",
        "#EBEEF2",
        "confident, clean transition",
        "large-scale urban geometry",
        "everyday retail",
        "public transit and street rhythm",
    ),
    "GB": _profile(
        "GB",
        "moody polish + classic-modern restraint",
        "#5D6072",
        "#ECECF1",
        "subtle, composed transition",
        "brick, stone and dark metal",
        "street and rail detail",
        "weathered urban texture",
    ),
    "DE": _profile(
        "DE",
        "disciplined clarity + material honesty",
        "#5E665F",
        "#ECEFEB",
        "crisp, low-motion transition",
        "architectural geometry",
        "transit infrastructure",
        "functional everyday detail",
    ),
    "IT": _profile(
        "IT",
        "warm sophistication + relaxed confidence",
        "#7B6557",
        "#F2ECE7",
        "warm, unhurried transition",
        "stone and plaster",
        "espresso and market detail",
        "street-scale urban life",
    ),
    "ES": _profile(
        "ES",
        "warm urban ease + cultured sunlight",
        "#8A684A",
        "#F4EEE6",
        "sun-warmed soft transition",
        "textured façades",
        "café and market rhythm",
        "public-space detail",
    ),
    "PT": _profile(
        "PT",
        "quiet warmth + textured elegance",
        "#6B756A",
        "#EDF1EB",
        "gentle, low-contrast transition",
        "stone, tile and plaster texture",
        "tram and street rhythm",
        "restrained café detail",
    ),
    "NL": _profile(
        "NL",
        "intelligent urban calm + clean functionality",
        "#55717B",
        "#EAF0F2",
        "clean, efficient transition",
        "waterfront urban geometry",
        "cycling and transit rhythm",
        "functional retail detail",
    ),
    "CH": _profile(
        "CH",
        "discreet luxury + quiet precision",
        "#6A655D",
        "#F0EEE9",
        "precise, restrained transition",
        "stone, glass and metal",
        "rail infrastructure",
        "quiet premium retail detail",
    ),
    "SE": _profile(
        "SE",
        "warm Nordic softness + digital ease",
        "#60788A",
        "#EAF0F3",
        "soft Nordic transition",
        "light timber and stone",
        "public transport",
        "calm everyday retail",
    ),
    "NO": _profile(
        "NO",
        "cool clarity + waterfront calm",
        "#4E6C7A",
        "#E8EFF2",
        "cool, spacious transition",
        "waterfront materials",
        "tram, ferry and street rhythm",
        "clean café detail",
    ),
    "DK": _profile(
        "DK",
        "human design culture + warm functionality",
        "#79645A",
        "#F2ECE9",
        "warm functional transition",
        "timber, brick and soft metal",
        "cycling and transit",
        "human-scale café detail",
    ),
    "PL": _profile(
        "PL",
        "cultured contemporary Europe + grounded energy",
        "#6F665B",
        "#F0EDE8",
        "grounded, composed transition",
        "brick, stone and contemporary glass",
        "tram and street rhythm",
        "market and café detail",
    ),
    "CZ": _profile(
        "CZ",
        "architectural depth + subtle patina",
        "#77675D",
        "#F1ECE8",
        "layered, quiet transition",
        "stone, plaster and aged metal",
        "tram and station detail",
        "restrained café texture",
    ),
    "TR": _profile(
        "TR",
        "layered cosmopolitan richness + waterfront warmth",
        "#7B6656",
        "#F2ECE6",
        "layered warm transition",
        "stone, ferry and waterfront texture",
        "market and café detail",
        "dense street rhythm",
    ),
    "CA": _profile(
        "CA",
        "open modernity + calm cosmopolitan polish",
        "#5C6F6A",
        "#EAF0ED",
        "open, calm transition",
        "glass, timber and urban greenery",
        "transit and waterfront rhythm",
        "everyday café detail",
    ),
    "AU": _profile(
        "AU",
        "bright urban sophistication + relaxed confidence",
        "#65765F",
        "#EDF1E9",
        "bright, relaxed transition",
        "sunlit contemporary architecture",
        "street and transit rhythm",
        "casual café detail",
    ),
    "NZ": _profile(
        "NZ",
        "compact calm + maritime softness",
        "#5C7276",
        "#E9F0F1",
        "soft maritime transition",
        "waterfront materials",
        "compact urban streets",
        "quiet café and retail detail",
    ),
    "SG": _profile(
        "SG",
        "tropical metropolitan precision + frictionless efficiency",
        "#55736A",
        "#E8F0EC",
        "precise, light transition",
        "tropical urban geometry",
        "rail and payment moments",
        "hawker and retail detail",
    ),
    "KR": _profile(
        "KR",
        "design-forward density + digital fluency",
        "#606A7D",
        "#EBEDF2",
        "clean digital transition",
        "dense contemporary streets",
        "rail and payment rhythm",
        "refined retail detail",
    ),
    "TH": _profile(
        "TH",
        "warm layered city life + controlled energy",
        "#866D50",
        "#F3EDE4",
        "warm, lively but restrained transition",
        "street and transit layers",
        "market and café detail",
        "tropical material texture",
    ),
    "AE": _profile(
        "AE",
        "restrained cosmopolitan luxury + architectural calm",
        "#7B705E",
        "#F2EFE9",
        "smooth, spacious transition",
        "stone, glass and shaded architecture",
        "metro and retail detail",
        "controlled warm light",
    ),
    "CN": _profile(
        "CN",
        "metropolitan depth + technological maturity",
        "#685F67",
        "#EFEBEE",
        "measured metropolitan transition",
        "dense urban geometry",
        "rail and payment rhythm",
        "contemporary retail detail",
    ),
    "IN": _profile(
        "IN",
        "layered urban energy + disciplined richness",
        "#816A55",
        "#F3EDE6",
        "layered, controlled transition",
        "urban material depth",
        "metro and market rhythm",
        "everyday payment detail",
    ),
    "ID": _profile(
        "ID",
        "tropical urban modernity + soft density",
        "#5E766B",
        "#EAF1ED",
        "soft tropical transition",
        "urban greenery and concrete",
        "transit and market rhythm",
        "everyday retail detail",
    ),
    "MX": _profile(
        "MX",
        "architectural warmth + cultural depth",
        "#81634F",
        "#F3EBE5",
        "warm architectural transition",
        "stone, plaster and shaded streets",
        "market and café detail",
        "transit rhythm",
    ),
    "BR": _profile(
        "BR",
        "urban vitality + composed density",
        "#5E755F",
        "#EBF1EA",
        "lively but composed transition",
        "layered urban greenery",
        "metro and street rhythm",
        "everyday café and retail detail",
    ),
    "ZA": _profile(
        "ZA",
        "sunlit urban confidence + grounded elegance",
        "#786B55",
        "#F2EEE7",
        "sunlit, grounded transition",
        "stone, concrete and warm light",
        "urban street rhythm",
        "market and café detail",
    ),
}

_ATLAS_FALLBACK_THEME_KEYS = (
    "atlas-fjord",
    "atlas-moss",
    "atlas-clay",
    "atlas-slate",
    "atlas-sand",
    "atlas-plum",
)


def country_theme_profile(country_code: str) -> CountryThemeProfile | None:
    return COUNTRY_THEME_PROFILES.get(country_code.upper().strip())


def country_theme_key(country_code: str) -> str:
    """Return a stable presentation theme key without creating country truth."""

    code = country_code.upper().strip()
    if not code:
        return ""

    profile = country_theme_profile(code)
    if profile is not None:
        return profile.theme_key

    checksum = sum((index + 1) * ord(character) for index, character in enumerate(code))
    return _ATLAS_FALLBACK_THEME_KEYS[checksum % len(_ATLAS_FALLBACK_THEME_KEYS)]

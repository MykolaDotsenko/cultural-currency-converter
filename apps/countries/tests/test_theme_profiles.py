from __future__ import annotations

from apps.countries.theme_profiles import (
    COUNTRY_THEME_PROFILES,
    country_theme_key,
    country_theme_profile,
)

EXPECTED_CURATED_COUNTRY_CODES = {
    "AE",
    "AU",
    "BR",
    "CA",
    "CH",
    "CN",
    "CZ",
    "DE",
    "DK",
    "ES",
    "FI",
    "FR",
    "GB",
    "ID",
    "IN",
    "IT",
    "JP",
    "KR",
    "MX",
    "NL",
    "NO",
    "NZ",
    "PL",
    "PT",
    "SE",
    "SG",
    "TH",
    "TR",
    "US",
    "ZA",
}


def test_curated_country_theme_release_has_exactly_thirty_explicit_profiles():
    assert set(COUNTRY_THEME_PROFILES) == EXPECTED_CURATED_COUNTRY_CODES
    assert len({profile.theme_key for profile in COUNTRY_THEME_PROFILES.values()}) == 30


def test_country_theme_profiles_have_bounded_presentation_metadata():
    for code, profile in COUNTRY_THEME_PROFILES.items():
        assert profile.country_code == code
        assert profile.theme_key == code.lower()
        assert profile.atmosphere
        assert profile.motion_tone
        assert len(profile.editorial_cues) >= 2
        assert profile.accent_hex.startswith("#") and len(profile.accent_hex) == 7
        assert profile.soft_hex.startswith("#") and len(profile.soft_hex) == 7
        assert profile.prohibited_cliches


def test_country_theme_lookup_is_case_and_whitespace_tolerant():
    profile = country_theme_profile("  ca ")

    assert profile is not None
    assert profile.country_code == "CA"
    assert country_theme_key("  ca ") == "ca"


def test_unknown_country_keeps_stable_atlas_fallback():
    first = country_theme_key("XX")
    second = country_theme_key("xx")

    assert first == second
    assert first.startswith("atlas-")


def test_empty_country_has_no_theme():
    assert country_theme_key("") == ""
    assert country_theme_key("   ") == ""

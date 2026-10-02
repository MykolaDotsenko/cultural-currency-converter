from __future__ import annotations

import logging
from decimal import DecimalException
from urllib.parse import urlencode

from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_GET

from apps.countries.models import Country, Currency
from apps.culture.city_profile import build_city_money_profile, build_city_money_profile_component
from apps.culture.explore import build_explore_destinations
from apps.culture.explore_collections import build_explore_collections
from apps.culture.explore_navigation import build_explore_regions
from apps.culture.explore_presentation import (
    build_explore_collection_components,
    build_explore_destination_cards,
    build_explore_region_components,
)
from apps.culture.forms import CurrentDestinationContextForm, StoryRequestForm
from apps.culture.media import select_destination_media
from apps.culture.presentation import build_destination_context_component
from apps.culture.services import build_destination_context
from apps.culture.story import compose_story
from apps.media.models import MediaRole
from apps.media.presentation import select_media_for_display

logger = logging.getLogger("cultural_currency.culture")


@require_GET
def city_money_profile(
    request: HttpRequest,
    country_code: str,
    city_slug: str,
) -> HttpResponse:
    """Show reviewed current money context for one canonical city without requesting FX."""

    try:
        profile = build_city_money_profile(country_code=country_code, city_slug=city_slug)
    except DatabaseError as exc:
        logger.warning(
            "City money profile composition failed",
            extra={
                "error_code": exc.__class__.__name__,
                "culture.country": country_code.upper(),
                "culture.city": city_slug.lower(),
            },
        )
        return render(
            request,
            "pages/city_money_profile.html",
            {
                "city_profile": None,
                "city_profile_error": {
                    "title": "City money context is temporarily unavailable.",
                    "detail": "The converter and destination planner remain available.",
                },
            },
            status=503,
        )

    if profile is None:
        raise Http404("Reviewed city money context is not available.")

    return render(
        request,
        "pages/city_money_profile.html",
        {
            "city_profile": build_city_money_profile_component(profile),
            "city_profile_error": None,
        },
    )


@require_GET
def explore(request: HttpRequest) -> HttpResponse:
    """Discover reviewed current money context without requesting FX or AI."""

    selected_date = timezone.localdate()
    explore_error = None
    collection_error = None
    navigation_error = None
    destinations = ()
    destination_cards = ()
    region_components = ()
    collection_components = ()

    try:
        destinations = build_explore_destinations(as_of=selected_date, limit=24)
    except DatabaseError as exc:
        logger.warning(
            "Explore destination composition failed",
            extra={"error_code": exc.__class__.__name__},
        )
        explore_error = {
            "title": "Explore is temporarily unavailable.",
            "detail": "The converter and saved travel-money tools remain available.",
        }
    else:
        destination_cards = build_explore_destination_cards(destinations)

        try:
            region_components = build_explore_region_components(build_explore_regions(destinations))
        except DatabaseError as exc:
            logger.warning(
                "Explore regional navigation composition failed",
                extra={"error_code": exc.__class__.__name__},
            )
            navigation_error = {
                "title": "Regional navigation is temporarily unavailable.",
                "detail": "The reviewed destination list below is still available.",
            }

        try:
            collections = build_explore_collections(
                as_of=selected_date,
                item_limit=6,
                destinations=destinations,
            )
            collection_components = build_explore_collection_components(
                collections,
                selected_date=selected_date,
            )
        except DatabaseError as exc:
            logger.warning(
                "Explore collection composition failed",
                extra={"error_code": exc.__class__.__name__},
            )
            collection_error = {
                "title": "Curated collections are temporarily unavailable.",
                "detail": "Regional and destination discovery still use reviewed context.",
            }

    country_codes = {destination.country_code for destination in destinations}
    city_count = sum(destination.is_city_scope for destination in destinations)
    explore_stats = {
        "country_count": len(country_codes),
        "city_count": city_count,
        "region_count": len(region_components),
        "collection_count": len(collection_components),
    }

    return render(
        request,
        "pages/explore.html",
        {
            "explore_destinations": destination_cards,
            "explore_regions": region_components,
            "explore_collections": collection_components,
            "explore_stats": explore_stats,
            "explore_error": explore_error,
            "explore_collection_error": collection_error,
            "explore_navigation_error": navigation_error,
            "explore_as_of": selected_date,
        },
    )

@require_GET
def money_culture_story(request: HttpRequest) -> HttpResponse:
    form = StoryRequestForm(request.GET)
    story = None
    story_error = None
    story_media = None
    response_status = 200

    if not form.is_valid():
        response_status = 400
        story_error = {
            "title": "This story request is not valid.",
            "detail": "Run the conversion again, then open Money & culture.",
        }
    else:
        story_request = form.to_story_request()
        try:
            story = compose_story(story_request)
        except DatabaseError:
            logger.exception(
                "Money and culture story composition failed",
                extra={
                    "culture.status": "unavailable",
                    "culture.historical": story_request.historical,
                    "culture.selected_date": story_request.selected_date.isoformat(),
                },
            )
            story_error = {
                "title": "Money & culture is temporarily unavailable.",
                "detail": "The conversion remains valid. Try the story again later.",
            }
        else:
            try:
                country = _country_for_story(story_request.destination_country)
                currency = _currency_for_story(story_request.destination_currency)
                story_media = select_media_for_display(
                    role=MediaRole.STORY_COVER,
                    country=country,
                    currency=currency,
                    target_date=story_request.selected_date if story_request.historical else None,
                )
            except (DatabaseError, ValueError) as exc:
                logger.warning(
                    "Money and culture story cover media unavailable",
                    extra={
                        "error_code": exc.__class__.__name__,
                        "culture.status": "media_unavailable",
                        "culture.historical": story_request.historical,
                    },
                )

    context = {
        "story": story,
        "story_error": story_error,
        "story_media": story_media,
    }
    fragment = bool(request.htmx)
    template = "components/culture/story.html" if fragment else "pages/money_culture_story.html"
    response = render(request, template, context, status=response_status)
    patch_vary_headers(response, ["HX-Request"])
    return response


@require_GET
def current_destination_context(request: HttpRequest) -> HttpResponse:
    form = CurrentDestinationContextForm(request.GET)
    destination_context_component = None
    current_context_error = None
    response_status = 200

    if not form.is_valid():
        response_status = 400
        current_context_error = {
            "title": "Today's destination context request is not valid.",
            "detail": "Run the historical conversion again, then open today's travel context.",
        }
    else:
        try:
            destination_context = build_destination_context(
                country_code=form.cleaned_data["country"],
                converted_amount=form.cleaned_data["amount"],
                quote_currency=form.cleaned_data["currency"],
            )
        except (DatabaseError, ValueError, DecimalException):
            logger.exception(
                "Current destination context composition failed",
                extra={
                    "culture.status": "unavailable",
                    "culture.country": form.cleaned_data["country"],
                    "culture.currency": form.cleaned_data["currency"],
                },
            )
            current_context_error = {
                "title": "Today's destination context is temporarily unavailable.",
                "detail": "The historical conversion remains valid. Try this context again later.",
            }
        else:
            if destination_context is None:
                current_context_error = {
                    "title": "Today's destination context is not available.",
                    "detail": "The historical conversion remains valid.",
                }
            else:
                destination_media = select_destination_media(destination_context.country_code)
                destination_context_component = build_destination_context_component(
                    destination_context,
                    historical=True,
                    show_explore_nav=False,
                    hero_image=destination_media.hero,
                    everyday_value_image=destination_media.everyday_value,
                    payment_culture_image=destination_media.payment_culture,
                    local_detail_image=destination_media.local_detail,
                )

    context = {
        "destination_context_component": destination_context_component,
        "current_context_error": current_context_error,
    }
    fragment = bool(request.htmx)
    template = (
        "components/culture/current_destination_context.html"
        if fragment
        else "pages/current_destination_context.html"
    )
    response = render(request, template, context, status=response_status)
    patch_vary_headers(response, ["HX-Request"])
    return response


def _country_for_story(code: str) -> Country | None:
    if not code:
        return None
    return Country.objects.filter(iso2=code).first()


def _currency_for_story(code: str) -> Currency | None:
    if not code:
        return None
    return Currency.objects.filter(code=code).first()

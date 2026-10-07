from __future__ import annotations

import logging
from decimal import DecimalException

from django.conf import settings
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.ai_preferences import explanation_preferences
from apps.common.presentation.media_view_models import ImageViewModel
from apps.countries.models import Country, Currency
from apps.culture.city_profile import build_city_money_profile, build_city_money_profile_component
from apps.culture.explore import build_explore_destinations
from apps.culture.explore_ai import (
    ExploreExplanationError,
    available_explore_explanation_intents,
    build_explore_explanation_service,
    destination_token,
    explain_reviewed_destination,
    parse_explore_explanation_intent,
    resolve_reviewed_explore_destination,
)
from apps.culture.explore_collections import build_explore_collections
from apps.culture.explore_navigation import build_explore_regions
from apps.culture.explore_presentation import (
    build_explore_collection_components,
    build_explore_destination_cards,
    build_explore_region_components,
)
from apps.culture.forms import (
    CurrentDestinationContextForm,
    ExploreExplanationForm,
    StoryRequestForm,
)
from apps.culture.media import select_destination_media
from apps.culture.presentation import build_destination_context_component
from apps.culture.services import build_destination_context
from apps.culture.story import compose_story
from apps.media.models import MediaRole
from apps.media.presentation import (
    select_media_for_display,
    select_media_for_display_countries,
)

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

    social_preview = None
    try:
        country = Country.objects.filter(iso2=profile.country_code).first()
        currency = Currency.objects.filter(code=profile.currency_code).first()
        selection = select_media_for_display(
            role=MediaRole.SOCIAL_PREVIEW,
            country=country,
            currency=currency,
        )
        if selection is not None:
            social_preview = {
                "url": request.build_absolute_uri(selection.image.src),
                "alt": selection.image.alt,
            }
    except (DatabaseError, ValueError) as exc:
        logger.warning(
            "City money profile social preview unavailable",
            extra={
                "error_code": exc.__class__.__name__,
                "culture.country": profile.country_code,
                "culture.city": profile.city_slug,
            },
        )

    return render(
        request,
        "pages/city_money_profile.html",
        {
            "city_profile": build_city_money_profile_component(profile),
            "city_profile_error": None,
            "social_preview": social_preview,
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
                item_limit=3,
                destinations=destinations,
            )
            teaser_media = {}
            try:
                teaser_media = _explore_collection_teaser_media(collections)
            except (DatabaseError, ValueError) as exc:
                logger.warning(
                    "Explore teaser media unavailable",
                    extra={"error_code": exc.__class__.__name__},
                )
            collection_components = build_explore_collection_components(
                collections,
                selected_date=selected_date,
                teaser_media_by_country=teaser_media,
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
    ai_destination_choices = tuple(
        (destination_token(destination), destination.scope_label) for destination in destinations
    )
    explore_ai_form = (
        ExploreExplanationForm(destination_choices=ai_destination_choices)
        if settings.AI_RUNTIME_EXPLANATION_ENABLED and ai_destination_choices
        else None
    )

    social_preview = None
    try:
        selection = select_media_for_display(role=MediaRole.SOCIAL_PREVIEW)
        if selection is not None:
            social_preview = {
                "url": request.build_absolute_uri(selection.image.src),
                "alt": selection.image.alt,
            }
    except (DatabaseError, ValueError) as exc:
        logger.warning(
            "Explore social preview unavailable",
            extra={"error_code": exc.__class__.__name__},
        )

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
            "explore_ai_form": explore_ai_form,
            "explore_ai_prompts": available_explore_explanation_intents(),
            "social_preview": social_preview,
        },
    )


@require_POST
def explore_explanation(request: HttpRequest) -> HttpResponse:
    """Explain one reviewed Explore destination using only rebuilt trusted context."""

    if not settings.AI_RUNTIME_EXPLANATION_ENABLED:
        raise Http404("Runtime AI explanation is disabled.")

    selected_date = timezone.localdate()
    explanation = None
    explanation_error = None
    response_status = 200

    try:
        destinations = build_explore_destinations(as_of=selected_date, limit=24)
    except DatabaseError:
        logger.exception(
            "Explore AI destination resolution failed",
            extra={"culture.capability": "explore_explanation"},
        )
        destinations = ()
        response_status = 503
        explanation_error = {
            "title": "Reviewed destination context is temporarily unavailable.",
            "detail": "Explore and the converter remain usable without this optional explanation.",
        }

    if explanation_error is None:
        choices = tuple(
            (destination_token(destination), destination.scope_label)
            for destination in destinations
        )
        form = ExploreExplanationForm(request.POST, destination_choices=choices)
        if not form.is_valid():
            response_status = 422
            explanation_error = {
                "title": "This Explore explanation request is not valid.",
                "detail": "Choose one reviewed destination and one of the suggested questions.",
            }
        else:
            try:
                destination = resolve_reviewed_explore_destination(
                    form.cleaned_data["destination_token"],
                    destinations=destinations,
                )
                intent = parse_explore_explanation_intent(form.cleaned_data["prompt_id"])
                preferences = explanation_preferences(request.user)
                context, packet, delivery = explain_reviewed_destination(
                    destination,
                    intent=intent,
                    service=build_explore_explanation_service(),
                    locale=preferences.locale,
                    focus_instruction_suffix=preferences.focus_instruction_suffix,
                )
            except ExploreExplanationError:
                response_status = 422
                explanation_error = {
                    "title": "This reviewed destination is no longer available.",
                    "detail": "Refresh Explore and choose a destination that still has reviewed context.",
                }
            except (DatabaseError, ValueError):
                logger.exception(
                    "Explore AI trusted context composition failed",
                    extra={"culture.capability": "explore_explanation"},
                )
                response_status = 503
                explanation_error = {
                    "title": "The optional explanation is temporarily unavailable.",
                    "detail": "The reviewed Explore facts remain unchanged and available.",
                }
            else:
                spec = next(
                    spec
                    for spec in available_explore_explanation_intents()
                    if spec.intent is intent
                )
                supporting_fact_ids = {
                    fact_id
                    for insight in (
                        delivery.result.short_answer,
                        *delivery.result.key_factors,
                        delivery.result.watch_out_for,
                        delivery.result.next_step,
                    )
                    for fact_id in insight.supporting_fact_ids
                }
                explanation = {
                    "result": delivery.result,
                    "cache_status": delivery.cache_status,
                    "question": spec.question,
                    "facts_used": tuple(
                        fact for fact in packet.facts if fact.id in supporting_fact_ids
                    ),
                    "destination_label": (
                        f"{context.city_name}, {context.country_name}"
                        if context.city_name
                        else context.country_name
                    ),
                }

    fragment = bool(request.htmx)
    template = (
        "components/culture/explore_explanation.html"
        if fragment
        else "pages/explore_explanation.html"
    )
    response = render(
        request,
        template,
        {
            "explanation": explanation,
            "explanation_error": explanation_error,
            "is_htmx_fragment": fragment,
        },
        status=response_status,
    )
    patch_vary_headers(response, ["HX-Request"])
    return response


@require_GET
def money_culture_story(request: HttpRequest) -> HttpResponse:
    form = StoryRequestForm(request.GET)
    story = None
    story_error = None
    story_media = None
    story_social_preview = None
    story_chapter_items = ()
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
            story_chapter_items = tuple(
                {"chapter": chapter, "media": None} for chapter in story.historical_moment_chapters
            )
            try:
                country = _country_for_story(story_request.destination_country)
                currency = _currency_for_story(story_request.destination_currency)
            except DatabaseError as exc:
                logger.warning(
                    "Money and culture story media metadata unavailable",
                    extra={
                        "error_code": exc.__class__.__name__,
                        "culture.status": "media_metadata_unavailable",
                        "culture.historical": story_request.historical,
                    },
                )
            else:
                try:
                    story_media = select_media_for_display(
                        role=MediaRole.STORY_COVER,
                        country=country,
                        currency=currency,
                        target_date=(
                            story_request.selected_date if story_request.historical else None
                        ),
                    )
                except (DatabaseError, ValueError) as exc:
                    logger.warning(
                        "Money and culture story cover media unavailable",
                        extra={
                            "error_code": exc.__class__.__name__,
                            "culture.status": "cover_media_unavailable",
                            "culture.historical": story_request.historical,
                        },
                    )

                try:
                    story_social_preview = select_media_for_display(
                        role=MediaRole.SOCIAL_PREVIEW,
                        country=country,
                        currency=currency,
                    )
                except (DatabaseError, ValueError) as exc:
                    logger.warning(
                        "Money and culture story social preview unavailable",
                        extra={
                            "error_code": exc.__class__.__name__,
                            "culture.status": "social_preview_unavailable",
                            "culture.historical": story_request.historical,
                        },
                    )

                try:
                    used_sources = {
                        selection.image.src for selection in (story_media,) if selection is not None
                    }
                    chapter_items = []
                    for chapter in story.historical_moment_chapters:
                        chapter_media = select_media_for_display(
                            role=MediaRole.STORY_CHAPTER,
                            country=country,
                            currency=currency,
                            target_date=chapter.target_date,
                        )
                        if chapter_media is not None and chapter_media.image.src in used_sources:
                            chapter_media = None
                        if chapter_media is not None:
                            used_sources.add(chapter_media.image.src)
                        chapter_items.append({"chapter": chapter, "media": chapter_media})
                    story_chapter_items = tuple(chapter_items)
                except (DatabaseError, ValueError) as exc:
                    logger.warning(
                        "Money and culture story chapter media unavailable",
                        extra={
                            "error_code": exc.__class__.__name__,
                            "culture.status": "chapter_media_unavailable",
                            "culture.historical": story_request.historical,
                        },
                    )

    context = {
        "story": story,
        "story_error": story_error,
        "story_media": story_media,
        "story_chapter_items": story_chapter_items,
        "social_preview": (
            {
                "url": request.build_absolute_uri(story_social_preview.image.src),
                "alt": story_social_preview.image.alt,
            }
            if story_social_preview is not None
            else None
        ),
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


def _explore_collection_teaser_media(collections) -> dict[str, ImageViewModel]:
    country_codes: list[str] = []
    for collection in collections:
        for item in collection.items:
            if len(item.country_codes) != 1:
                continue
            code = item.country_codes[0]
            if code not in country_codes:
                country_codes.append(code)

    countries = {
        country.iso2: country for country in Country.objects.filter(iso2__in=country_codes[:12])
    }
    ordered_countries = tuple(
        country for code in country_codes[:12] if (country := countries.get(code)) is not None
    )
    return select_media_for_display_countries(
        role=MediaRole.COUNTRY_TEASER,
        countries=ordered_countries,
        aspect_ratio="4 / 3",
    )


def _country_for_story(code: str) -> Country | None:
    if not code:
        return None
    return Country.objects.filter(iso2=code).first()


def _currency_for_story(code: str) -> Currency | None:
    if not code:
        return None
    return Currency.objects.filter(code=code).first()

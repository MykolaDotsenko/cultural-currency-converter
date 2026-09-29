from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_GET

from apps.countries.models import Country, Currency
from apps.culture.forms import CurrentDestinationContextForm, StoryRequestForm
from apps.culture.media import select_destination_media
from apps.culture.presentation import build_destination_context_component
from apps.culture.services import build_destination_context
from apps.culture.story import compose_story
from apps.media.models import MediaRole
from apps.media.presentation import select_media_for_display

logger = logging.getLogger("cultural_currency.culture")


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
        except Exception:
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
            country = _country_for_story(story_request.destination_country)
            currency = _currency_for_story(story_request.destination_currency)
            story_media = select_media_for_display(
                role=MediaRole.STORY_COVER,
                country=country,
                currency=currency,
                target_date=story_request.selected_date if story_request.historical else None,
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
        except Exception:
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

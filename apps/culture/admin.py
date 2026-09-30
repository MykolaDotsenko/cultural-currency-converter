from __future__ import annotations

from django.contrib import admin, messages

from apps.culture.models import CulturalProfile, StoryMoment, TypicalPrice
from apps.culture.services import (
    StoryPublicationError,
    approve_story_moment,
    publish_story_moment,
    reject_story_moment,
    retire_story_moment,
)


@admin.register(StoryMoment)
class StoryMomentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "status",
        "relevance_weight",
        "start_date",
        "source_name",
        "verified_at",
    )
    list_filter = ("status", "category", "source_kind", "supports_causality")
    search_fields = ("title", "summary", "source_name", "external_id")
    filter_horizontal = ("countries", "currencies")
    readonly_fields = (
        "status",
        "reviewed_at",
        "published_at",
        "created_at",
        "updated_at",
    )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status in {"published", "retired"}:
            fields.extend(
                [
                    "category",
                    "title",
                    "summary",
                    "countries",
                    "currencies",
                    "start_date",
                    "end_date",
                    "date_precision",
                    "source_kind",
                    "source_name",
                    "source_url",
                    "external_id",
                    "source_published_at",
                    "source_retrieved_at",
                    "verified_at",
                    "relevance_weight",
                    "supports_causality",
                    "causal_support_note",
                ]
            )
        return tuple(fields)

    actions = (
        "approve_selected",
        "publish_selected",
        "retire_selected",
        "reject_selected",
    )

    @admin.action(description="Approve selected story moments")
    def approve_selected(self, request, queryset):
        self._run_transition(request, queryset, approve_story_moment, "approved")

    @admin.action(description="Publish selected approved story moments")
    def publish_selected(self, request, queryset):
        self._run_transition(request, queryset, publish_story_moment, "published")

    @admin.action(description="Retire selected published story moments")
    def retire_selected(self, request, queryset):
        self._run_transition(request, queryset, retire_story_moment, "retired")

    @admin.action(description="Reject selected unpublished story moments")
    def reject_selected(self, request, queryset):
        self._run_transition(request, queryset, reject_story_moment, "rejected")

    def _run_transition(self, request, queryset, transition, label: str) -> None:
        succeeded = 0
        failures: list[str] = []
        for moment in queryset:
            try:
                transition(moment)
                succeeded += 1
            except StoryPublicationError as exc:
                failures.append(f"{moment.pk}: {exc}")

        if succeeded:
            self.message_user(
                request,
                f"{succeeded} story moment(s) {label}.",
                level=messages.SUCCESS,
            )
        if failures:
            self.message_user(
                request,
                "Skipped story moments: " + " | ".join(failures[:8]),
                level=messages.WARNING,
            )


@admin.register(CulturalProfile)
class CulturalProfileAdmin(admin.ModelAdmin):
    list_display = ("country", "is_published", "source_name", "verified_at", "updated_at")
    list_filter = ("is_published",)
    search_fields = ("country__name", "country__iso2", "source_name")
    list_select_related = ("country",)


@admin.register(TypicalPrice)
class TypicalPriceAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "country",
        "city_ref",
        "city",
        "category",
        "amount_low",
        "amount_high",
        "currency",
        "observed_at",
        "source_class",
        "confidence",
        "is_published",
    )
    list_filter = ("is_published", "source_class", "confidence", "category", "country")
    search_fields = (
        "label",
        "country__name",
        "city",
        "city_ref__name",
        "city_ref__slug",
        "source_name",
    )
    list_select_related = ("country", "currency", "city_ref")
    ordering = ("display_order", "country__name", "city", "label")

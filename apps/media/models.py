from __future__ import annotations

from pathlib import Path

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class MediaKind(models.TextChoices):
    CONTEMPORARY_PHOTO = "contemporary_photo", "Contemporary photo"
    ARCHIVAL_PHOTO = "archival_photo", "Archival photo"
    ARTWORK = "artwork", "Artwork"
    HERITAGE_OBJECT = "heritage_object", "Heritage object"
    MAP = "map", "Map"
    GENERATED_ILLUSTRATION = "generated_illustration", "Generated illustration"
    DECORATIVE_PATTERN = "decorative_pattern", "Decorative pattern"
    BRAND_ASSET = "brand_asset", "Brand asset"


class MediaSourceKind(models.TextChoices):
    WIKIMEDIA_COMMONS = "wikimedia_commons", "Wikimedia Commons"
    EUROPEANA = "europeana", "Europeana"
    INSTITUTION = "institution", "Institution / archive"
    MANUAL = "manual", "Manual / owned"
    GENERATED = "generated", "Generated"


class MediaRole(models.TextChoices):
    COUNTRY_HERO = "country_hero", "Country hero"
    COUNTRY_TEASER = "country_teaser", "Country teaser"
    EVERYDAY_VALUE = "everyday_value", "Everyday value"
    PAYMENT_CULTURE = "payment_culture", "Payment culture"
    LOCAL_DETAIL = "local_detail", "Local detail"
    STORY_COVER = "story_cover", "Story cover"
    STORY_CHAPTER = "story_chapter", "Story chapter"
    COMPARISON_THEN = "comparison_then", "Comparison then"
    COMPARISON_NOW = "comparison_now", "Comparison now"
    HISTORICAL_TIMELINE = "historical_timeline", "Historical timeline"
    SOCIAL_PREVIEW = "social_preview", "Social preview"
    DECORATIVE_BACKGROUND = "decorative_background", "Decorative background"


class DatePrecision(models.TextChoices):
    EXACT_DAY = "exact_day", "Exact day"
    MONTH = "month", "Month"
    YEAR = "year", "Year"
    DECADE = "decade", "Decade"
    RANGE = "range", "Range"
    ERA = "era", "Era"
    UNKNOWN = "unknown", "Unknown"


class MediaStatus(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    NEEDS_REVIEW = "needs_review", "Needs review"
    APPROVED = "approved", "Approved"
    PUBLISHED = "published", "Published"
    RETIRED = "retired", "Retired"
    REJECTED = "rejected", "Rejected"


def _media_upload_to(instance: MediaAsset, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    bucket = "generated" if instance.generated_by_ai else "sourced"
    identity = instance.content_hash[:32] if instance.content_hash else "pending"
    return f"{bucket}/{identity[:2]}/{identity}{suffix}"


class MediaAsset(models.Model):
    kind = models.CharField(max_length=32, choices=MediaKind.choices)
    source_kind = models.CharField(max_length=32, choices=MediaSourceKind.choices)
    role = models.CharField(max_length=32, choices=MediaRole.choices)

    country = models.ForeignKey(
        "countries.Country",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="media_assets",
    )
    currency = models.ForeignKey(
        "countries.Currency",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="media_assets",
    )
    city = models.CharField(max_length=120, blank=True)

    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    date_precision = models.CharField(
        max_length=16,
        choices=DatePrecision.choices,
        default=DatePrecision.UNKNOWN,
    )

    title = models.CharField(max_length=240)
    alt_text = models.CharField(max_length=500, blank=True)
    caption = models.TextField(blank=True)

    storage_file = models.FileField(upload_to=_media_upload_to, blank=True, max_length=500)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    aspect_ratio = models.CharField(max_length=32, blank=True)
    focal_x = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    focal_y = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)

    derivative_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="derivatives",
    )
    variant_width = models.PositiveIntegerField(null=True, blank=True)

    source_name = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    source_media_url = models.URLField(max_length=1000, blank=True)
    external_id = models.CharField(max_length=240, blank=True)
    creator = models.CharField(max_length=300, blank=True)
    licence_id = models.CharField(max_length=120, blank=True)
    licence_url = models.URLField(max_length=500, blank=True)
    rights_statement = models.TextField(blank=True)
    attribution_text = models.TextField(blank=True)
    source_retrieved_at = models.DateTimeField(null=True, blank=True)

    generated_by_ai = models.BooleanField(default=False)
    ai_label = models.CharField(max_length=160, blank=True)
    generation_provider = models.CharField(max_length=120, blank=True)
    generation_model = models.CharField(max_length=160, blank=True)
    prompt_version = models.CharField(max_length=80, blank=True)
    prompt_hash = models.CharField(max_length=64, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=MediaStatus.choices,
        default=MediaStatus.CANDIDATE,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("role", "-published_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_to__isnull=True)
                | Q(valid_to__gte=models.F("valid_from")),
                name="media_valid_date_range",
            ),
            models.CheckConstraint(
                condition=Q(focal_x__isnull=True) | Q(focal_x__gte=0, focal_x__lte=1),
                name="media_focal_x_normalized",
            ),
            models.CheckConstraint(
                condition=Q(focal_y__isnull=True) | Q(focal_y__gte=0, focal_y__lte=1),
                name="media_focal_y_normalized",
            ),
            models.UniqueConstraint(
                fields=("source_kind", "external_id"),
                condition=~Q(external_id=""),
                name="media_unique_external_identity",
            ),
            models.UniqueConstraint(
                fields=("content_hash",),
                condition=~Q(content_hash=""),
                name="media_unique_content_hash",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            errors["valid_to"] = "Media valid_to cannot precede valid_from."

        if self.generated_by_ai:
            if self.kind != MediaKind.GENERATED_ILLUSTRATION:
                errors["kind"] = "AI-generated media must use generated_illustration kind."
            if self.source_kind != MediaSourceKind.GENERATED:
                errors["source_kind"] = "AI-generated media must use generated source kind."
        elif self.source_kind == MediaSourceKind.GENERATED:
            errors["generated_by_ai"] = "Generated source kind requires generated_by_ai=true."

        if self.derivative_of_id and self.pk and self.derivative_of_id == self.pk:
            errors["derivative_of"] = "A media asset cannot be its own derivative."

        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    @property
    def is_decorative(self) -> bool:
        return self.role == MediaRole.DECORATIVE_BACKGROUND

    @property
    def is_published(self) -> bool:
        return self.status == MediaStatus.PUBLISHED

    def __str__(self) -> str:
        return f"{self.title} [{self.role}]"

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageOps

from apps.countries.models import Country, Currency
from apps.media.models import (
    DatePrecision,
    MediaAsset,
    MediaKind,
    MediaRole,
    MediaSourceKind,
    MediaStatus,
)
from apps.media.sources.base import MediaCandidate
from apps.media.validation import MediaValidationError, validate_raster_image


class MediaPublicationError(ValueError):
    pass


class DuplicateMediaContentError(ValueError):
    def __init__(self, existing_asset_id: int):
        self.existing_asset_id = existing_asset_id
        super().__init__(f"Media bytes already belong to asset {existing_asset_id}.")


@dataclass(frozen=True, slots=True)
class CandidateIngestSummary:
    created: int
    updated: int
    unchanged: int
    skipped_protected: int
    dry_run: bool


@dataclass(frozen=True, slots=True)
class SelectedMedia:
    asset: MediaAsset
    selection_reason: str
    temporal_match_quality: str
    authenticity_class: str
    fallback_level: int = 0


_HISTORICAL_ROLES = {
    MediaRole.COMPARISON_THEN,
    MediaRole.HISTORICAL_TIMELINE,
}
_PHOTOGRAPHIC_ROLES = {
    MediaRole.COUNTRY_HERO,
    MediaRole.COUNTRY_TEASER,
}
_TEMPORAL_SCORE = {
    DatePrecision.EXACT_DAY: 1000,
    DatePrecision.MONTH: 900,
    DatePrecision.YEAR: 850,
    DatePrecision.RANGE: 700,
    DatePrecision.DECADE: 550,
    DatePrecision.ERA: 400,
    DatePrecision.UNKNOWN: 0,
}
_FORMAT_EXTENSION = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _validate_sha256(value: str, *, field_name: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value.lower()):
        raise MediaPublicationError(f"{field_name} must be a valid SHA-256 hex digest.")


def _validate_https_url(value: str, *, field_name: str, required: bool = False) -> None:
    if not value:
        if required:
            raise MediaPublicationError(f"{field_name} is required.")
        return
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise MediaPublicationError(f"{field_name} must be an absolute credential-free HTTPS URL.")


def _validate_publishable_metadata(asset: MediaAsset) -> None:
    if not asset.storage_file:
        raise MediaPublicationError("Published media requires a managed storage file.")
    if not asset.content_hash:
        raise MediaPublicationError("Published media requires a SHA-256 content hash.")
    _validate_sha256(asset.content_hash, field_name="content_hash")
    if not asset.width or not asset.height:
        raise MediaPublicationError("Published media requires positive intrinsic dimensions.")
    if not asset.is_decorative and not asset.alt_text.strip():
        raise MediaPublicationError("Non-decorative published media requires editorial alt text.")
    if asset.reviewed_at is None:
        raise MediaPublicationError("Published media requires explicit editorial review.")

    if asset.generated_by_ai:
        required_ai = {
            "ai_label": asset.ai_label,
            "generation_provider": asset.generation_provider,
            "generation_model": asset.generation_model,
            "prompt_version": asset.prompt_version,
            "prompt_hash": asset.prompt_hash,
        }
        missing = [name for name, value in required_ai.items() if not str(value or "").strip()]
        if missing:
            raise MediaPublicationError(
                "AI-generated media is missing required authenticity metadata: "
                + ", ".join(missing)
                + "."
            )
        if "ai" not in asset.ai_label.casefold() or "generated" not in asset.ai_label.casefold():
            raise MediaPublicationError(
                "AI-generated media authenticity label must explicitly say it is AI-generated."
            )
        _validate_sha256(asset.prompt_hash, field_name="prompt_hash")
        if asset.kind != MediaKind.GENERATED_ILLUSTRATION:
            raise MediaPublicationError("AI media must use generated_illustration kind.")
        if asset.source_kind != MediaSourceKind.GENERATED:
            raise MediaPublicationError("AI media must use generated source kind.")
        if asset.role in _HISTORICAL_ROLES and asset.date_precision == DatePrecision.UNKNOWN:
            raise MediaPublicationError(
                "Historical AI illustration requires explicit temporal precision."
            )
    else:
        _validate_https_url(asset.source_url, field_name="source_url", required=True)
        _validate_https_url(asset.licence_url, field_name="licence_url")
        _validate_https_url(asset.source_media_url, field_name="source_media_url")
        if not asset.source_name.strip():
            raise MediaPublicationError("Sourced media requires source/institution metadata.")
        if not (asset.licence_id.strip() or asset.rights_statement.strip()):
            raise MediaPublicationError("Sourced media requires licence or rights metadata.")
        if not asset.attribution_text.strip():
            raise MediaPublicationError("Sourced media requires attribution text.")
        if asset.kind == MediaKind.ARCHIVAL_PHOTO or asset.role in _HISTORICAL_ROLES:
            if asset.date_precision == DatePrecision.UNKNOWN:
                raise MediaPublicationError(
                    "Historical sourced media requires honest temporal precision."
                )
            if asset.valid_from is None and asset.valid_to is None:
                raise MediaPublicationError("Historical sourced media requires a temporal scope.")

    asset.full_clean(exclude={"storage_file"})


def approve_media_asset(
    asset: MediaAsset,
    *,
    reviewed_at: datetime | None = None,
) -> MediaAsset:
    if asset.status in {MediaStatus.PUBLISHED, MediaStatus.RETIRED, MediaStatus.REJECTED}:
        raise MediaPublicationError(f"Cannot approve media in {asset.status} state.")

    previous_reviewed_at = asset.reviewed_at
    asset.reviewed_at = reviewed_at or timezone.now()
    try:
        _validate_publishable_metadata(asset)
    except Exception:
        asset.reviewed_at = previous_reviewed_at
        raise

    asset.status = MediaStatus.APPROVED
    asset.save()
    return asset


def publish_media_asset(
    asset: MediaAsset,
    *,
    published_at: datetime | None = None,
) -> MediaAsset:
    if asset.status != MediaStatus.APPROVED:
        raise MediaPublicationError("Only explicitly approved media can be published.")
    _validate_publishable_metadata(asset)
    asset.status = MediaStatus.PUBLISHED
    asset.published_at = published_at or timezone.now()
    asset.save(update_fields=("status", "published_at", "updated_at"))
    return asset


def retire_media_asset(asset: MediaAsset) -> MediaAsset:
    if asset.status != MediaStatus.PUBLISHED:
        raise MediaPublicationError("Only published media can be retired.")
    asset.status = MediaStatus.RETIRED
    asset.save(update_fields=("status", "updated_at"))
    return asset


def reject_media_asset(asset: MediaAsset) -> MediaAsset:
    if asset.status in {MediaStatus.PUBLISHED, MediaStatus.RETIRED}:
        raise MediaPublicationError("Published/retired media cannot be rejected in place.")
    asset.status = MediaStatus.REJECTED
    asset.reviewed_at = timezone.now()
    asset.save(update_fields=("status", "reviewed_at", "updated_at"))
    return asset


def _sanitize_raster_bytes(data: bytes, *, image_format: str) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        image.load()
        if image_format == "JPEG":
            normalized = image.convert("RGB")
        elif image.mode not in {"RGB", "RGBA"}:
            normalized = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        else:
            normalized = image.copy()

    output = io.BytesIO()
    if image_format == "JPEG":
        normalized.save(output, format="JPEG", quality=92, optimize=True, progressive=True)
    elif image_format == "PNG":
        normalized.save(output, format="PNG", optimize=True)
    else:
        normalized.save(output, format="WEBP", quality=90, method=6)
    return output.getvalue()


def attach_media_bytes(
    asset: MediaAsset,
    data: bytes,
    *,
    filename: str,
) -> MediaAsset:
    if asset.pk is None:
        raise MediaPublicationError("Media asset must be persisted before bytes are attached.")
    if asset.status in {MediaStatus.APPROVED, MediaStatus.PUBLISHED, MediaStatus.RETIRED}:
        raise MediaPublicationError(
            "Approved/published media bytes are immutable; create a new asset instead."
        )

    incoming = validate_raster_image(data, filename=filename)
    sanitized_data = _sanitize_raster_bytes(data, image_format=incoming.format)
    normalized_filename = f"normalized{_FORMAT_EXTENSION[incoming.format]}"
    validated = validate_raster_image(sanitized_data, filename=normalized_filename)
    duplicate = (
        MediaAsset.objects.filter(content_hash=validated.content_hash)
        .exclude(pk=asset.pk)
        .only("pk")
        .first()
    )
    if duplicate is not None:
        raise DuplicateMediaContentError(duplicate.pk)

    suffix = _FORMAT_EXTENSION[validated.format]
    bucket = "generated" if asset.generated_by_ai else "sourced"
    storage_name = f"{bucket}/{validated.content_hash[:2]}/{validated.content_hash}{suffix}"
    created_storage_object = False
    if not default_storage.exists(storage_name):
        storage_name = default_storage.save(storage_name, ContentFile(sanitized_data))
        created_storage_object = True

    try:
        with transaction.atomic():
            asset.storage_file.name = storage_name
            asset.width = validated.width
            asset.height = validated.height
            asset.aspect_ratio = validated.aspect_ratio
            asset.content_hash = validated.content_hash
            asset.status = MediaStatus.NEEDS_REVIEW
            asset.save()
    except Exception:
        if created_storage_object:
            default_storage.delete(storage_name)
        raise
    return asset


def create_responsive_derivative(
    source: MediaAsset,
    *,
    width: int,
) -> MediaAsset:
    if source.status not in {MediaStatus.APPROVED, MediaStatus.PUBLISHED}:
        raise MediaPublicationError("Responsive derivatives require reviewed source media.")
    if not source.storage_file:
        raise MediaPublicationError("Responsive derivatives require source bytes.")
    if not 1 <= width < (source.width or 0):
        raise MediaPublicationError(
            "Derivative width must be positive and smaller than the source."
        )

    with source.storage_file.open("rb") as source_file:
        raw = source_file.read()

    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image)
            target_height = max(1, round(image.height * width / image.width))
            resized = image.resize((width, target_height), Image.Resampling.LANCZOS)
            if resized.mode not in {"RGB", "RGBA"}:
                resized = resized.convert("RGBA" if "A" in resized.getbands() else "RGB")
            output = io.BytesIO()
            resized.save(output, format="WEBP", quality=86, method=6, exif=b"")
    except OSError as exc:
        raise MediaValidationError("Stored source media cannot be decoded for derivation.") from exc

    derivative = MediaAsset.objects.create(
        kind=source.kind,
        source_kind=source.source_kind,
        role=source.role,
        country=source.country,
        currency=source.currency,
        city=source.city,
        valid_from=source.valid_from,
        valid_to=source.valid_to,
        date_precision=source.date_precision,
        title=f"{source.title} · {width}px",
        alt_text=source.alt_text,
        caption=source.caption,
        focal_x=source.focal_x,
        focal_y=source.focal_y,
        derivative_of=source,
        variant_width=width,
        source_name=source.source_name,
        source_url=source.source_url,
        source_media_url=source.source_media_url,
        external_id="",
        creator=source.creator,
        licence_id=source.licence_id,
        licence_url=source.licence_url,
        rights_statement=source.rights_statement,
        attribution_text=source.attribution_text,
        source_retrieved_at=source.source_retrieved_at,
        generated_by_ai=source.generated_by_ai,
        ai_label=source.ai_label,
        generation_provider=source.generation_provider,
        generation_model=source.generation_model,
        prompt_version=source.prompt_version,
        prompt_hash=source.prompt_hash,
        generated_at=source.generated_at,
        status=MediaStatus.CANDIDATE,
    )
    try:
        return attach_media_bytes(
            derivative,
            output.getvalue(),
            filename=f"derivative-{width}.webp",
        )
    except Exception:
        derivative.delete()
        raise


def upsert_media_candidates(
    candidates: tuple[MediaCandidate, ...],
    *,
    role: str,
    kind: str,
    country: Country | None = None,
    currency: Currency | None = None,
    dry_run: bool = False,
) -> CandidateIngestSummary:
    if role not in MediaRole.values:
        raise ValueError("Unknown media role.")
    if kind not in MediaKind.values or kind == MediaKind.GENERATED_ILLUSTRATION:
        raise ValueError("Candidate ingestion requires a non-generated media kind.")

    created = updated = unchanged = skipped_protected = 0
    with transaction.atomic():
        for candidate in candidates:
            _validate_https_url(
                candidate.source_url, field_name="candidate source_url", required=True
            )
            _validate_https_url(
                candidate.source_media_url,
                field_name="candidate source_media_url",
            )
            _validate_https_url(candidate.licence_url, field_name="candidate licence_url")
            if candidate.source_kind not in {
                MediaSourceKind.WIKIMEDIA_COMMONS,
                MediaSourceKind.EUROPEANA,
            }:
                raise ValueError("Unsupported candidate source kind.")
            if not candidate.external_id.strip():
                raise ValueError("Media candidate external identity is required.")

            existing = MediaAsset.objects.filter(
                source_kind=candidate.source_kind,
                external_id=candidate.external_id,
            ).first()
            if existing and existing.status in {
                MediaStatus.APPROVED,
                MediaStatus.PUBLISHED,
                MediaStatus.RETIRED,
            }:
                skipped_protected += 1
                continue

            defaults = {
                "kind": kind,
                "role": role,
                "country": country,
                "currency": currency,
                "title": candidate.title[:240],
                "source_name": candidate.source_name[:200],
                "source_url": candidate.source_url,
                "source_media_url": candidate.source_media_url,
                "creator": candidate.creator[:300],
                "licence_id": candidate.licence_id[:120],
                "licence_url": candidate.licence_url,
                "rights_statement": candidate.rights_statement,
                "attribution_text": candidate.attribution_text,
                "source_retrieved_at": candidate.retrieved_at,
                "width": candidate.width,
                "height": candidate.height,
                "aspect_ratio": (
                    f"{candidate.width} / {candidate.height}"
                    if candidate.width and candidate.height
                    else ""
                ),
                "generated_by_ai": False,
                "status": MediaStatus.NEEDS_REVIEW,
            }
            if existing is None:
                MediaAsset.objects.create(
                    source_kind=candidate.source_kind,
                    external_id=candidate.external_id,
                    **defaults,
                )
                created += 1
                continue

            dirty_fields = []
            for field_name, value in defaults.items():
                if getattr(existing, field_name) != value:
                    setattr(existing, field_name, value)
                    dirty_fields.append(field_name)
            if dirty_fields:
                existing.save(update_fields=(*dirty_fields, "updated_at"))
                updated += 1
            else:
                unchanged += 1

        if dry_run:
            transaction.set_rollback(True)

    return CandidateIngestSummary(
        created=created,
        updated=updated,
        unchanged=unchanged,
        skipped_protected=skipped_protected,
        dry_run=dry_run,
    )


def _temporal_quality(asset: MediaAsset, target_date: date | None) -> str:
    if target_date is None:
        return "not_requested"
    if asset.valid_from == target_date and asset.valid_to in {None, target_date}:
        return "exact"
    if asset.date_precision == DatePrecision.YEAR:
        return "year"
    if asset.date_precision == DatePrecision.DECADE:
        return "decade"
    if asset.date_precision in {DatePrecision.RANGE, DatePrecision.ERA}:
        return asset.date_precision
    if asset.valid_from or asset.valid_to:
        return "range"
    return "unknown"


def select_published_media(
    *,
    role: str,
    country: Country | None = None,
    currency: Currency | None = None,
    target_date: date | None = None,
    aspect_ratio: str | None = None,
) -> SelectedMedia | None:
    if role not in MediaRole.values:
        raise ValueError("Unknown media role.")

    queryset = MediaAsset.objects.filter(status=MediaStatus.PUBLISHED, role=role)
    if role in _PHOTOGRAPHIC_ROLES:
        queryset = queryset.filter(
            kind=MediaKind.CONTEMPORARY_PHOTO,
            generated_by_ai=False,
        )
    if country is None:
        queryset = queryset.filter(country__isnull=True)
    else:
        queryset = queryset.filter(Q(country=country) | Q(country__isnull=True))
    if currency is None:
        queryset = queryset.filter(currency__isnull=True)
    else:
        queryset = queryset.filter(Q(currency=currency) | Q(currency__isnull=True))

    if target_date is not None:
        queryset = queryset.filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=target_date),
            Q(valid_to__isnull=True) | Q(valid_to__gte=target_date),
        )

    candidates = list(queryset.select_related("country", "currency"))
    if not candidates:
        return None

    def score(asset: MediaAsset) -> tuple[int, int, int, int, datetime, int]:
        semantic_specificity = 0
        if country is not None and asset.country_id == country.id:
            semantic_specificity += 2
        if currency is not None and asset.currency_id == currency.id:
            semantic_specificity += 1

        temporal_score = _TEMPORAL_SCORE.get(asset.date_precision, 0)
        if target_date is None:
            authenticity_rank = 3 if not asset.generated_by_ai else 2
        elif not asset.generated_by_ai and temporal_score > 0:
            authenticity_rank = 4
        elif asset.generated_by_ai and temporal_score > 0:
            authenticity_rank = 3
        elif not asset.generated_by_ai:
            authenticity_rank = 2
        else:
            authenticity_rank = 1

        aspect_match = int(bool(aspect_ratio and asset.aspect_ratio == aspect_ratio))
        return (
            semantic_specificity,
            authenticity_rank,
            temporal_score,
            aspect_match,
            asset.published_at or asset.updated_at,
            asset.pk,
        )

    selected = max(candidates, key=score)
    return SelectedMedia(
        asset=selected,
        selection_reason="published_media_priority",
        temporal_match_quality=_temporal_quality(selected, target_date),
        authenticity_class=(
            "ai_generated_illustration" if selected.generated_by_ai else "sourced_media"
        ),
    )

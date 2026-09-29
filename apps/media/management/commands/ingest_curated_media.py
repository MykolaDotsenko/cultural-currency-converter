from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.countries.models import Country, Currency
from apps.media.acquisition import MediaAcquisitionError, download_media_bytes
from apps.media.curated import CURATED_MEDIA, get_curated_media_spec
from apps.media.models import MediaAsset, MediaStatus
from apps.media.services import (
    DuplicateMediaContentError,
    MediaPublicationError,
    attach_media_bytes,
    upsert_media_candidates,
)
from apps.media.sources.base import MediaCandidate
from apps.media.validation import MediaValidationError, validate_raster_image

_PROTECTED_STATUSES = {
    MediaStatus.APPROVED,
    MediaStatus.PUBLISHED,
    MediaStatus.RETIRED,
    MediaStatus.REJECTED,
}


class Command(BaseCommand):
    help = (
        "Ingest one explicitly reviewed curated media source into managed storage. "
        "The command validates and sanitizes bytes but never approves or publishes media."
    )

    def add_arguments(self, parser):
        parser.add_argument("--slug", choices=sorted(CURATED_MEDIA), required=True)
        parser.add_argument(
            "--metadata-only",
            action="store_true",
            help="Create/update the review candidate without downloading source bytes.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the curated manifest and planned database change without network I/O.",
        )

    def handle(self, *args, **options):
        try:
            spec = get_curated_media_spec(options["slug"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        country = None
        if spec.country_code:
            country = Country.objects.filter(iso2=spec.country_code).first()
            if country is None:
                raise CommandError(
                    f"Curated media requires country {spec.country_code}; seed reference data first."
                )

        currency = None
        if spec.currency_code:
            currency = Currency.objects.filter(code=spec.currency_code).first()
            if currency is None:
                raise CommandError(
                    f"Curated media requires currency {spec.currency_code}; seed reference data first."
                )

        existing = MediaAsset.objects.filter(
            source_kind=spec.source_kind,
            external_id=spec.external_id,
        ).first()
        if existing is not None and existing.status in _PROTECTED_STATUSES:
            self.stdout.write(
                self.style.SUCCESS(
                    f"PROTECTED: slug={spec.slug} asset={existing.pk} status={existing.status}; "
                    "reviewed media was not modified."
                )
            )
            return

        candidate = MediaCandidate(
            source_kind=spec.source_kind,
            external_id=spec.external_id,
            title=spec.title,
            source_name=spec.source_name,
            source_url=spec.source_url,
            source_media_url=spec.source_media_url,
            creator=spec.creator,
            licence_id=spec.licence_id,
            licence_url=spec.licence_url,
            rights_statement=spec.rights_statement,
            attribution_text=spec.attribution_text,
            width=spec.expected_width,
            height=spec.expected_height,
            retrieved_at=timezone.now(),
        )

        try:
            summary = upsert_media_candidates(
                (candidate,),
                role=spec.role,
                kind=spec.kind,
                country=country,
                currency=currency,
                dry_run=options["dry_run"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN: slug={spec.slug} +{summary.created}/~{summary.updated}/"
                    f"={summary.unchanged}; no network or file writes performed."
                )
            )
            return

        asset = MediaAsset.objects.get(
            source_kind=spec.source_kind,
            external_id=spec.external_id,
        )
        asset.city = spec.city
        asset.alt_text = spec.alt_text
        asset.caption = spec.caption
        asset.valid_from = spec.valid_from
        asset.valid_to = spec.valid_to
        asset.date_precision = spec.date_precision
        asset.save(
            update_fields=(
                "city",
                "alt_text",
                "caption",
                "valid_from",
                "valid_to",
                "date_precision",
                "updated_at",
            )
        )

        if options["metadata_only"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"METADATA: slug={spec.slug} asset={asset.pk}; status={asset.status}; "
                    "source bytes were not downloaded."
                )
            )
            return

        if asset.storage_file:
            self.stdout.write(
                self.style.SUCCESS(
                    f"UNCHANGED: slug={spec.slug} asset={asset.pk} already has managed bytes; "
                    f"status={asset.status}."
                )
            )
            return

        try:
            downloaded = download_media_bytes(spec.source_media_url)
            if downloaded.final_url != spec.source_media_url:
                raise MediaAcquisitionError(
                    "Curated source redirected to an unexpected media URL; review the manifest."
                )

            validated = validate_raster_image(
                downloaded.data,
                filename=downloaded.filename,
            )
            if validated.width != spec.expected_width or validated.height != spec.expected_height:
                raise MediaAcquisitionError(
                    "Curated source dimensions changed; review the upstream file before ingesting."
                )

            attach_media_bytes(
                asset,
                downloaded.data,
                filename=downloaded.filename,
            )
        except (
            DuplicateMediaContentError,
            MediaAcquisitionError,
            MediaPublicationError,
            MediaValidationError,
        ) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"INGESTED: slug={spec.slug} asset={asset.pk} "
                f"sha256={asset.content_hash} size={asset.width}x{asset.height}; "
                f"status={asset.status}. Review before approval; do not publish the full-size "
                "source directly when a responsive derivative is appropriate."
            )
        )

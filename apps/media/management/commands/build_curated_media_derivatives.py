from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError

from apps.media.curated import (
    CURATED_MEDIA,
    CuratedMediaSpec,
    get_curated_media_spec,
)
from apps.media.models import MediaAsset, MediaStatus
from apps.media.services import (
    DuplicateMediaContentError,
    MediaPublicationError,
    create_responsive_derivative,
)
from apps.media.validation import MediaValidationError

_REVIEWED_SOURCE_STATUSES = {
    MediaStatus.APPROVED,
    MediaStatus.PUBLISHED,
}


@dataclass(frozen=True, slots=True)
class _DerivativePlan:
    spec: CuratedMediaSpec
    source: MediaAsset
    existing_widths: tuple[int, ...]
    missing_widths: tuple[int, ...]


def _source_scope_error(source: MediaAsset, spec: CuratedMediaSpec) -> str:
    country_code = source.country.iso2 if source.country_id else ""
    currency_code = source.currency.code if source.currency_id else ""
    expected = (
        spec.role,
        spec.kind,
        spec.country_code,
        spec.currency_code,
        spec.city,
        spec.focal_x,
        spec.focal_y,
    )
    actual = (
        source.role,
        source.kind,
        country_code,
        currency_code,
        source.city,
        source.focal_x,
        source.focal_y,
    )
    if actual != expected:
        return (
            f"Curated source metadata drift for {spec.slug}: "
            f"expected={expected!r} actual={actual!r}."
        )
    return ""


def _build_plan(spec: CuratedMediaSpec) -> _DerivativePlan:
    if not spec.responsive_widths:
        raise CommandError(f"Curated media {spec.slug} has no responsive-width plan.")

    source = (
        MediaAsset.objects.select_related("country", "currency")
        .filter(
            source_kind=spec.source_kind,
            external_id=spec.external_id,
            derivative_of__isnull=True,
        )
        .first()
    )
    if source is None:
        raise CommandError(
            f"Curated source {spec.slug} is not ingested. Run ingest_curated_media first."
        )
    if source.status not in _REVIEWED_SOURCE_STATUSES:
        raise CommandError(
            f"Curated source {spec.slug} must be explicitly approved before derivatives "
            f"are built; current status={source.status}."
        )
    if not source.storage_file:
        raise CommandError(f"Curated source {spec.slug} has no managed source bytes.")

    scope_error = _source_scope_error(source, spec)
    if scope_error:
        raise CommandError(scope_error)

    source_width = source.width or 0
    if any(width >= source_width for width in spec.responsive_widths):
        raise CommandError(
            f"Curated source {spec.slug} is only {source_width}px wide, which cannot satisfy "
            f"its responsive plan {spec.responsive_widths!r}."
        )

    raw_existing = tuple(
        MediaAsset.objects.filter(
            derivative_of=source,
            variant_width__in=spec.responsive_widths,
        )
        .exclude(variant_width__isnull=True)
        .values_list("variant_width", flat=True)
    )
    existing_widths = tuple(sorted(set(raw_existing)))
    if len(existing_widths) != len(raw_existing):
        raise CommandError(
            f"Curated source {spec.slug} has duplicate derivative widths; "
            "resolve the media records before continuing."
        )

    missing_widths = tuple(
        width for width in spec.responsive_widths if width not in existing_widths
    )
    return _DerivativePlan(
        spec=spec,
        source=source,
        existing_widths=existing_widths,
        missing_widths=missing_widths,
    )


class Command(BaseCommand):
    help = (
        "Create the reviewed responsive derivative plan declared by curated destination media. "
        "Existing widths are left unchanged and derivatives are never auto-published."
    )

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument("--slug", choices=sorted(CURATED_MEDIA))
        selection.add_argument(
            "--all-destination",
            action="store_true",
            help="Build plans for every curated item that declares responsive widths.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate every selected source and report missing widths without file writes.",
        )

    def handle(self, *args, **options):
        if options["slug"]:
            specs = (get_curated_media_spec(options["slug"]),)
        else:
            specs = tuple(
                get_curated_media_spec(slug)
                for slug, spec in sorted(CURATED_MEDIA.items())
                if spec.responsive_widths
            )

        # Preflight the whole selection before the first write so a bad source cannot
        # leave an avoidable half-built multi-country batch.
        plans = tuple(_build_plan(spec) for spec in specs)

        if options["dry_run"]:
            for plan in plans:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"DRY RUN: slug={plan.spec.slug} source={plan.source.pk} "
                        f"existing={plan.existing_widths!r} missing={plan.missing_widths!r}"
                    )
                )
            return

        for plan in plans:
            if not plan.missing_widths:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"UNCHANGED: slug={plan.spec.slug} source={plan.source.pk}; "
                        "responsive derivative plan already exists."
                    )
                )
                continue

            for width in plan.missing_widths:
                try:
                    derivative = create_responsive_derivative(plan.source, width=width)
                except (
                    DuplicateMediaContentError,
                    MediaPublicationError,
                    MediaValidationError,
                ) as exc:
                    raise CommandError(
                        f"Failed building {plan.spec.slug} at {width}px: {exc}"
                    ) from exc
                self.stdout.write(
                    self.style.SUCCESS(
                        f"CREATED: slug={plan.spec.slug} derivative={derivative.pk} "
                        f"source={plan.source.pk} width={width}; status={derivative.status}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Curated responsive build complete. Review and publish each derivative "
                "explicitly; source assets and new derivatives were not auto-published."
            )
        )

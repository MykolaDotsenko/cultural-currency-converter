from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError

from apps.media.curated import CURATED_MEDIA, CuratedMediaSpec, get_curated_media_spec
from apps.media.curated_runtime import (
    REVIEWED_SOURCE_STATUSES,
    curated_derivative_contract_error,
    curated_source_contract_error,
)
from apps.media.models import MediaAsset, MediaStatus


@dataclass(frozen=True, slots=True)
class _Coverage:
    spec: CuratedMediaSpec
    source: MediaAsset | None
    source_contract_matches: bool
    existing_widths: tuple[int, ...]
    published_widths: tuple[int, ...]
    derivative_contract_matches: bool

    @property
    def ready(self) -> bool:
        if self.source is None or self.source.status not in REVIEWED_SOURCE_STATUSES:
            return False
        if not self.source_contract_matches or not self.derivative_contract_matches:
            return False
        return set(self.spec.responsive_widths).issubset(self.published_widths)


def _coverage(spec: CuratedMediaSpec) -> _Coverage:
    source = (
        MediaAsset.objects.filter(
            source_kind=spec.source_kind,
            external_id=spec.external_id,
            derivative_of__isnull=True,
        )
        .order_by("-pk")
        .first()
    )
    if source is None:
        return _Coverage(
            spec=spec,
            source=None,
            source_contract_matches=False,
            existing_widths=(),
            published_widths=(),
            derivative_contract_matches=False,
        )

    derivatives = tuple(
        MediaAsset.objects.select_related("country", "currency")
        .filter(
            derivative_of=source,
            variant_width__in=spec.responsive_widths,
        )
        .exclude(variant_width__isnull=True)
        .order_by("variant_width", "pk")
    )
    raw_widths = tuple(
        derivative.variant_width
        for derivative in derivatives
        if derivative.variant_width is not None
    )
    existing_widths = tuple(sorted(set(raw_widths)))
    published_widths = tuple(
        sorted(
            {
                derivative.variant_width
                for derivative in derivatives
                if derivative.status == MediaStatus.PUBLISHED
                and derivative.variant_width is not None
            }
        )
    )

    source_contract_matches = not curated_source_contract_error(source, spec)
    derivative_contract_matches = len(raw_widths) == len(existing_widths)
    for derivative in derivatives:
        derivative_contract_matches = derivative_contract_matches and not bool(
            curated_derivative_contract_error(
                derivative,
                source=source,
                spec=spec,
            )
        )

    return _Coverage(
        spec=spec,
        source=source,
        source_contract_matches=source_contract_matches,
        existing_widths=existing_widths,
        published_widths=published_widths,
        derivative_contract_matches=derivative_contract_matches,
    )


class Command(BaseCommand):
    help = (
        "Report deployment readiness for curated responsive destination media without "
        "downloading, mutating or publishing anything."
    )

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group()
        selection.add_argument("--slug", choices=sorted(CURATED_MEDIA))
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit non-zero unless every selected responsive plan is runtime-ready.",
        )

    def handle(self, *args, **options):
        slug = options["slug"]
        if slug:
            specs = (get_curated_media_spec(slug),)
        else:
            specs = tuple(
                get_curated_media_spec(item_slug)
                for item_slug, spec in sorted(CURATED_MEDIA.items())
                if spec.responsive_widths
            )

        if not specs:
            self.stdout.write("No curated responsive destination media is configured.")
            return

        rows = tuple(_coverage(spec) for spec in specs)
        for row in rows:
            if row.source is None:
                source_status = "missing"
                source_id = "-"
                has_bytes = False
            else:
                source_status = row.source.status
                source_id = str(row.source.pk)
                has_bytes = bool(row.source.storage_file)

            state = "READY" if row.ready else "NOT_READY"
            self.stdout.write(
                f"{state}: slug={row.spec.slug} source={source_id} "
                f"source_status={source_status} bytes={str(has_bytes).lower()} "
                f"source_contract={str(row.source_contract_matches).lower()} "
                f"derivative_contract={str(row.derivative_contract_matches).lower()} "
                f"planned={row.spec.responsive_widths!r} "
                f"existing={row.existing_widths!r} published={row.published_widths!r}"
            )

        ready_count = sum(row.ready for row in rows)
        self.stdout.write(
            f"SUMMARY: ready={ready_count} total={len(rows)} not_ready={len(rows) - ready_count}"
        )
        if options["strict"] and ready_count != len(rows):
            raise CommandError(
                "Curated destination media is not fully runtime-ready; "
                "review the NOT_READY rows above."
            )

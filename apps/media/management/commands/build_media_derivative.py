from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.media.models import MediaAsset
from apps.media.services import (
    DuplicateMediaContentError,
    MediaPublicationError,
    create_responsive_derivative,
)
from apps.media.validation import MediaValidationError


class Command(BaseCommand):
    help = (
        "Create one or more sanitized WebP responsive derivatives from reviewed managed media. "
        "Derivatives are never auto-published."
    )

    def add_arguments(self, parser):
        parser.add_argument("--asset-id", type=int, required=True)
        parser.add_argument("--width", type=int, action="append", required=True)

    def handle(self, *args, **options):
        source = MediaAsset.objects.filter(pk=options["asset_id"]).first()
        if source is None:
            raise CommandError("MediaAsset does not exist.")
        raw_widths = options["width"]
        widths = raw_widths if isinstance(raw_widths, list) else [raw_widths]
        if len(set(widths)) != len(widths):
            raise CommandError("Derivative widths must be unique.")

        source_width = source.width or 0
        if any(width < 1 or width >= source_width for width in widths):
            raise CommandError("Each derivative width must be positive and smaller than the source.")

        existing_widths = set(
            MediaAsset.objects.filter(
                derivative_of=source,
                variant_width__in=widths,
            ).values_list("variant_width", flat=True)
        )
        if existing_widths:
            joined = ", ".join(str(width) for width in sorted(existing_widths) if width)
            raise CommandError(f"Derivative already exists for width(s): {joined}.")

        created = []
        for width in widths:
            try:
                derivative = create_responsive_derivative(source, width=width)
            except (
                DuplicateMediaContentError,
                MediaPublicationError,
                MediaValidationError,
            ) as exc:
                raise CommandError(str(exc)) from exc
            created.append(derivative)
            self.stdout.write(
                self.style.SUCCESS(
                    f"CREATED: derivative={derivative.pk} source={source.pk} "
                    f"size={derivative.width}x{derivative.height}; status={derivative.status}"
                )
            )

        if len(created) > 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"CREATED BATCH: source={source.pk} derivatives={len(created)}; "
                    "review and publish each derivative explicitly."
                )
            )

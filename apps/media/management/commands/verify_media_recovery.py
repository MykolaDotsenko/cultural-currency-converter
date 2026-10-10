"""Read-only checksum validation for a previously restored managed media object.

Must be run only after a separately approved storage-version restore. Verifying
object bytes does not establish S3 versioning, retention or recoverability.
"""

from __future__ import annotations

import hashlib
import re

from django.core.management.base import BaseCommand, CommandError

from apps.media.models import MediaAsset, MediaStatus

_MAX_MEDIA_BYTES = 64 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024


class Command(BaseCommand):
    help = "Compare published managed-media object bytes with recorded SHA-256."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--asset-id", type=int, required=True)

    def handle(self, *args, **options) -> None:
        asset = MediaAsset.objects.filter(pk=options["asset_id"]).only(
            "status", "content_hash", "storage_file"
        ).first()
        if asset is None:
            raise CommandError("Managed media record does not exist.")
        if asset.status != MediaStatus.PUBLISHED:
            raise CommandError("Only published managed media can prove the recovery contract.")
        if not asset.storage_file:
            raise CommandError("Published media object has no storage reference.")
        if not re.fullmatch(r"[a-f0-9]{64}", asset.content_hash or ""):
            raise CommandError("Published media has no valid recorded SHA-256 checksum.")

        digest = hashlib.sha256()
        total = 0
        try:
            with asset.storage_file.open("rb") as stored:
                while True:
                    chunk = stored.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_MEDIA_BYTES:
                        raise CommandError("Media object exceeds the bounded recovery-check size.")
                    digest.update(chunk)
        except CommandError:
            raise
        except Exception:
            # Object-storage client exceptions can contain internal bucket URLs,
            # signed query tokens or tenant identifiers. Never print them.
            raise CommandError("Published media object bytes are unavailable.") from None

        if total == 0 or digest.hexdigest() != asset.content_hash:
            raise CommandError("Published media recovery checksum mismatch.")
        self.stdout.write("VERIFIED: managed media storage bytes match recorded SHA-256.")

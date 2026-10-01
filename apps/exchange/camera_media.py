from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from apps.media.validation import MediaValidationError, validate_raster_image

MAX_CAMERA_UPLOAD_BYTES = 6 * 1024 * 1024
MAX_CAMERA_PIXELS = 16_000_000
MAX_CAMERA_DIMENSION = 6000
MAX_CAMERA_PROVIDER_DIMENSION = 2048


class CameraImageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedCameraImage:
    data: bytes
    mime_type: str
    width: int
    height: int


def prepare_camera_image(data: bytes, *, filename: str) -> PreparedCameraImage:
    try:
        validated = validate_raster_image(
            data,
            filename=filename,
            max_bytes=MAX_CAMERA_UPLOAD_BYTES,
        )
    except MediaValidationError as exc:
        raise CameraImageError(str(exc)) from exc

    if validated.width > MAX_CAMERA_DIMENSION or validated.height > MAX_CAMERA_DIMENSION:
        raise CameraImageError("Camera image dimensions are too large.")
    if validated.width * validated.height > MAX_CAMERA_PIXELS:
        raise CameraImageError("Camera image pixel count is too large.")

    try:
        with Image.open(io.BytesIO(data)) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail(
                (MAX_CAMERA_PROVIDER_DIMENSION, MAX_CAMERA_PROVIDER_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            if image.mode in {"RGBA", "LA"}:
                rgba = image.convert("RGBA")
                flattened = Image.new("RGB", rgba.size, "white")
                flattened.paste(rgba, mask=rgba.getchannel("A"))
                image = flattened
            elif image.mode != "RGB":
                image = image.convert("RGB")

            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=88,
                optimize=True,
                progressive=True,
            )
            width, height = image.size
    except OSError as exc:
        raise CameraImageError("Camera image could not be normalized safely.") from exc

    normalized = output.getvalue()
    if not normalized:
        raise CameraImageError("Camera image normalization produced no data.")

    return PreparedCameraImage(
        data=normalized,
        mime_type="image/jpeg",
        width=width,
        height=height,
    )

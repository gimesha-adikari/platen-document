"""Canonical PDF-page geometry and raster preparation.

All canonical rectangles use visible CropBox-relative PDF points, top-left
origin, X right and Y down.  Raster dimensions come from the raster itself;
no nominal DPI is used to infer its size.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pymupdf as fitz
from PIL import Image, ImageOps

from .contracts import PageGeometry, Rect


class RasterDpiMetadataPolicy(str, Enum):
    """Control DPI metadata on the encoded OCR raster without changing pixels."""

    EMBED_DPI = "embed_dpi"
    OMIT_DPI = "omit_dpi"

    @classmethod
    def coerce(cls, value: "RasterDpiMetadataPolicy | str") -> "RasterDpiMetadataPolicy":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            supported = ", ".join(item.value for item in cls)
            raise ValueError(
                f"unsupported raster DPI metadata policy: {value!r}; expected one of: {supported}"
            ) from exc


def normalize_rotation(rotation: int) -> int:
    value = int(rotation) % 360
    if value not in (0, 90, 180, 270):
        raise ValueError(f"unsupported PDF rotation: {rotation}")
    return value


def page_geometry_from_pdf(page: Any, *, pixel_width: int | None = None, pixel_height: int | None = None) -> PageGeometry:
    """Read the visible, rotated page rect exposed by PyMuPDF."""

    rect = page.rect
    return PageGeometry(
        width=float(rect.width),
        height=float(rect.height),
        rotation=normalize_rotation(getattr(page, "rotation", 0)),
        pixel_width=pixel_width,
        pixel_height=pixel_height,
    )


def pixel_rect_to_points(box: tuple[float, float, float, float], geometry: PageGeometry) -> Rect:
    """Convert an x0/y0/x1/y1 raster box using actual raster dimensions."""

    if not geometry.pixel_width or not geometry.pixel_height:
        raise ValueError("pixel dimensions are required for raster geometry conversion")
    x0, y0, x1, y1 = (float(value) for value in box)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("raster box must have positive area")
    return Rect(
        x=x0 * geometry.width / geometry.pixel_width,
        y=y0 * geometry.height / geometry.pixel_height,
        width=(x1 - x0) * geometry.width / geometry.pixel_width,
        height=(y1 - y0) * geometry.height / geometry.pixel_height,
    )


def clamp_rect(rect: Rect, geometry: PageGeometry) -> Rect:
    x0 = max(0.0, min(geometry.width, rect.x))
    y0 = max(0.0, min(geometry.height, rect.y))
    x1 = max(x0, min(geometry.width, rect.x1))
    y1 = max(y0, min(geometry.height, rect.y1))
    return Rect(x0, y0, x1 - x0, y1 - y0)


def visible_rect_to_native_pdf(rect: Rect, geometry: PageGeometry) -> Rect:
    """Map a visible CropBox rectangle into PyMuPDF's unrotated PDF space.

    ``PageGeometry`` describes the visible, rotated page while native
    ``page.get_text("words")`` boxes and annotation writers use the
    unrotated CropBox coordinate space.  OCR adapters already emit visible
    rectangles, so callers must use this conversion only when crossing from
    the public visible-region contract into a native PDF writer or native
    word-intersection operation.
    """

    rotation = normalize_rotation(geometry.rotation)
    if rotation == 0:
        return rect
    if rotation == 90:
        return Rect(
            x=rect.y,
            y=geometry.width - rect.x1,
            width=rect.height,
            height=rect.width,
        )
    if rotation == 180:
        return Rect(
            x=geometry.width - rect.x1,
            y=geometry.height - rect.y1,
            width=rect.width,
            height=rect.height,
        )
    return Rect(
        x=geometry.height - rect.y1,
        y=rect.x,
        width=rect.height,
        height=rect.width,
    )


@dataclass(frozen=True)
class PreparedRaster:
    image: Image.Image
    png_bytes: bytes
    geometry: PageGeometry
    dpi: int


class RasterPreparer:
    """Render a PDF page and normalize EXIF orientation before OCR."""

    def __init__(
        self,
        dpi: int = 200,
        *,
        dpi_metadata_policy: RasterDpiMetadataPolicy | str = RasterDpiMetadataPolicy.EMBED_DPI,
    ) -> None:
        if dpi <= 0:
            raise ValueError("dpi must be positive")
        self.dpi = dpi
        self.dpi_metadata_policy = RasterDpiMetadataPolicy.coerce(dpi_metadata_policy)

    def prepare(self, page: Any) -> PreparedRaster:
        scale = self.dpi / 72.0
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        raw = pixmap.tobytes("png")
        with Image.open(io.BytesIO(raw)) as loaded:
            image = ImageOps.exif_transpose(loaded).convert("RGB")
        encoded = io.BytesIO()
        if self.dpi_metadata_policy is RasterDpiMetadataPolicy.EMBED_DPI:
            image.save(encoded, format="PNG", dpi=(self.dpi, self.dpi))
        else:
            image.save(encoded, format="PNG")
        geometry = page_geometry_from_pdf(page, pixel_width=image.width, pixel_height=image.height)
        return PreparedRaster(image=image, png_bytes=encoded.getvalue(), geometry=geometry, dpi=self.dpi)

"""Renders ONE certificate PDF.

The single predefined template is split in two: templates/certificate_template.json
holds the wording and colours; the layout (landscape A4, border, positions) is
drawn in code with reportlab. No template editor and no multiple designs, as
the brief specifies.

Limitation: the built-in PDF fonts only cover Latin (WinAnsi) characters.
Text outside that set raises GenerationError so the failure is recorded for
that recipient instead of silently printing garbage. To support e.g. Devanagari,
register a TTF font with reportlab and use it in place of Helvetica.
"""
import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.core.config import settings

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
CONTENT_WIDTH = PAGE_WIDTH - 160  # horizontal margins inside the border


class GenerationError(Exception):
    """Raised when a single certificate cannot be generated."""


@lru_cache(maxsize=1)
def load_template() -> dict:
    """Read the predefined template once and cache it."""
    path = Path(settings.template_dir) / "certificate_template.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationError(f"Certificate template could not be loaded: {exc}") from exc


def _ensure_renderable(label: str, text: str) -> None:
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        raise GenerationError(f"{label} contains characters the certificate font cannot render")


def _fit_font_size(text: str, font: str, max_size: int, min_size: int, max_width: float) -> int:
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def generate_certificate(
    *,
    recipient_name: str,
    course_name: str,
    issued_by: str,
    issue_date: date,
    output_path: Path,
) -> Path:
    """Write one PDF to output_path and return the path.

    The file is written to a temp name and renamed, so a failure never leaves a
    half-written certificate behind.
    """
    tpl = load_template()
    primary = colors.HexColor(tpl["colors"]["primary"])
    muted = colors.HexColor(tpl["colors"]["text"])
    name_color = colors.HexColor(tpl["colors"]["name"])

    _ensure_renderable("Recipient name", recipient_name)
    _ensure_renderable("Course name", course_name)
    _ensure_renderable("Issuer", issued_by)

    name_font = "Helvetica-Bold"
    name_size = _fit_font_size(recipient_name, name_font, 40, 10, CONTENT_WIDTH)
    if stringWidth(recipient_name, name_font, name_size) > CONTENT_WIDTH:
        raise GenerationError("Recipient name is too long to fit on the certificate")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp")

    try:
        c = canvas.Canvas(str(tmp_path), pagesize=landscape(A4))
        cx = PAGE_WIDTH / 2

        # Double border
        c.setStrokeColor(primary)
        c.setLineWidth(4)
        c.rect(25, 25, PAGE_WIDTH - 50, PAGE_HEIGHT - 50)
        c.setLineWidth(1)
        c.rect(35, 35, PAGE_WIDTH - 70, PAGE_HEIGHT - 70)

        # Title
        c.setFillColor(primary)
        c.setFont("Helvetica-Bold", 36)
        c.drawCentredString(cx, PAGE_HEIGHT - 120, tpl["title"])

        c.setFillColor(muted)
        c.setFont("Helvetica", 16)
        c.drawCentredString(cx, PAGE_HEIGHT - 175, tpl["intro_text"])

        # Recipient name
        c.setFillColor(name_color)
        c.setFont(name_font, name_size)
        c.drawCentredString(cx, PAGE_HEIGHT - 240, recipient_name)
        c.setLineWidth(0.8)
        c.line(cx - 220, PAGE_HEIGHT - 252, cx + 220, PAGE_HEIGHT - 252)

        c.setFillColor(muted)
        c.setFont("Helvetica", 16)
        c.drawCentredString(cx, PAGE_HEIGHT - 290, tpl["completion_text"])

        # Course name (wrapped, may be long)
        c.setFillColor(primary)
        c.setFont("Helvetica-Bold", 24)
        y = PAGE_HEIGHT - 330
        for line in simpleSplit(course_name, "Helvetica-Bold", 24, CONTENT_WIDTH)[:3]:
            c.drawCentredString(cx, y, line)
            y -= 30

        # Footer: date and issuer
        c.setFillColor(muted)
        c.setFont("Helvetica", 13)
        c.drawString(90, 90, f"{tpl['date_label']}: {issue_date.strftime(tpl['date_format'])}")
        c.drawRightString(PAGE_WIDTH - 90, 90, f"{tpl['issuer_label']}: {issued_by}")

        c.save()
        os.replace(tmp_path, output_path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        if isinstance(exc, GenerationError):
            raise
        raise GenerationError(f"PDF rendering failed: {exc}") from exc

    return output_path
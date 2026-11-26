"""Export notulen rapat ke TXT dan PDF (Sprint 10).

Prinsip penting:

* Modul ini **hanya membaca** data yang sudah tersimpan. Tidak ada provider AI,
  tidak ada ``db.commit()``, tidak ada file audio yang dibuka, dan tidak ada
  file sementara di disk — PDF/TXT dibangun di memori (``io.BytesIO``).
* Bagian yang belum tersedia tidak dikarang: setiap bagian kosong mendapat
  keterangan eksplisit, dan status pipeline ikut dicantumkan supaya export
  parsial tidak menyesatkan.
* Nama file dan teks PDF disanitasi; path internal, exception, dan secret
  tidak pernah masuk ke dokumen maupun response.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session, joinedload

from ..core.config import settings
from ..models.action_item import ActionExtractionStatus, ActionItem, ActionItemJob
from ..models.diarization import DiarizationJob, DiarizationStatus, Speaker
from ..models.meeting import Meeting
from ..models.summary import MeetingSummary, SummaryJob, SummaryStatus
from ..models.transcript import TranscriptionJob, TranscriptionStatus, TranscriptSegment

logger = logging.getLogger("meetnote.export")

TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"
PDF_MEDIA_TYPE = "application/pdf"

# ---------------------------------------------------------------------------
# Font PDF: pakai TTF yang dibundling reportlab (Bitstream Vera). Tidak perlu
# font sistem, tidak ada file baru di repo, dan mencakup Latin-1/Latin Extended
# yang dipakai bahasa Indonesia (é, è, ñ, tanda kutip tipis, dll).
# ---------------------------------------------------------------------------

_FONT_REGULAR = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_GLYPHS: set[int] = set()


def _setup_fonts() -> None:
    global _FONT_REGULAR, _FONT_BOLD, _FONT_GLYPHS
    try:
        import reportlab
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
        regular = font_dir / "Vera.ttf"
        bold = font_dir / "VeraBd.ttf"
        if not (regular.is_file() and bold.is_file()):
            return
        pdfmetrics.registerFont(TTFont("NotulenSans", str(regular)))
        pdfmetrics.registerFont(TTFont("NotulenSans-Bold", str(bold)))
        pdfmetrics.registerFontFamily(
            "NotulenSans",
            normal="NotulenSans",
            bold="NotulenSans-Bold",
            italic="NotulenSans",
            boldItalic="NotulenSans-Bold",
        )
        _FONT_REGULAR = "NotulenSans"
        _FONT_BOLD = "NotulenSans-Bold"
        _FONT_GLYPHS = set(pdfmetrics.getFont(_FONT_REGULAR).face.charToGlyph)
    except Exception as exc:  # pragma: no cover - fallback font bawaan
        # Jangan pernah memasukkan pesan exception ke log (bisa memuat path).
        logger.warning("pdf_font_fallback error_category=%s", type(exc).__name__)


_setup_fonts()

# Karakter yang sering muncul dari provider tapi tidak selalu didukung font.
_PDF_REPLACEMENTS = {
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u2022": "-",
    "\ufeff": "",
}

# ---------------------------------------------------------------------------
# Struktur data hasil audit (snapshot), bebas dari ORM lazy-load.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeakerLine:
    label: str
    display_name: str | None = None

    @property
    def display(self) -> str:
        if self.display_name:
            return f"{self.label} ({self.display_name})"
        return self.label


@dataclass(frozen=True)
class SummaryItemLine:
    title: str
    detail: str
    source: str


@dataclass(frozen=True)
class DecisionLine:
    text: str
    source: str


@dataclass(frozen=True)
class ActionLine:
    title: str
    description: str
    assignee: str | None
    deadline: str | None
    status: str
    source: str
    is_manually_edited: bool


@dataclass(frozen=True)
class SegmentLine:
    timestamp: str
    speaker: str
    text: str


@dataclass(frozen=True)
class NotulenData:
    meeting_id: str
    title: str
    meeting_status: str
    created_at: str
    duration_seconds: str | None
    statuses: dict[str, str]
    speakers: tuple[SpeakerLine, ...]
    has_summary: bool
    overview: str
    topics: tuple[SummaryItemLine, ...]
    decisions: tuple[DecisionLine, ...]
    action_items: tuple[ActionLine, ...]
    segments: tuple[SegmentLine, ...]


# ---------------------------------------------------------------------------
# Helper format
# ---------------------------------------------------------------------------


def format_clock(seconds: object) -> str:
    """m:ss (atau h:mm:ss) dari angka apa pun; tidak pernah mengarang nilai."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = 0.0
    if value < 0 or value != value:  # NaN
        value = 0.0
    total = int(value)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_datetime(value: object) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return ""


def _format_duration(value: object) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return format_clock(number)


def _source_clock(start: object, end: object) -> str:
    """Rentang waktu yang benar-benar tersimpan, atau '' bila tidak ada."""
    try:
        start_value = float(start)
        end_value = float(end)
    except (TypeError, ValueError):
        return ""
    if start_value < 0 or end_value < 0:
        return ""
    if end_value < start_value:
        end_value = start_value
    return f"{format_clock(start_value)}–{format_clock(end_value)}"


def _as_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _dict_value(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, dict) else None  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Pengambilan data (READ-ONLY)
# ---------------------------------------------------------------------------


def _job_status(db: Session, model: type, meeting_id: str, fallback: str) -> str:
    row = (
        db.query(model.status)
        .filter(model.meeting_id == meeting_id)
        .first()
    )
    return _as_text(row[0]) if row and row[0] else fallback


def load_notulen(db: Session, meeting_id: uuid.UUID) -> NotulenData:
    """Kumpulkan snapshot notulen. Melempar 404 bila meeting tidak ada."""
    meeting_id_text = str(meeting_id)
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id_text).first()
    if meeting is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Meeting tidak ditemukan.",
        )

    speakers_db = (
        db.query(Speaker)
        .filter(Speaker.meeting_id == meeting_id_text)
        .order_by(Speaker.speaker_label.asc())
        .all()
    )
    speakers = tuple(
        SpeakerLine(
            label=_as_text(speaker.speaker_label) or "Speaker ?",
            display_name=speaker.display_name or None,
        )
        for speaker in speakers_db
    )

    summary_db: MeetingSummary | None = (
        db.query(MeetingSummary)
        .filter(MeetingSummary.meeting_id == meeting_id_text)
        .first()
    )

    topics: list[SummaryItemLine] = []
    decisions: list[DecisionLine] = []
    if summary_db is not None:
        for raw in list(summary_db.topics or []):
            topics.append(
                SummaryItemLine(
                    title=_as_text(_dict_value(raw, "title")),
                    detail=_as_text(_dict_value(raw, "detail")),
                    source=_source_clock(
                        _dict_value(raw, "start_seconds"),
                        _dict_value(raw, "end_seconds"),
                    ),
                )
            )
        for raw in list(summary_db.decisions or []):
            decisions.append(
                DecisionLine(
                    text=_as_text(_dict_value(raw, "text")),
                    source=_source_clock(
                        _dict_value(raw, "start_seconds"),
                        _dict_value(raw, "end_seconds"),
                    ),
                )
            )

    items_db = (
        db.query(ActionItem)
        .options(joinedload(ActionItem.sources), joinedload(ActionItem.assignee_speaker))
        .filter(ActionItem.meeting_id == meeting_id_text)
        .order_by(ActionItem.created_at.asc(), ActionItem.id.asc())
        .all()
    )
    action_items: list[ActionLine] = []
    for item in items_db:
        assignee: str | None = None
        if item.assignee_speaker is not None:
            label = _as_text(item.assignee_speaker.speaker_label)
            name = item.assignee_speaker.display_name
            assignee = f"{label} ({name})" if name else (label or None)
        if not assignee:
            assignee = item.assignee_text or None

        deadline = item.due_date.isoformat() if item.due_date else None
        if item.deadline_text:
            deadline = f"{deadline} ({item.deadline_text})" if deadline else item.deadline_text

        action_items.append(
            ActionLine(
                title=_as_text(item.title),
                description=_as_text(item.description),
                assignee=assignee,
                deadline=deadline,
                status=_as_text(item.status) or "—",
                source=_source_clock(item.start_seconds, item.end_seconds),
                is_manually_edited=bool(item.is_manually_edited),
            )
        )

    segments_db = (
        db.query(TranscriptSegment)
        .options(joinedload(TranscriptSegment.speaker))
        .filter(TranscriptSegment.meeting_id == meeting_id_text)
        .order_by(TranscriptSegment.sequence.asc())
        .all()
    )
    segments: list[SegmentLine] = []
    for segment in segments_db:
        if segment.speaker is not None:
            label = _as_text(segment.speaker.speaker_label) or "Speaker ?"
            name = segment.speaker.display_name
            speaker_text = f"{label} ({name})" if name else label
        else:
            speaker_text = "—"
        segments.append(
            SegmentLine(
                timestamp=(
                    f"{format_clock(segment.start_seconds)} - "
                    f"{format_clock(segment.end_seconds)}"
                ),
                speaker=speaker_text,
                text=_as_text(segment.text),
            )
        )

    statuses = {
        "transkripsi": _job_status(
            db, TranscriptionJob, meeting_id_text, TranscriptionStatus.NOT_STARTED
        ),
        "diarisasi": _job_status(
            db, DiarizationJob, meeting_id_text, DiarizationStatus.NOT_STARTED
        ),
        "ringkasan": _job_status(
            db, SummaryJob, meeting_id_text, SummaryStatus.NOT_STARTED
        ),
        "action items": _job_status(
            db, ActionItemJob, meeting_id_text, ActionExtractionStatus.NOT_STARTED
        ),
    }

    duration = _format_duration(getattr(meeting.recording, "duration_seconds", None))

    return NotulenData(
        meeting_id=meeting_id_text,
        title=_as_text(meeting.title),
        meeting_status=_as_text(meeting.status),
        created_at=_format_datetime(meeting.created_at),
        duration_seconds=duration,
        statuses=statuses,
        speakers=speakers,
        has_summary=summary_db is not None,
        overview=_as_text(summary_db.overview) if summary_db is not None else "",
        topics=tuple(topics),
        decisions=tuple(decisions),
        action_items=tuple(action_items),
        segments=tuple(segments),
    )


# ---------------------------------------------------------------------------
# Render TXT
# ---------------------------------------------------------------------------

_SEPARATOR = "-" * 64
_NOT_AVAILABLE = "Belum tersedia."


def render_txt(data: NotulenData) -> str:
    lines: list[str] = [
        "NOTULEN RAPAT",
        "=" * 64,
        "Dibuat oleh MeetNote AI dari data yang tersimpan (tanpa proses AI saat export).",
        "",
        "INFORMASI RAPAT",
        _SEPARATOR,
        f"Judul           : {data.title}",
        f"Tanggal dibuat  : {data.created_at or _NOT_AVAILABLE}",
        f"Status meeting  : {data.meeting_status}",
        f"ID meeting      : {data.meeting_id}",
        f"Durasi rekaman  : {data.duration_seconds or _NOT_AVAILABLE}",
    ]
    for label, value in data.statuses.items():
        lines.append(f"Status {label:<14}: {value}")

    lines.extend(["", "PEMBICARA", _SEPARATOR])
    if data.speakers:
        for speaker in data.speakers:
            lines.append(f"- {speaker.display}")
    else:
        lines.append(_NOT_AVAILABLE)

    lines.extend(["", "RINGKASAN EKSEKUTIF", _SEPARATOR])
    if data.has_summary and data.overview:
        lines.append(data.overview)
    else:
        lines.append(_NOT_AVAILABLE)

    lines.extend(["", "TOPIK PEMBAHASAN", _SEPARATOR])
    if data.topics:
        for index, topic in enumerate(data.topics, start=1):
            lines.append(f"{index}. {topic.title or '(topik tanpa judul)'}")
            if topic.detail:
                lines.append(f"   {topic.detail}")
            if topic.source:
                lines.append(f"   Sumber: {topic.source}")
    else:
        lines.append(_NOT_AVAILABLE)

    lines.extend(["", "KEPUTUSAN", _SEPARATOR])
    if data.decisions:
        for index, decision in enumerate(data.decisions, start=1):
            lines.append(f"{index}. {decision.text or '(keputusan tanpa teks)'}")
            if decision.source:
                lines.append(f"   Sumber: {decision.source}")
    else:
        lines.append(_NOT_AVAILABLE)

    lines.extend(["", "ACTION ITEMS", _SEPARATOR])
    if data.action_items:
        for index, item in enumerate(data.action_items, start=1):
            lines.append(f"{index}. [{item.status}] {item.title}")
            if item.description:
                lines.append(f"   Deskripsi       : {item.description}")
            lines.append(f"   Penanggung jawab: {item.assignee or _NOT_AVAILABLE}")
            lines.append(f"   Deadline        : {item.deadline or _NOT_AVAILABLE}")
            if item.source:
                lines.append(f"   Sumber          : {item.source}")
            if item.is_manually_edited:
                lines.append("   (diedit manual)")
    else:
        lines.append(_NOT_AVAILABLE)

    lines.extend(["", "TRANSKRIP", _SEPARATOR])
    if data.segments:
        for segment in data.segments:
            prefix = f"[{segment.timestamp}]"
            if segment.speaker != "—":
                prefix = f"{prefix} {segment.speaker}:"
            lines.append(f"{prefix} {segment.text}")
    else:
        lines.append(_NOT_AVAILABLE)

    lines.extend(["", _SEPARATOR, "Akhir dokumen."])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Render PDF
# ---------------------------------------------------------------------------


def _pdf_plain(value: object) -> str:
    """Normalisasi glyph untuk teks canvas/metadata (tanpa escape XML)."""
    text = unicodedata.normalize("NFC", _as_text(value))
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    for old, new in _PDF_REPLACEMENTS.items():
        text = text.replace(old, new)
    output: list[str] = []
    for character in text:
        codepoint = ord(character)
        if _FONT_GLYPHS and codepoint in _FONT_GLYPHS:
            output.append(character)
        elif 32 <= codepoint < 127:
            output.append(character)
        else:
            output.append("?")
    return "".join(output)


def _pdf_text(value: object) -> str:
    """Amankan teks untuk Paragraph PDF (XML + glyph yang tidak didukung)."""
    text = unicodedata.normalize("NFC", _as_text(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for old, new in _PDF_REPLACEMENTS.items():
        text = text.replace(old, new)
    output: list[str] = []
    for character in text:
        codepoint = ord(character)
        if character in ("\n", "\t"):
            output.append(character)
        elif _FONT_GLYPHS and codepoint in _FONT_GLYPHS:
            output.append(character)
        elif 32 <= codepoint < 127:
            output.append(character)
        else:
            output.append("?")
    escaped = xml_escape("".join(output))
    return escaped.replace("\n", "<br/>")


def _pdf_paragraph(text: object, style) -> object:
    from reportlab.platypus import Paragraph

    return Paragraph(_pdf_text(text), style)


def _section_heading(text: str, style) -> object:
    from reportlab.platypus import KeepTogether, Paragraph, Spacer

    return KeepTogether([Spacer(1, 8), Paragraph(_pdf_text(text), style), Spacer(1, 4)])


def render_pdf(data: NotulenData) -> bytes:
    """Bangun PDF di memori. Tidak menulis file sementara apa pun."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        title=f"Notulen - {_pdf_plain(data.title)}",
        author=settings.APP_NAME,
        subject="Notulen rapat MeetNote AI",
    )

    body = ParagraphStyle(
        "NotulenBody",
        fontName=_FONT_REGULAR,
        fontSize=9.5,
        leading=13.5,
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "NotulenSmall", parent=body, fontSize=8, leading=11, textColor=colors.HexColor("#6b7280")
    )
    heading = ParagraphStyle(
        "NotulenHeading",
        fontName=_FONT_BOLD,
        fontSize=12,
        leading=15,
        spaceBefore=6,
        textColor=colors.HexColor("#1d4ed8"),
    )
    title_style = ParagraphStyle(
        "NotulenTitle", fontName=_FONT_BOLD, fontSize=19, leading=24, spaceAfter=2
    )
    cell = ParagraphStyle("NotulenCell", parent=body, fontSize=8, leading=10.5, spaceAfter=0)
    cell_head = ParagraphStyle(
        "NotulenCellHead", parent=cell, fontName=_FONT_BOLD, textColor=colors.white
    )

    def decorate(canvas, doc) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setFont(_FONT_REGULAR, 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(18 * mm, height - 14 * mm, _pdf_plain(settings.APP_NAME))
        canvas.drawRightString(
            width - 18 * mm, height - 14 * mm, _pdf_plain("Notulen Rapat")
        )
        canvas.setStrokeColor(colors.HexColor("#e5e7eb"))
        canvas.line(18 * mm, height - 16 * mm, width - 18 * mm, height - 16 * mm)
        canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
        canvas.drawString(18 * mm, 10 * mm, _pdf_plain(data.title[:60]))
        canvas.drawRightString(
            width - 18 * mm, 10 * mm, _pdf_plain(f"Halaman {canvas.getPageNumber()}")
        )
        canvas.restoreState()

    story: list[object] = [
        _pdf_paragraph(data.title, title_style),
        _pdf_paragraph("Notulen rapat - dokumen dari data yang tersimpan", small),
        Spacer(1, 8),
    ]

    info_rows = [
        ("Judul", data.title),
        ("Tanggal dibuat", data.created_at or _NOT_AVAILABLE),
        ("Status meeting", data.meeting_status),
        ("ID meeting", data.meeting_id),
        ("Durasi rekaman", data.duration_seconds or _NOT_AVAILABLE),
    ]
    info_rows.extend((f"Status {key}", value) for key, value in data.statuses.items())
    info_table = Table(
        [[_pdf_paragraph(label, cell_head), _pdf_paragraph(value, cell)] for label, value in info_rows],
        colWidths=[42 * mm, 132 * mm],
    )
    info_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#2563eb")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ]
        )
    )
    story.append(info_table)

    story.append(_section_heading("PEMBICARA", heading))
    if data.speakers:
        for speaker in data.speakers:
            story.append(Paragraph(f"&bull; {_pdf_text(speaker.display)}", body))
    else:
        story.append(Paragraph(_pdf_text(_NOT_AVAILABLE), small))

    story.append(_section_heading("RINGKASAN EKSEKUTIF", heading))
    if data.has_summary and data.overview:
        story.append(Paragraph(_pdf_text(data.overview), body))
    else:
        story.append(Paragraph(_pdf_text(_NOT_AVAILABLE), small))

    story.append(_section_heading("TOPIK PEMBAHASAN", heading))
    if data.topics:
        for index, topic in enumerate(data.topics, start=1):
            source = f" <font color='#6b7280'>[{_pdf_text(topic.source)}]</font>" if topic.source else ""
            story.append(
                Paragraph(
                    f"<b>{index}. {_pdf_text(topic.title or '(topik tanpa judul)')}</b>{source}",
                    body,
                )
            )
            if topic.detail:
                story.append(Paragraph(_pdf_text(topic.detail), body))
    else:
        story.append(Paragraph(_pdf_text(_NOT_AVAILABLE), small))

    story.append(_section_heading("KEPUTUSAN", heading))
    if data.decisions:
        for index, decision in enumerate(data.decisions, start=1):
            source = f" <font color='#6b7280'>[{_pdf_text(decision.source)}]</font>" if decision.source else ""
            story.append(
                Paragraph(
                    f"{index}. {_pdf_text(decision.text or '(keputusan tanpa teks)')}{source}",
                    body,
                )
            )
    else:
        story.append(Paragraph(_pdf_text(_NOT_AVAILABLE), small))

    story.append(_section_heading("ACTION ITEMS", heading))
    if data.action_items:
        table_data = [
            [
                _pdf_paragraph(label, cell_head)
                for label in ("No", "Tugas / deskripsi", "Penanggung jawab", "Deadline", "Status", "Sumber")
            ]
        ]
        for index, item in enumerate(data.action_items, start=1):
            task = f"<b>{_pdf_text(item.title)}</b>"
            if item.description:
                task += f"<br/>{_pdf_text(item.description)}"
            if item.is_manually_edited:
                task += "<br/><font color='#6b7280'>(diedit manual)</font>"
            table_data.append(
                [
                    _pdf_paragraph(str(index), cell),
                    Paragraph(task, cell),
                    _pdf_paragraph(item.assignee or "-", cell),
                    _pdf_paragraph(item.deadline or "-", cell),
                    _pdf_paragraph(item.status, cell),
                    _pdf_paragraph(item.source or "-", cell),
                ]
            )
        action_table = Table(
            table_data,
            colWidths=[10 * mm, 56 * mm, 32 * mm, 30 * mm, 21 * mm, 25 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        action_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f9fafb")],
                    ),
                ]
            )
        )
        story.append(action_table)
    else:
        story.append(Paragraph(_pdf_text(_NOT_AVAILABLE), small))

    story.append(PageBreak())
    story.append(_section_heading("LAMPIRAN - TRANSKRIP", heading))
    if data.segments:
        for segment in data.segments:
            speaker = f" {_pdf_text(segment.speaker)}:" if segment.speaker != "-" else ""
            story.append(
                Paragraph(
                    f"<font color='#6b7280'>[{_pdf_text(segment.timestamp)}]</font>"
                    f"<b>{speaker}</b> {_pdf_text(segment.text)}",
                    body,
                )
            )
    else:
        story.append(Paragraph(_pdf_text(_NOT_AVAILABLE), small))

    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            _pdf_text(
                "Dokumen ini dibuat dari data yang tersimpan. Export tidak menjalankan "
                "proses AI dan tidak mengubah data rapat."
            ),
            small,
        )
    )

    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Nama file aman
# ---------------------------------------------------------------------------


def export_filename(title: str, extension: str) -> str:
    """Nama file ASCII aman untuk Content-Disposition (tanpa path/quote)."""
    normalized = unicodedata.normalize("NFKD", _as_text(title))
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title).strip("-").lower()
    slug = slug[:60].rstrip("-") or "rapat"
    return f"notulen-{slug}.{extension}"

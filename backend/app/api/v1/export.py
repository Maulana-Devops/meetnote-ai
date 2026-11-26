"""Endpoint export notulen (Sprint 10).

GET TXT/PDF hanya membaca data yang sudah tersimpan. Tidak ada AI generation,
tidak ada penulisan database, tidak ada file sementara, dan tidak ada akses
langsung ke file audio. Hasil dibangun di memori lalu dikembalikan sebagai
attachment dengan nama file yang sudah disanitasi.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Response
from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from ...services.export import (
    PDF_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
    export_filename,
    load_notulen,
    render_pdf,
    render_txt,
)
from .meetings import get_db

router = APIRouter(prefix="/meetings", tags=["Export"])
logger = logging.getLogger("meetnote.export")


def _build_response(meeting_id: uuid.UUID, db: Session, extension: str) -> Response:
    try:
        data = load_notulen(db, meeting_id)
        if extension == "txt":
            content = render_txt(data).encode("utf-8")
            media_type = TEXT_MEDIA_TYPE
        else:
            content = render_pdf(data)
            media_type = PDF_MEDIA_TYPE
        filename = export_filename(data.title, extension)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - jalur error tak terduga
        # Kategori saja. Pesan exception dapat memuat path/internal detail.
        logger.error("export_failed error_category=%s", type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal membuat dokumen export.",
        ) from None

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{meeting_id}/export/txt")
def export_meeting_txt(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Unduh notulen meeting sebagai berkas teks UTF-8."""
    return _build_response(meeting_id, db, "txt")


@router.get("/{meeting_id}/export/pdf")
def export_meeting_pdf(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Unduh notulen meeting sebagai dokumen PDF."""
    return _build_response(meeting_id, db, "pdf")

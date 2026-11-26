"""Kontrak provider LLM dan bentuk hasil yang dinormalisasi.

Sprint 7 memakai kontrak ringkasan (`overview`, `topics`, `decisions`).
Sprint 8 menambah kontrak ekstraksi action items di file yang sama agar tetap
menggunakan satu lapisan provider LLM. Workflow tetap memvalidasi referensi
segmen dan speaker terhadap database sebelum menyimpan apa pun.
"""

import datetime
import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .errors import LlmInvalidResultError

# Nama format untuk Structured Outputs OpenAI. Harus alphanum/underscore.
SUMMARY_FORMAT_NAME = "meeting_summary"
ACTION_ITEMS_FORMAT_NAME = "action_items"


@dataclass(frozen=True)
class SummaryInputSegment:
    """Satu baris transkrip yang dikirim ke provider."""

    id: str
    text: str
    start_seconds: float
    end_seconds: float
    speaker_display_name: str | None = None


@dataclass(frozen=True)
class SummaryInput:
    """Permintaan ringkasan yang sudah disiapkan workflow."""

    meeting_title: str
    segments: list[SummaryInputSegment]
    output_language: str | None = None


@dataclass(frozen=True)
class SummaryTopic:
    """Topik pembahasan dengan referensi ke transkrip asli."""

    title: str
    detail: str
    segment_ids: tuple[str, ...]
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class SummaryDecision:
    """Keputusan eksplisit dengan referensi ke transkrip asli."""

    text: str
    segment_ids: tuple[str, ...]
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class SummaryResult:
    """Hasil ringkasan yang sudah dinormalisasi dari provider."""

    overview: str
    topics: list[SummaryTopic]
    decisions: list[SummaryDecision]
    provider: str
    model: str
    is_mock: bool = False


SYSTEM_PROMPT = """Kamu adalah asisten yang membuat ringkasan rapat HANYA dari transkrip yang diberikan.

Aturan mutlak:
1. Gunakan hanya fakta yang tertulis di transkrip. Jangan memakai pengetahuan umum, menebak, atau menambahkan informasi.
2. Jangan pernah menciptakan atau menebak identitas dunia nyata, jabatan, nama, assignee, atau tenggat waktu. Jika transkrip menampilkan label pembicara, pakai persis label itu bila perlu.
3. Jangan ekstrak action item, tugas, penanggung jawab, atau deadline. Itu bukan bagian dari ringkasan ini.
4. overview: 1–3 kalimat ringkas tentang isi rapat.
5. topics: topik yang benar-benar dibahas. Sertakan judul, detail singkat, dan referensi segmen yang mendukung.
6. decisions: HANYA keputusan akhir yang dinyatakan secara eksplisit dan disepakati/ditegaskan dalam transkrip. Usulan, rencana, diskusi, atau pernyataan satu pihak BUKAN keputusan. Jika tidak ada keputusan eksplisit, kembalikan array kosong [].
7. Setiap topic dan decision WAJIB memiliki segment_ids (minimal satu) serta start_seconds dan end_seconds. Salin ID segmen persis seperti pada input. Gunakan waktu mulai terkecil dan waktu akhir terbesar dari segmen yang dirujuk.
8. Jangan mengubah arti kalimat. Jika ragu, lebih baik ringkas lebih sedikit daripada mengarang.
9. Tulis dalam bahasa transkrip. Jika instruksi bahasa output diberikan secara eksplisit, ikuti instruksi itu.
10. Keluarkan HANYA objek JSON sesuai schema. Jangan memasukkan catatan, markdown, atau teks di luar JSON.
"""


# JSON Schema untuk Structured Outputs (strict=true): semua field required dan
# additionalProperties=false, sesuai persyaratan OpenAI.
SUMMARY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "segment_ids": {"type": "array", "items": {"type": "string"}},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                },
                "required": [
                    "title",
                    "detail",
                    "segment_ids",
                    "start_seconds",
                    "end_seconds",
                ],
                "additionalProperties": False,
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "segment_ids": {"type": "array", "items": {"type": "string"}},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                },
                "required": ["text", "segment_ids", "start_seconds", "end_seconds"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "topics", "decisions"],
    "additionalProperties": False,
}


def _format_clock(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{remainder:04.1f}"


def format_transcript(data: SummaryInput) -> str:
    """Render transkrip dengan ID dan waktu yang bisa disalin model."""
    lines = [f"Judul rapat: {data.meeting_title}", "Transkrip:"]
    for segment in data.segments:
        speaker = segment.speaker_display_name or "Pembicara tidak diketahui"
        lines.append(
            f'[{segment.id}] {_format_clock(segment.start_seconds)}-'
            f'{_format_clock(segment.end_seconds)} | {speaker} | {segment.text}'
        )
    if data.output_language:
        lines.append(f"Bahasa output yang diminta: {data.output_language}")
    else:
        lines.append("Bahasa output: ikuti bahasa transkrip.")
    return "\n".join(lines)


def _clean_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise LlmInvalidResultError(f"Field {field} harus berupa teks.")
    text = value.strip()
    if not text:
        raise LlmInvalidResultError(f"Field {field} tidak boleh kosong.")
    return text


def _clean_ids(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise LlmInvalidResultError(f"{field} harus berisi minimal satu ID segmen.")
    ids: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise LlmInvalidResultError(f"{field} berisi ID segmen tidak valid.")
        ids.append(item.strip())
    return tuple(ids)


def _clean_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LlmInvalidResultError(f"Field {field} harus berupa angka.")
    number = float(value)
    if number < 0 or number != number or number in (float("inf"), float("-inf")):
        raise LlmInvalidResultError(f"Field {field} bukan timestamp yang valid.")
    return number


def parse_summary_payload(
    payload: Any,
    *,
    provider: str,
    model: str,
    is_mock: bool = False,
) -> SummaryResult:
    """Validasi bentuk JSON provider sebelum dikembalikan ke workflow."""
    if not isinstance(payload, dict):
        raise LlmInvalidResultError("Respons provider bukan objek JSON.")

    overview = _clean_text(payload.get("overview"), "overview")
    raw_topics = payload.get("topics")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_topics, list) or not isinstance(raw_decisions, list):
        raise LlmInvalidResultError("topics dan decisions harus berupa array.")

    topics: list[SummaryTopic] = []
    for index, item in enumerate(raw_topics, start=1):
        if not isinstance(item, dict):
            raise LlmInvalidResultError(f"Topik #{index} bukan objek.")
        start = _clean_number(item.get("start_seconds"), f"topics[{index}].start_seconds")
        end = _clean_number(item.get("end_seconds"), f"topics[{index}].end_seconds")
        if end < start:
            raise LlmInvalidResultError(f"Topik #{index} memiliki waktu akhir sebelum mulai.")
        topics.append(
            SummaryTopic(
                title=_clean_text(item.get("title"), f"topics[{index}].title"),
                detail=_clean_text(item.get("detail"), f"topics[{index}].detail"),
                segment_ids=_clean_ids(item.get("segment_ids"), f"topics[{index}].segment_ids"),
                start_seconds=start,
                end_seconds=end,
            )
        )

    decisions: list[SummaryDecision] = []
    for index, item in enumerate(raw_decisions, start=1):
        if not isinstance(item, dict):
            raise LlmInvalidResultError(f"Keputusan #{index} bukan objek.")
        start = _clean_number(item.get("start_seconds"), f"decisions[{index}].start_seconds")
        end = _clean_number(item.get("end_seconds"), f"decisions[{index}].end_seconds")
        if end < start:
            raise LlmInvalidResultError(
                f"Keputusan #{index} memiliki waktu akhir sebelum mulai."
            )
        decisions.append(
            SummaryDecision(
                text=_clean_text(item.get("text"), f"decisions[{index}].text"),
                segment_ids=_clean_ids(
                    item.get("segment_ids"), f"decisions[{index}].segment_ids"
                ),
                start_seconds=start,
                end_seconds=end,
            )
        )

    return SummaryResult(
        overview=overview,
        topics=topics,
        decisions=decisions,
        provider=provider,
        model=model,
        is_mock=is_mock,
    )


# ---------------------------------------------------------------------------
# Sprint 8 — ekstraksi action items (kontrak kedua pada provider LLM yang sama)
# ---------------------------------------------------------------------------

# Baris transkrip identik dengan ringkasan; alias ini menjaga nama kontrak
# action items tetap jelas tanpa menduplikasi dataclass.
ActionItemInputSegment = SummaryInputSegment


@dataclass(frozen=True)
class ActionItemInput:
    """Permintaan ekstraksi; bentuknya sengaja sama dengan ``SummaryInput``."""

    meeting_title: str
    segments: list[SummaryInputSegment]
    output_language: str | None = None
    # Label speaker yang benar-benar ada di meeting ini. Model hanya boleh
    # memetakan assignee ke salah satu label di bawah (atau tidak sama sekali).
    available_speaker_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedActionItem:
    """Satu action item dari provider, sebelum validasi referensi workflow."""

    title: str
    description: str
    assignee_speaker_label: str | None
    assignee_text: str | None
    deadline_text: str | None
    due_date: datetime.date | None
    segment_ids: tuple[str, ...]
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class ActionItemExtractionResult:
    """Seluruh hasil ekstraksi action items dari satu panggilan provider."""

    items: list[ExtractedActionItem]
    provider: str
    model: str
    is_mock: bool = False


ACTION_ITEMS_SYSTEM_PROMPT = """Kamu adalah asisten yang mengekstrak ACTION ITEM (tugas/tindak lanjut) HANYA dari transkrip rapat yang diberikan.

Aturan mutlak:
1. Sertakan hanya tugas atau tindak lanjut yang benar-benar dinyatakan/diminta dalam transkrip. Ide, saran, rencana, atau pekerjaan yang hanya dibicarakan BUKAN action item. Jika ragu, jangan sertakan. Jika tidak ada action item yang didukung transkrip, kembalikan array kosong [].
2. Jangan mengarang penanggung jawab. assignee_speaker_label HANYA boleh diisi dengan salah satu label speaker yang tercantam dalam daftar "Speaker tersedia", persis seperti tulisannya. Jangan memilih pembicara hanya karena dia mengucapkan kalimat tersebut — harus ada pernyataan eksplisit bahwa orang itu menerima tugas.
3. Jika transkrip menyebut nama/keterangan penanggung jawab tetapi tidak dapat dipetakan ke speaker tersedia, isi assignee_text dengan frasa aslinya dan biarkan assignee_speaker_label null. Jika tidak ada penanggung jawab yang jelas, keduanya null.
4. Jangan mengarang deadline. deadline_text harus merupakan frasa deadline yang persis disebutkan dalam transkrip (mis. "hari Jumat"), bukan terjemahan bebas. due_date HANYA diisi "YYYY-MM-DD" jika tanggal dapat ditentukan secara tidak ambigu dari transkrip. Frasa relatif yang ambigu tetap disimpan di deadline_text dengan due_date null. JANGAN mengasumsikan tanggal rapat dari waktu server atau pengetahuan di luar transkrip.
5. title = deskripsi singkat tugas. description = konteks/rincian yang mendukung dari transkrip. Jangan menambahkan detail yang tidak ada.
6. Setiap action item WAJIB memiliki segment_ids (minimal satu) serta start_seconds dan end_seconds. Salin ID segmen persis seperti pada input. Gunakan waktu mulai terkecil dan waktu akhir terbesar dari segmen yang dirujuk.
7. Gunakan bahasa transkrip, kecuali instruksi bahasa output diberikan secara eksplisit.
8. Keluarkan HANYA objek JSON sesuai schema. Jangan memasukkan catatan, markdown, atau teks di luar JSON.
"""


# JSON Schema strict untuk Structured Outputs. Setiap property wajib masuk
# `required`; field opsional memakai tipe ["string", "null"] / ["string", ...].
ACTION_ITEMS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "assignee_speaker_label": {"type": ["string", "null"]},
                    "assignee_text": {"type": ["string", "null"]},
                    "deadline_text": {"type": ["string", "null"]},
                    "due_date": {"type": ["string", "null"]},
                    "segment_ids": {"type": "array", "items": {"type": "string"}},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                },
                "required": [
                    "title",
                    "description",
                    "assignee_speaker_label",
                    "assignee_text",
                    "deadline_text",
                    "due_date",
                    "segment_ids",
                    "start_seconds",
                    "end_seconds",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["action_items"],
    "additionalProperties": False,
}


def format_action_items_input(data: ActionItemInput) -> str:
    """Render transkrip + daftar speaker yang boleh dipetakan model."""
    base = format_transcript(
        SummaryInput(
            meeting_title=data.meeting_title,
            segments=data.segments,
            output_language=data.output_language,
        )
    )
    if data.available_speaker_labels:
        labels = ", ".join(data.available_speaker_labels)
    else:
        labels = "(tidak ada speaker terdetektif — jangan isi assignee_speaker_label)"
    return f"{base}\nSpeaker tersedia: {labels}"


def _clean_optional_text(value: Any, field: str) -> str | None:
    """Teks opsional; string kosong dinormalisasi menjadi None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise LlmInvalidResultError(f"Field {field} harus berupa teks atau null.")
    cleaned = value.strip()
    return cleaned or None


def _clean_description(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise LlmInvalidResultError(f"Field {field} harus berupa teks.")
    return value.strip()


def _parse_due_date(value: Any, field: str) -> datetime.date | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        raise LlmInvalidResultError(
            f"Field {field} harus berupa tanggal YYYY-MM-DD atau null."
        )
    try:
        return datetime.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise LlmInvalidResultError(f"Field {field} bukan tanggal yang valid.") from exc


def _reject_unknown_keys(value: dict, allowed: set[str], label: str) -> None:
    """Perlakukan field di luar schema strict sebagai output invalid."""
    unknown = set(value) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise LlmInvalidResultError(f"{label} memiliki field tidak dikenal: {names}.")


_ACTION_ITEM_FIELDS = {
    "title",
    "description",
    "assignee_speaker_label",
    "assignee_text",
    "deadline_text",
    "due_date",
    "segment_ids",
    "start_seconds",
    "end_seconds",
}


def parse_action_items_payload(
    payload: Any,
    *,
    provider: str,
    model: str,
    is_mock: bool = False,
) -> ActionItemExtractionResult:
    """Validasi bentuk JSON action items sebelum dikembalikan ke workflow."""
    if not isinstance(payload, dict):
        raise LlmInvalidResultError("Respons provider bukan objek JSON.")
    _reject_unknown_keys(payload, {"action_items"}, "Respons")

    raw_items = payload.get("action_items")
    if not isinstance(raw_items, list):
        raise LlmInvalidResultError("action_items harus berupa array.")

    items: list[ExtractedActionItem] = []
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise LlmInvalidResultError(f"Action item #{index} bukan objek.")
        _reject_unknown_keys(raw, _ACTION_ITEM_FIELDS, f"Action item #{index}")
        start = _clean_number(raw.get("start_seconds"), f"action_items[{index}].start_seconds")
        end = _clean_number(raw.get("end_seconds"), f"action_items[{index}].end_seconds")
        if end < start:
            raise LlmInvalidResultError(
                f"Action item #{index} memiliki waktu akhir sebelum mulai."
            )
        items.append(
            ExtractedActionItem(
                title=_clean_text(raw.get("title"), f"action_items[{index}].title"),
                description=_clean_description(
                    raw.get("description"), f"action_items[{index}].description"
                ),
                assignee_speaker_label=_clean_optional_text(
                    raw.get("assignee_speaker_label"),
                    f"action_items[{index}].assignee_speaker_label",
                ),
                assignee_text=_clean_optional_text(
                    raw.get("assignee_text"), f"action_items[{index}].assignee_text"
                ),
                deadline_text=_clean_optional_text(
                    raw.get("deadline_text"), f"action_items[{index}].deadline_text"
                ),
                due_date=_parse_due_date(
                    raw.get("due_date"), f"action_items[{index}].due_date"
                ),
                segment_ids=_clean_ids(
                    raw.get("segment_ids"), f"action_items[{index}].segment_ids"
                ),
                start_seconds=start,
                end_seconds=end,
            )
        )

    return ActionItemExtractionResult(
        items=items,
        provider=provider,
        model=model,
        is_mock=is_mock,
    )


@runtime_checkable
class LlmProvider(Protocol):
    """Antarmuka minimal provider AI (ringkasan + action items)."""

    name: str

    @property
    def model(self) -> str: ...

    def validate_configuration(self) -> None:
        """Lempar LlmConfigurationError bila konfigurasi belum lengkap."""

    def summarize(self, data: SummaryInput) -> SummaryResult:
        """Ringkas transkrip. Lempar subclass LlmError bila gagal."""

    def extract_action_items(self, data: ActionItemInput) -> ActionItemExtractionResult:
        """Ekstrak action items. Lempar subclass LlmError bila gagal."""

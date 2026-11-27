// Lapisan akses API.
// Base URL dibaca dari environment variable Vite (`VITE_API_BASE_URL`).
// Jangan pernah menaruh API key di sini.

import type {
  ActionItem,
  ActionItemListDetail,
  ActionItemUpdate,
  AppConfig,
  AudioAsset,
  DiarizationDetail,
  Meeting,
  SpeakerSummary,
  SummaryDetail,
  TranscriptionDetail,
  TranscriptSegment,
} from './types'
import { readDetailMessage, resolvePlaybackUrl } from './utils/apiSafety'
import { resolveExportFilename, type ExportFormat } from './utils/export'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface ApiError extends Error {
  status?: number
}

/** Ambil pesan error dari response FastAPI (field `detail`) secara fail-closed. */
async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    return readDetailMessage(body.detail, fallback)
  } catch {
    // Response bukan JSON — pakai pesan fallback.
  }
  return fallback
}

function makeApiError(message: string, status: number): ApiError {
  const error: ApiError = new Error(message)
  error.status = status
  return error
}

/** PATCH JSON dipakai bersama oleh editor transkrip & speaker (Sprint 6). */
async function patchJson<T>(path: string, body: unknown, fallback: string): Promise<T> {
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw makeApiError('Tidak dapat terhubung ke backend saat menyimpan perubahan.', 0)
  }

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `${fallback} (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as T
}

/** Ambil daftar meeting dari backend. */
export async function fetchMeetings(): Promise<Meeting[]> {
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}/api/v1/meetings`, {
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw makeApiError(
      'Tidak dapat terhubung ke backend. Pastikan server backend sudah berjalan.',
      0,
    )
  }

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memuat daftar meeting (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as Meeting[]
}

/** Cek kesehatan backend (dipakai untuk indikator koneksi). */
export async function fetchHealth(): Promise<{ status: string; application: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError('Backend tidak sehat.', response.status)
  }

  return response.json()
}

/** Buat meeting baru. Status awal dari backend: PENDING. */
export async function createMeeting(title: string): Promise<Meeting> {
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}/api/v1/meetings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ title }),
    })
  } catch {
    throw makeApiError('Tidak dapat terhubung ke backend saat membuat meeting.', 0)
  }

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal membuat meeting (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as Meeting
}

/** Simpan Blob hasil MediaRecorder ke meeting tertentu. */
export async function uploadRecording(
  meetingId: string,
  blob: Blob,
  filename: string,
  durationSeconds: number,
): Promise<AudioAsset> {
  const form = new FormData()
  form.append('file', blob, filename)
  form.append('duration_seconds', durationSeconds.toFixed(3))

  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/recording`, {
      method: 'POST',
      body: form,
    })
  } catch {
    throw makeApiError('Tidak dapat terhubung ke backend saat menyimpan rekaman.', 0)
  }

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal menyimpan rekaman (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as AudioAsset
}

/** Konfigurasi publik dari backend (batas ukuran & format audio). */
export async function fetchAppConfig(): Promise<AppConfig> {
  const response = await fetch(`${API_BASE_URL}/api/v1/config`, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError('Gagal memuat konfigurasi audio dari backend.', response.status)
  }

  return (await response.json()) as AppConfig
}

/**
 * Upload file audio lokal.
 * Memakai endpoint yang sama dengan rekaman MediaRecorder — bukan endpoint duplikat.
 */
export async function uploadAudioFile(
  meetingId: string,
  file: File,
  durationSeconds: number,
): Promise<AudioAsset> {
  return uploadRecording(meetingId, file, file.name, durationSeconds)
}

/** Hapus rekaman yang tersimpan. Meeting kembali ke status PENDING. */
export async function deleteRecording(meetingId: string): Promise<{ detail: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/recording`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal menghapus rekaman (HTTP ${response.status}).`),
      response.status,
    )
  }

  return response.json()
}

/** URL absolut untuk memutar rekaman lewat endpoint playback backend. */
export function playbackUrl(asset: AudioAsset): string {
  return resolvePlaybackUrl(asset.playback_url, API_BASE_URL)
}

/**
 * Ambil satu meeting terbaru dari daftar.
 * Backend Sprint 1 hanya menyediakan GET /meetings, jadi ini sengaja memakai
 * endpoint tersebut agar tidak menambah endpoint baru di luar Sprint 4.
 */
export async function refreshMeeting(meetingId: string): Promise<Meeting> {
  const meetings = await fetchMeetings()
  const meeting = meetings.find((item) => item.id === meetingId)
  if (!meeting) throw makeApiError('Meeting tidak ditemukan saat menyegarkan status.', 404)
  return meeting
}

/** Sprint 4: mulai transkripsi rekaman (202 = diproses di background). */
export async function startTranscription(meetingId: string): Promise<TranscriptionDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/transcription`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memulai transkripsi (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as TranscriptionDetail
}

/** Sprint 4: status + segmen transkrip. Aman dipanggil berulang saat polling. */
export async function fetchTranscription(meetingId: string): Promise<TranscriptionDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/transcription`, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memuat transkrip (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as TranscriptionDetail
}

/** Sprint 4: hapus transkrip saja; audio dan AudioAsset tidak dihapus. */
export async function deleteTranscript(
  meetingId: string,
): Promise<{ detail: string; meeting_id: string; segments_deleted: number }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/transcription`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal menghapus transkrip (HTTP ${response.status}).`),
      response.status,
    )
  }

  return response.json()
}

/** Sprint 5: mulai diarisasi dari rekaman + transkrip yang sudah ada. */
export async function startDiarization(meetingId: string): Promise<DiarizationDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/diarization`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memulai diarisasi (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as DiarizationDetail
}

/** Sprint 5: status + speaker diarisasi. Aman dipanggil berulang saat polling. */
export async function fetchDiarization(meetingId: string): Promise<DiarizationDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/diarization`, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memuat status diarisasi (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as DiarizationDetail
}

/** Sprint 5: hapus speaker + job saja; transkrip dan audio tetap ada. */
export async function deleteDiarization(
  meetingId: string,
): Promise<{ detail: string; meeting_id: string; speakers_deleted: number; segments_unassigned: number }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/diarization`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal menghapus diarisasi (HTTP ${response.status}).`),
      response.status,
    )
  }

  return response.json()
}

/**
 * Sprint 7: mulai/generate/regenerate ringkasan (202 = diproses di background).
 * Saat ringkasan sudah ada, backend menggantinya hanya setelah hasil baru valid.
 */
export async function startSummary(meetingId: string): Promise<SummaryDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/summary`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memulai ringkasan (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as SummaryDetail
}

/** Sprint 7: status + ringkasan terakhir. Aman dipanggil berulang saat polling. */
export async function fetchSummary(meetingId: string): Promise<SummaryDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/summary`, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memuat ringkasan (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as SummaryDetail
}

/** Sprint 7: hapus ringkasan + job; transkrip dan audio tidak dihapus. */
export async function deleteSummary(
  meetingId: string,
): Promise<{ detail: string; meeting_id: string; summaries_deleted: number; jobs_deleted: number }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/summary`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal menghapus ringkasan (HTTP ${response.status}).`),
      response.status,
    )
  }

  return response.json()
}

/**
 * Sprint 8: mulai/generate/regenerate action items (202 = background).
 * Item hasil edit pengguna tidak dihapus oleh backend saat regenerasi.
 */
export async function startActionItems(meetingId: string): Promise<ActionItemListDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/action-items`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memulai ekstraksi action items (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as ActionItemListDetail
}

/** Sprint 8: status + action items terakhir. Aman dipanggil saat polling. */
export async function fetchActionItems(meetingId: string): Promise<ActionItemListDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/action-items`, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal memuat action items (HTTP ${response.status}).`),
      response.status,
    )
  }

  return (await response.json()) as ActionItemListDetail
}

/** Sprint 8: hapus seluruh action items + job; transkrip dan audio tetap ada. */
export async function deleteActionItems(
  meetingId: string,
): Promise<{ detail: string; meeting_id: string; items_deleted: number; sources_deleted: number; jobs_deleted: number }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/action-items`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal menghapus action items (HTTP ${response.status}).`),
      response.status,
    )
  }

  return response.json()
}

/** Sprint 8: edit satu action item. */
export function updateActionItem(
  meetingId: string,
  itemId: string,
  body: ActionItemUpdate,
): Promise<ActionItem> {
  return patchJson<ActionItem>(
    `/api/v1/meetings/${meetingId}/action-items/${itemId}`,
    body,
    'Gagal menyimpan action item',
  )
}

/** Sprint 8: hapus satu action item. */
export async function deleteActionItem(
  meetingId: string,
  itemId: string,
): Promise<{ detail: string; meeting_id: string; item_id: string; sources_deleted: number }> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/meetings/${meetingId}/action-items/${itemId}`,
    { method: 'DELETE', headers: { Accept: 'application/json' } },
  )

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal menghapus action item (HTTP ${response.status}).`),
      response.status,
    )
  }

  return response.json()
}

/** Sprint 6: simpan teks segmen yang sudah disunting pengguna. */
export function updateTranscriptSegmentText(
  meetingId: string,
  segmentId: string,
  text: string,
): Promise<TranscriptSegment> {
  return patchJson<TranscriptSegment>(
    `/api/v1/meetings/${meetingId}/transcript/${segmentId}`,
    { text },
    'Gagal menyimpan teks segmen',
  )
}

/** Sprint 6: ubah nama tampilan speaker, atau kirim null untuk memakai label. */
export function updateSpeakerDisplayName(
  meetingId: string,
  speakerId: string,
  displayName: string | null,
): Promise<SpeakerSummary> {
  return patchJson<SpeakerSummary>(
    `/api/v1/meetings/${meetingId}/speakers/${speakerId}`,
    { display_name: displayName },
    'Gagal menyimpan nama speaker',
  )
}

/** Sprint 6: petakan segmen ke speaker satu meeting, atau null untuk melepas. */
export function updateSegmentSpeaker(
  meetingId: string,
  segmentId: string,
  speakerId: string | null,
): Promise<TranscriptSegment> {
  return patchJson<TranscriptSegment>(
    `/api/v1/meetings/${meetingId}/transcript/${segmentId}/speaker`,
    { speaker_id: speakerId },
    'Gagal mengubah speaker segmen',
  )
}

/**
 * Sprint 10: unduh notulen sebagai TXT/PDF dari data yang sudah tersimpan.
 * Mengembalikan Blob + nama file; pemanggilan URL.createObjectURL/anchor
 * dilakukan komponen agar lapisan API tetap bebas efek samping DOM.
 */
export async function downloadExport(
  meetingId: string,
  format: ExportFormat,
): Promise<{ blob: Blob; filename: string }> {
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}/api/v1/meetings/${meetingId}/export/${format}`, {
      headers: { Accept: format === 'pdf' ? 'application/pdf' : 'text/plain' },
    })
  } catch {
    throw makeApiError('Tidak dapat terhubung ke backend saat mengunduh notulen.', 0)
  }

  if (!response.ok) {
    throw makeApiError(
      await readErrorMessage(response, `Gagal mengunduh notulen ${format.toUpperCase()} (HTTP ${response.status}).`),
      response.status,
    )
  }

  return {
    blob: await response.blob(),
    filename: resolveExportFilename(
      response.headers.get('Content-Disposition'),
      meetingId,
      format,
    ),
  }
}
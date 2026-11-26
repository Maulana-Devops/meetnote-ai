// Definisi tipe data yang dikirim backend.
// Selaras dengan skema Pydantic `MeetingRead`, `AudioAssetRead`,
// `AppConfigRead`, `TranscriptionRead`, dan `DiarizationRead` (Sprint 5).

export interface AudioAsset {
  id: string
  meeting_id: string
  original_filename: string
  storage_filename: string
  mime_type: string
  file_size_bytes: number
  duration_seconds: number
  created_at: string
  // Path relatif dari backend, mis. /api/v1/meetings/{id}/recording/play
  playback_url: string
}

export interface Meeting {
  id: string
  title: string
  status: string
  created_at: string
  updated_at: string
  has_recording: boolean
  recording: AudioAsset | null
}

export interface AppConfig {
  max_audio_file_bytes: number
  allowed_mime_types: string[]
  allowed_extensions: string[]
  // Sprint 4: informasi provider STT yang aman dipublikasikan backend.
  stt_provider: string
  stt_configured: boolean
  // Fase 1: bahasa STT/ringkasan yang aman dipublikasikan backend.
  stt_language: string
  summary_language: string
  // Sprint 5: informasi provider diarisasi (tanpa API key).
  diarization_provider: string
  diarization_configured: boolean
  // Sprint 7: informasi provider LLM (tanpa API key).
  llm_provider: string
  llm_configured: boolean
}

export interface TranscriptSegment {
  id: string
  meeting_id: string
  text: string
  start_seconds: number
  end_seconds: number
  sequence: number
  created_at: string
  // Sprint 5: null berarti tidak ada mapping speaker yang andal.
  speaker_id: string | null
  speaker_label: string | null
  // Sprint 6: nama buatan pengguna. UI memakai ini bila ada, jika tidak
  // speaker_label. Null bukan berarti speaker tidak dikenali.
  speaker_display_name: string | null
}

/** Status job transkripsi di backend (bukan status Meeting). */
export type TranscriptionStatus = 'NOT_STARTED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

export interface TranscriptionDetail {
  meeting_id: string
  status: TranscriptionStatus
  meeting_status: string
  provider: string | null
  model: string | null
  has_timestamps: boolean
  error: string | null
  full_text: string
  segments: TranscriptSegment[]
  updated_at: string | null
}

export interface SpeakerSummary {
  id: string
  meeting_id: string
  speaker_label: string
  display_name: string | null
  created_at: string
  segment_count: number
}

/** Status job diarisasi di backend (bukan status Meeting/transkripsi). */
export type DiarizationStatus = 'NOT_STARTED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

export interface DiarizationDetail {
  meeting_id: string
  status: DiarizationStatus
  meeting_status: string
  provider: string | null
  model: string | null
  is_mock: boolean
  error: string | null
  turns_count: number
  mapped_segments: number
  speakers: SpeakerSummary[]
  updated_at: string | null
}

/** Sprint 7: status job ringkasan (bukan status Meeting). */
export type SummaryStatus = 'NOT_STARTED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

/** Referensi transkrip yang wajib ada pada setiap topik/keputusan. */
export interface SummarySourceRef {
  segment_ids: string[]
  start_seconds: number
  end_seconds: number
}

export interface SummaryTopic extends SummarySourceRef {
  title: string
  detail: string
}

export interface SummaryDecision extends SummarySourceRef {
  text: string
}

export interface SummaryDetail {
  meeting_id: string
  status: SummaryStatus
  meeting_status: string
  provider: string | null
  model: string | null
  is_mock: boolean
  error: string | null
  overview: string
  topics: SummaryTopic[]
  decisions: SummaryDecision[]
  created_at: string | null
  updated_at: string | null
}

/** Sprint 8: status item dan status job ekstraksi action items. */
export type ActionItemStatus = 'OPEN' | 'COMPLETED' | 'CANCELLED'
export type ActionItemJobStatus = 'NOT_STARTED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

/** Referensi transkrip wajib (bentuk sama dengan referensi summary). */
export interface ActionItemSourceRef {
  segment_ids: string[]
  start_seconds: number
  end_seconds: number
}

export interface ActionItemSpeakerOption {
  id: string
  label: string
}

export interface ActionItem extends ActionItemSourceRef {
  id: string
  meeting_id: string
  title: string
  description: string
  assignee_speaker_id: string | null
  assignee_text: string | null
  deadline_text: string | null
  due_date: string | null
  status: ActionItemStatus
  is_manually_edited: boolean
  provider: string | null
  model: string | null
  is_mock: boolean
  created_at: string | null
  updated_at: string | null
}

export interface ActionItemListDetail {
  meeting_id: string
  status: ActionItemJobStatus
  meeting_status: string
  provider: string | null
  model: string | null
  is_mock: boolean
  error: string | null
  items: ActionItem[]
  speakers: ActionItemSpeakerOption[]
  created_at: string | null
  updated_at: string | null
}

/** PATCH: hanya field yang dikirim yang diubah; null menghapus nilai. */
export interface ActionItemUpdate {
  title?: string
  description?: string
  assignee_speaker_id?: string | null
  assignee_text?: string | null
  deadline_text?: string | null
  due_date?: string | null
  status?: ActionItemStatus
}

// Satu baris segmen transkrip: lihat/sunting teks, pilih speaker, dan
// klik timestamp untuk melompat ke audio. Dipisah dari TranscriptEditor agar
// state edit per segmen tidak menumpuk di satu komponen besar.

import { useState } from 'react'

import { updateSegmentSpeaker, updateTranscriptSegmentText } from '../api'
import type { SpeakerSummary, TranscriptSegment } from '../types'
import { formatTimestamp } from '../utils/format'

// Sama dengan batas di backend (`services/transcript_editing.py`).
const MAX_SEGMENT_TEXT_CHARS = 10_000

interface TranscriptSegmentItemProps {
  segment: TranscriptSegment
  speakers: SpeakerSummary[]
  hasTimestamps: boolean
  disabled: boolean
  onSeek: (seconds: number) => void
  onTextSaved: (updated: TranscriptSegment) => void
  onSpeakerSaved: (updated: TranscriptSegment) => void
}

export function TranscriptSegmentItem({
  segment,
  speakers,
  hasTimestamps,
  disabled,
  onSeek,
  onTextSaved,
  onSpeakerSaved,
}: TranscriptSegmentItemProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(segment.text)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Nama buatan pengguna lebih diprioritasikan; label anonim jadi cadangan.
  const speakerName = segment.speaker_display_name ?? segment.speaker_label ?? 'Speaker ?'
  const timeLabel = hasTimestamps
    ? `${formatTimestamp(segment.start_seconds)} – ${formatTimestamp(segment.end_seconds)}`
    : 'Tanpa timestamp asli'

  function startEditing() {
    setDraft(segment.text)
    setError('')
    setEditing(true)
  }

  function cancelEditing() {
    setDraft(segment.text)
    setError('')
    setEditing(false)
  }

  async function saveText() {
    if (saving) return

    const trimmed = draft.trim()
    if (!trimmed) {
      setError('Teks segmen tidak boleh kosong.')
      return
    }
    if (trimmed.length > MAX_SEGMENT_TEXT_CHARS) {
      setError(`Teks terlalu panjang (maksimal ${MAX_SEGMENT_TEXT_CHARS} karakter).`)
      return
    }

    setSaving(true)
    setError('')
    try {
      const updated = await updateTranscriptSegmentText(segment.meeting_id, segment.id, draft)
      onTextSaved(updated)
      setDraft(updated.text)
      setEditing(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Gagal menyimpan teks segmen.')
    } finally {
      setSaving(false)
    }
  }

  async function changeSpeaker(nextId: string) {
    if (saving) return

    const speakerId = nextId === '' ? null : nextId
    if (speakerId === segment.speaker_id) return

    setSaving(true)
    setError('')
    try {
      const updated = await updateSegmentSpeaker(segment.meeting_id, segment.id, speakerId)
      onSpeakerSaved(updated)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Gagal mengubah speaker segmen.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <li className="transcript-segment">
      {hasTimestamps ? (
        <button
          className="transcript-segment__time transcript-segment__time--button"
          type="button"
          onClick={() => onSeek(segment.start_seconds)}
          disabled={disabled}
          title="Putar rekaman dari waktu mulai segmen ini"
        >
          {timeLabel}
        </button>
      ) : (
        <span className="transcript-segment__time">{timeLabel}</span>
      )}

      <div className="transcript-segment__body">
        <div className="transcript-segment__controls">
          <span
            className={
              segment.speaker_id
                ? 'transcript-segment__speaker'
                : 'transcript-segment__speaker transcript-segment__speaker--empty'
            }
          >
            {speakerName}
          </span>

          <select
            className="transcript-segment__select"
            value={segment.speaker_id ?? ''}
            onChange={(event) => void changeSpeaker(event.target.value)}
            disabled={disabled || saving}
            aria-label={`Speaker untuk segmen ${segment.sequence}`}
            title="Tentukan speaker untuk segmen ini"
          >
            <option value="">Unassigned</option>
            {speakers.map((speaker) => (
              <option key={speaker.id} value={speaker.id}>
                {speaker.display_name ?? speaker.speaker_label}
              </option>
            ))}
          </select>

          {editing ? (
            <span className="transcript-segment__actions">
              <button
                className="button button--ghost button--small"
                type="button"
                onClick={() => void saveText()}
                disabled={saving || !draft.trim()}
              >
                {saving ? 'Menyimpan…' : 'Save'}
              </button>
              <button
                className="button button--ghost button--small"
                type="button"
                onClick={cancelEditing}
                disabled={saving}
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              className="button button--ghost button--small"
              type="button"
              onClick={startEditing}
              disabled={disabled || saving}
            >
              Edit
            </button>
          )}
        </div>

        {editing ? (
          <textarea
            className="transcript-segment__input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={3}
            disabled={saving}
            aria-label={`Teks segmen ${segment.sequence}`}
          />
        ) : (
          <p>{segment.text}</p>
        )}

        {error && <p className="inline-error" role="alert">{error}</p>}
      </div>
    </li>
  )
}

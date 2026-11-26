// Kelola nama tampilan speaker. Nama selalu berasal dari pengguna — aplikasi
// tidak pernah menebak identitas dari rekaman. Label anonim tidak bisa diubah.

import { useState } from 'react'

import { updateSpeakerDisplayName } from '../api'
import type { SpeakerSummary } from '../types'

// Sama dengan batas di backend (`services/transcript_editing.py`).
const MAX_SPEAKER_DISPLAY_NAME_CHARS = 255

interface SpeakerManagerProps {
  speakers: SpeakerSummary[]
  disabled: boolean
  onSpeakerUpdated: (updated: SpeakerSummary) => void
}

export function SpeakerManager({ speakers, disabled, onSpeakerUpdated }: SpeakerManagerProps) {
  if (speakers.length === 0) {
    return <p className="muted">Belum ada speaker yang dikenali.</p>
  }

  return (
    <ul className="speaker-list speaker-manager">
      {speakers.map((speaker) => (
        <SpeakerRow
          key={speaker.id}
          speaker={speaker}
          disabled={disabled}
          onUpdated={onSpeakerUpdated}
        />
      ))}
    </ul>
  )
}

interface SpeakerRowProps {
  speaker: SpeakerSummary
  disabled: boolean
  onUpdated: (updated: SpeakerSummary) => void
}

function SpeakerRow({ speaker, disabled, onUpdated }: SpeakerRowProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(speaker.display_name ?? '')
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState('')

  function startEditing() {
    setDraft(speaker.display_name ?? '')
    setFeedback('')
    setError('')
    setEditing(true)
  }

  function cancelEditing() {
    setDraft(speaker.display_name ?? '')
    setFeedback('')
    setError('')
    setEditing(false)
  }

  async function save() {
    if (saving) return

    const trimmed = draft.trim()
    if (!trimmed) {
      setError('Nama tidak boleh kosong. Gunakan "Pakai label" untuk menghapusnya.')
      return
    }
    if (trimmed.length > MAX_SPEAKER_DISPLAY_NAME_CHARS) {
      setError(`Nama terlalu panjang (maksimal ${MAX_SPEAKER_DISPLAY_NAME_CHARS} karakter).`)
      return
    }

    setSaving(true)
    setError('')
    try {
      const updated = await updateSpeakerDisplayName(
        speaker.meeting_id,
        speaker.id,
        trimmed,
      )
      onUpdated(updated)
      setDraft(updated.display_name ?? '')
      setEditing(false)
      setFeedback('Nama speaker disimpan.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Gagal menyimpan nama speaker.')
    } finally {
      setSaving(false)
    }
  }

  async function restoreLabel() {
    if (saving) return

    setSaving(true)
    setError('')
    try {
      const updated = await updateSpeakerDisplayName(speaker.meeting_id, speaker.id, null)
      onUpdated(updated)
      setDraft('')
      setEditing(false)
      setFeedback('Nama dihapus. Label anonim yang dipakai.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Gagal menghapus nama speaker.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <li>
      <div className="speaker-manager__row">
        <div>
          <strong>{speaker.display_name ?? speaker.speaker_label}</strong>
          {speaker.display_name && (
            <span className="speaker-manager__label"> ({speaker.speaker_label})</span>
          )}
          <span className="speaker-manager__count"> — {speaker.segment_count} segmen</span>
        </div>
        {!editing && (
          <button
            className="button button--ghost button--small"
            type="button"
            onClick={startEditing}
            disabled={disabled || saving}
          >
            Edit Nama
          </button>
        )}
      </div>

      {editing && (
        <div className="speaker-manager__edit">
          <input
            className="speaker-manager__input"
            type="text"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            disabled={saving}
            aria-label={`Nama tampilan ${speaker.speaker_label}`}
            placeholder={speaker.speaker_label}
          />
          <button
            className="button button--primary button--small"
            type="button"
            onClick={() => void save()}
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
          <button
            className="button button--ghost button--small"
            type="button"
            onClick={() => void restoreLabel()}
            disabled={saving}
            title="Kembalikan ke label anonim"
          >
            Pakai label
          </button>
        </div>
      )}

      {feedback && (
        <p className="speaker-manager__feedback" role="status">{feedback}</p>
      )}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </li>
  )
}

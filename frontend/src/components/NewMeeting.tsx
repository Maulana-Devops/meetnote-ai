// Halaman New Meeting: buat meeting, lalu pilih salah satu sumber audio:
// 1. rekam langsung dari mikrofon (MediaRecorder), atau
// 2. unggah file audio lokal (Sprint 3).

import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { createMeeting, uploadRecording } from '../api'
import { useLiveCaption } from '../hooks/useLiveCaption'
import { useMediaRecorder } from '../hooks/useMediaRecorder'
import type { AudioAsset, Meeting } from '../types'
import { formatBytes, formatDuration } from '../utils/format'
import { AudioUploader } from './AudioUploader'
import { StatusBadge } from './StatusBadge'

interface NewMeetingProps {
  onBack: () => void
  onCreated: (meeting: Meeting) => void
  onSaved: (meeting: Meeting, asset: AudioAsset) => void
  // Jika diisi, halaman dipakai untuk menambah rekaman ke meeting yang sudah ada.
  existingMeeting?: Meeting | null
}

export function NewMeeting({ onBack, onCreated, onSaved, existingMeeting }: NewMeetingProps) {
  const [title, setTitle] = useState('')
  const [meeting, setMeeting] = useState<Meeting | null>(existingMeeting ?? null)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [hasSelectedFile, setHasSelectedFile] = useState(false)

  const recorder = useMediaRecorder()
  const caption = useLiveCaption()
  const isBusy = recorder.status === 'recording' || recorder.status === 'paused'
  // Model hanya mendukung satu AudioAsset per meeting.
  const uploadDisabled = isBusy || !!recorder.result || saving
  const recorderDisabled = hasSelectedFile || saving

  // Caption memakai mikrofon yang sama dengan recorder:hentikan bila rekaman
  // dijeda/dihentikan agar tidak ada sumber audio aktif yang tersisa.
  useEffect(() => {
    if (recorder.status !== 'recording' && caption.listening) caption.stop()
  }, [recorder.status, caption.listening, caption.stop])

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const cleanTitle = title.trim()

    if (!cleanTitle || creating) return

    setCreating(true)
    setCreateError('')

    try {
      const created = await createMeeting(cleanTitle)
      setMeeting(created)
      onCreated(created)
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : 'Gagal membuat meeting.')
    } finally {
      setCreating(false)
    }
  }

  async function handleSave() {
    if (!meeting || !recorder.result || saving) return

    setSaving(true)
    setSaveError('')

    try {
      const asset = await uploadRecording(
        meeting.id,
        recorder.result.blob,
        recorder.result.filename,
        recorder.result.durationSeconds,
      )
      onSaved(
        { ...meeting, status: 'UPLOADED', has_recording: true, recording: asset },
        asset,
      )
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Gagal menyimpan rekaman.')
    } finally {
      setSaving(false)
    }
  }

  function handleDeletePreview() {
    if (!window.confirm('Hapus rekaman sementara ini? Rekaman belum disimpan ke server.')) return
    recorder.reset()
    setSaveError('')
  }

  return (
    <section className="new-meeting">
      <button className="button button--ghost" type="button" onClick={onBack}>
        ← Kembali ke Dashboard
      </button>

      {!meeting ? (
        <div className="panel">
          <h2>Buat Meeting Baru</h2>
          <p className="muted">Berikan judul rapat, lalu rekam percakapan langsung dari browser.</p>

          <form onSubmit={handleCreate} className="meeting-form">
            <label htmlFor="meeting-title">Judul meeting</label>
            <input
              id="meeting-title"
              type="text"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Contoh: Rapat Mingguan Tim"
              maxLength={255}
              autoFocus
            />
            <button className="button button--primary" type="submit" disabled={!title.trim() || creating}>
              {creating ? 'Membuat…' : 'Buat Meeting'}
            </button>
          </form>

          {createError && <p className="inline-error" role="alert">{createError}</p>}
        </div>
      ) : (
        <div className="panel">
          <div className="panel__header">
            <div>
              <h2>{meeting.title}</h2>
              <p className="muted">Status: <StatusBadge status={meeting.status} /></p>
            </div>
            <span className="meeting-id">ID: {meeting.id.slice(0, 8)}…</span>
          </div>

          <p className="method-hint">
            Pilih <strong>salah satu</strong>: rekam langsung atau unggah file audio.
            Satu meeting hanya menyimpan satu rekaman.
          </p>

          <div className="recorder">
            <h3>Rekam Percakapan</h3>
            <p className="muted">
              Izinkan akses mikrofon saat browser meminta. Rekaman hanya disimpan di server
              setelah Anda menekan <strong>Save Recording</strong>.
            </p>

            <div className={`recording-indicator ${isBusy ? 'recording-indicator--active' : ''}`}>
              <span className="recording-indicator__dot" aria-hidden="true" />
              <strong>{recorder.status}</strong>
              <span className="recording-indicator__time">
                {formatDuration(recorder.elapsedMs / 1000)}
              </span>
            </div>

            <div className="button-row">
              <button
                className="button button--primary"
                type="button"
                onClick={() => void recorder.start()}
                disabled={recorderDisabled || isBusy || !!recorder.result}
              >
                ● Start Recording
              </button>

              {recorder.supportsPause && recorder.status === 'recording' && (
                <button className="button button--ghost" type="button" onClick={recorder.pause}>
                  ❚❚ Pause
                </button>
              )}

              {recorder.supportsPause && recorder.status === 'paused' && (
                <button className="button button--ghost" type="button" onClick={recorder.resume}>
                  ▶ Resume
                </button>
              )}

              <button
                className="button button--ghost"
                type="button"
                onClick={recorder.stop}
                disabled={!isBusy}
              >
                ■ Stop Recording
              </button>
            </div>

            {recorder.error && <p className="inline-error" role="alert">{recorder.error}</p>}

            <div className="live-caption">
              <p className="muted">
                Caption langsung (id-ID) dari browser — opsional. Hanya bantuan saat
                merekam; tidak dikirim ke server dan bukan sumber notulen yang diaudit.
              </p>
              {caption.supported ? (
                <div className="button-row">
                  <button
                    className="button button--ghost"
                    type="button"
                    onClick={caption.listening ? caption.stop : caption.start}
                    disabled={recorder.status !== 'recording'}
                    aria-pressed={caption.listening}
                  >
                    {caption.listening ? '■ Hentikan Caption' : '● Mulai Caption'}
                  </button>
                  {caption.text && (
                    <button className="button button--ghost" type="button" onClick={caption.reset}>
                      Hapus Caption
                    </button>
                  )}
                </div>
              ) : (
                <p className="muted">
                  Browser ini tidak mendukung caption langsung. Rekaman dan transkripsi
                  tetap dapat digunakan seperti biasa.
                </p>
              )}
              {caption.text && (
                <p className="live-caption__text" aria-live="polite" aria-atomic="true">
                  {caption.text}
                </p>
              )}
              {caption.error && <p className="inline-error" role="alert">{caption.error}</p>}
            </div>
          </div>

          {recorder.result && (
            <div className="preview">
              <h3>Preview Rekaman</h3>
              <audio controls src={recorder.result.audioUrl} preload="metadata" />
              <p className="muted">
                Durasi {formatDuration(recorder.result.durationSeconds)} ·
                Ukuran {formatBytes(recorder.result.blob.size)} ·
                Format {recorder.result.mimeType}
              </p>

              <div className="button-row">
                <button
                  className="button button--primary"
                  type="button"
                  onClick={() => void handleSave()}
                  disabled={saving}
                >
                  {saving ? 'Menyimpan…' : 'Save Recording'}
                </button>
                <button
                  className="button button--danger"
                  type="button"
                  onClick={handleDeletePreview}
                  disabled={saving}
                >
                  Hapus Rekaman
                </button>
              </div>

              {saveError && <p className="inline-error" role="alert">{saveError}</p>}
            </div>
          )}

          <AudioUploader
            meetingId={meeting.id}
            disabled={uploadDisabled}
            onSelectionChange={setHasSelectedFile}
            onUploaded={(asset) =>
              onSaved(
                {
                  ...meeting,
                  status: 'UPLOADED',
                  has_recording: true,
                  recording: asset,
                },
                asset,
              )
            }
          />
        </div>
      )}
    </section>
  )
}
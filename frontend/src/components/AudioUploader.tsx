// Antarmuka upload audio lokal: file picker + drag-and-drop + preview.
// File tidak diunggah otomatis; pengguna harus menekan Upload Audio.

import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'

import { uploadAudioFile } from '../api'
import { useAudioFile } from '../hooks/useAudioFile'
import type { AudioAsset } from '../types'
import { formatBytes, formatDuration } from '../utils/format'

interface AudioUploaderProps {
  meetingId: string
  // Nonaktif saat rekaman MediaRecorder sudah ada (satu AudioAsset per meeting).
  disabled: boolean
  onUploaded: (asset: AudioAsset) => void
  onSelectionChange?: (hasFile: boolean) => void
}

const ACCEPT = '.webm,.ogg,.wav,.mp3,.m4a,.mp4,audio/webm,audio/ogg,audio/wav,audio/mpeg,audio/mp4'

export function AudioUploader({ meetingId, disabled, onUploaded, onSelectionChange }: AudioUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const audio = useAudioFile()
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [dragging, setDragging] = useState(false)

  function handleSelect(file: File | undefined) {
    if (!file || disabled || uploading) return
    setUploadError('')
    // File yang ditolak validasi awal tidak boleh mengunci tombol recorder.
    if (audio.selectFile(file)) onSelectionChange?.(true)
    // Buka kemungkinan file baru dengan input yang sama.
    if (inputRef.current) inputRef.current.value = ''
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    handleSelect(event.target.files?.[0])
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    handleSelect(event.dataTransfer.files?.[0])
  }

  async function handleUpload() {
    if (!audio.file || uploading || disabled) return

    setUploading(true)
    setUploadError('')

    try {
      const asset = await uploadAudioFile(
        meetingId,
        audio.file,
        audio.durationSeconds ?? 0,
      )
      // Pesan sukses ditampilkan App via banner pada halaman detail.
      onUploaded(asset)
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Gagal mengunggah audio.')
    } finally {
      setUploading(false)
    }
  }

  function handleRemove() {
    if (uploading) return
    audio.clear()
    setUploadError('')
    onSelectionChange?.(false)
  }

  const locked = disabled || uploading

  return (
    <div className="uploader">
      <h3>Unggah File Audio</h3>
      <p className="muted">
        Atau pilih file yang sudah tersedia. Batas ukuran {formatBytes(audio.maxBytes)}.
        Format: WebM, OGG, WAV, MP3, M4A/MP4.
      </p>

      <div
        className={`dropzone ${dragging ? 'dropzone--active' : ''} ${locked ? 'dropzone--locked' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          if (!locked) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <span className="dropzone__icon" aria-hidden="true">📂</span>
        <p>Tarik file audio ke sini, atau</p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          onChange={handleInputChange}
          disabled={locked}
          className="visually-hidden"
          id={`audio-file-${meetingId}`}
        />
        <button
          className="button button--ghost"
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={locked}
        >
          Choose Audio File
        </button>
      </div>

      {audio.error && <p className="inline-error" role="alert">{audio.error}</p>}

      {audio.file && (
        <div className="selected-file">
          <p><strong>{audio.file.name}</strong></p>
          <p className="muted">
            Ukuran {formatBytes(audio.file.size)} ·
            Durasi {audio.readingDuration ? 'membaca…' : audio.durationSeconds !== null ? formatDuration(audio.durationSeconds) : 'tidak dapat dibaca browser'}
          </p>
          {audio.previewUrl && <audio controls src={audio.previewUrl} preload="metadata" />}

          <div className="button-row">
            <button
              className="button button--primary"
              type="button"
              onClick={() => void handleUpload()}
              disabled={locked}
            >
              {uploading ? 'Mengunggah…' : 'Upload Audio'}
            </button>
            <button
              className="button button--danger"
              type="button"
              onClick={handleRemove}
              disabled={uploading}
            >
              Remove
            </button>
          </div>

          {uploading && (
            <div className="upload-progress" role="status">
              <span className="spinner" aria-hidden="true" />
              Mengunggah {audio.file.name}…
            </div>
          )}
        </div>
      )}

      {uploadError && <p className="inline-error" role="alert">{uploadError}</p>}
    </div>
  )
}
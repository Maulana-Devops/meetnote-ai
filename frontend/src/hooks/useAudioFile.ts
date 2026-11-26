// Hook untuk memilih file audio lokal: validasi awal, preview, dan durasi.
//
// Backend tetap menjadi sumber validasi utama. Hook ini hanya membantu UX:
// menolak file yang jelas salah sebelum pengguna menekan Upload Audio.

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchAppConfig } from '../api'
import type { AppConfig } from '../types'

const ACCEPTED_EXTENSIONS = ['.webm', '.ogg', '.wav', '.mp3', '.m4a', '.mp4']
const ACCEPTED_MIME = new Set([
  'audio/webm',
  'audio/ogg',
  'audio/wav',
  'audio/x-wav',
  'audio/mpeg',
  'audio/mp4',
  'audio/x-m4a',
])
const FALLBACK_MAX_BYTES = 25 * 1024 * 1024

function formatMb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function useAudioFile() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [durationSeconds, setDurationSeconds] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [readingDuration, setReadingDuration] = useState(false)

  const urlRef = useRef<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const mountedRef = useRef(true)

  const revoke = useCallback(() => {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current)
      urlRef.current = null
    }
    audioRef.current?.pause()
    audioRef.current = null
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void fetchAppConfig()
      .then((value) => {
        if (mountedRef.current) setConfig(value)
      })
      .catch(() => {
        // Gagal memuat konfigurasi → pakai fallback 25 MB.
      })

    return () => {
      mountedRef.current = false
      revoke()
    }
  }, [revoke])

  const clear = useCallback(() => {
    revoke()
    setFile(null)
    setPreviewUrl(null)
    setDurationSeconds(null)
    setError('')
    setReadingDuration(false)
  }, [revoke])

  const selectFile = useCallback(
    (candidate: File): boolean => {
      setError('')

      const name = candidate.name.toLowerCase()
      const hasValidExtension = ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))
      if (!hasValidExtension) {
        setError('Ekstensi tidak didukung. Gunakan .webm, .ogg, .wav, .mp3, .m4a, atau .mp4.')
        return false
      }

      const baseType = candidate.type.split(';', 1)[0].trim().toLowerCase()
      const allowedMime = config?.allowed_mime_types ?? Array.from(ACCEPTED_MIME)
      // file.type bisa kosong pada beberapa browser; biarkan backend yang memutuskan.
      if (baseType && !allowedMime.includes(baseType) && !ACCEPTED_MIME.has(baseType)) {
        setError(`MIME type ${baseType} tidak didukung.`)
        return false
      }

      const maxBytes = config?.max_audio_file_bytes ?? FALLBACK_MAX_BYTES
      if (candidate.size === 0) {
        setError('File kosong. Pilih file audio yang berisi rekaman.')
        return false
      }
      if (candidate.size > maxBytes) {
        setError(`Ukuran file ${formatMb(candidate.size)} melebihi batas ${formatMb(maxBytes)}.`)
        return false
      }

      revoke()
      const url = URL.createObjectURL(candidate)
      urlRef.current = url
      setFile(candidate)
      setPreviewUrl(url)
      setDurationSeconds(null)
      setReadingDuration(true)

      const audio = new Audio(url)
      audio.preload = 'metadata'
      audioRef.current = audio
      audio.onloadedmetadata = () => {
        if (!mountedRef.current) return
        setDurationSeconds(Number.isFinite(audio.duration) ? audio.duration : null)
        setReadingDuration(false)
      }
      audio.onerror = () => {
        if (!mountedRef.current) return
        setDurationSeconds(null)
        setReadingDuration(false)
      }

      return true
    },
    [config, revoke],
  )

  return {
    file,
    previewUrl,
    durationSeconds,
    error,
    readingDuration,
    maxBytes: config?.max_audio_file_bytes ?? FALLBACK_MAX_BYTES,
    selectFile,
    clear,
  }
}
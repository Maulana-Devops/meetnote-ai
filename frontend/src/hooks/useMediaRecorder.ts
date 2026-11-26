// Hook untuk merekam audio langsung dari mikrofon memakai MediaRecorder API.
//
// Semua state recorder ada di sini supaya komponen UI tetap sederhana.
// Blob tidak disimpan ke localStorage — hanya URL sementara untuk preview.

import { useCallback, useEffect, useRef, useState } from 'react'

export type RecorderStatus = 'idle' | 'recording' | 'paused' | 'stopped'

export interface RecordingResult {
  blob: Blob
  audioUrl: string
  durationSeconds: number
  mimeType: string
  filename: string
}

// Urutan prioritas: Chrome/Edge (webm), Firefox (ogg), Safari (mp4/wav).
const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/ogg;codecs=opus',
  'audio/mp4',
  'audio/wav',
]

const EXTENSION_BY_MIME: Record<string, string> = {
  'audio/webm': '.webm',
  'audio/ogg': '.ogg',
  'audio/mp4': '.m4a',
  'audio/wav': '.wav',
}

function pickMimeType(): string | null {
  if (typeof MediaRecorder === 'undefined') return null
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? null
}

function extensionFor(mimeType: string): string {
  const base = mimeType.split(';', 1)[0].trim().toLowerCase()
  return EXTENSION_BY_MIME[base] ?? '.webm'
}

function describeMicError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return 'Izin mikrofon ditolak. Izinkan akses mikrofon di browser lalu coba lagi.'
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return 'Mikrofon tidak ditemukan. Pastikan perangkat audio terhubung.'
  }
  if (name === 'NotReadableError') {
    return 'Mikrofon sedang digunakan aplikasi lain.'
  }
  return error instanceof Error ? error.message : 'Gagal mengakses mikrofon.'
}

export function useMediaRecorder() {
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [error, setError] = useState('')
  const [elapsedMs, setElapsedMs] = useState(0)
  const [result, setResult] = useState<RecordingResult | null>(null)
  const [supportsPause, setSupportsPause] = useState(false)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<BlobPart[]>([])
  const timerRef = useRef<number | null>(null)
  const elapsedRef = useRef(0)
  const accumulatedRef = useRef(0)
  const startedAtRef = useRef(0)
  const objectUrlRef = useRef<string | null>(null)
  const mountedRef = useRef(true)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const startTimer = useCallback(() => {
    clearTimer()
    timerRef.current = window.setInterval(() => {
      elapsedRef.current = accumulatedRef.current + (Date.now() - startedAtRef.current)
      setElapsedMs(elapsedRef.current)
    }, 100)
  }, [clearTimer])

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  const revokePreview = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  /** Kembalikan ke kondisi awal (hapus rekaman sementara). */
  const reset = useCallback(() => {
    clearTimer()
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.ondataavailable = null
      recorderRef.current.onstop = null
      recorderRef.current.onerror = null
      recorderRef.current.stop()
    }
    recorderRef.current = null
    stopStream()
    revokePreview()

    chunksRef.current = []
    elapsedRef.current = 0
    accumulatedRef.current = 0
    setElapsedMs(0)
    setResult(null)
    setError('')
    setStatus('idle')
  }, [clearTimer, revokePreview, stopStream])

  const start = useCallback(async () => {
    setError('')

    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Browser tidak mendukung akses mikrofon. Gunakan HTTPS atau localhost.')
      return
    }

    // Rekaman lama ditimpa, jangan biarkan object URL bocor.
    if (result) reset()

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = pickMimeType()

      if (!mimeType) {
        stream.getTracks().forEach((track) => track.stop())
        setError('Browser tidak mendukung format audio yang diizinkan backend.')
        return
      }

      const recorder = new MediaRecorder(stream, { mimeType })
      recorderRef.current = recorder
      streamRef.current = stream
      chunksRef.current = []

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }

      recorder.onstop = () => {
        clearTimer()
        stopStream()

        const finalMime = recorder.mimeType || mimeType
        const blob = new Blob(chunksRef.current, { type: finalMime })

        revokePreview()
        const audioUrl = URL.createObjectURL(blob)
        objectUrlRef.current = audioUrl

        if (!mountedRef.current) return

        setResult({
          blob,
          audioUrl,
          durationSeconds: elapsedRef.current / 1000,
          mimeType: finalMime,
          filename: `recording-${Date.now()}${extensionFor(finalMime)}`,
        })
        setStatus('stopped')
      }

      recorder.onerror = () => {
        if (mountedRef.current) setError('Terjadi kesalahan saat merekam audio.')
      }

      accumulatedRef.current = 0
      startedAtRef.current = Date.now()
      setSupportsPause(
        typeof recorder.pause === 'function' && typeof recorder.resume === 'function',
      )
      recorder.start(250)
      setStatus('recording')
      startTimer()
    } catch (error) {
      stopStream()
      setError(describeMicError(error))
    }
  }, [clearTimer, reset, result, revokePreview, startTimer, stopStream])

  const pause = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state !== 'recording') return

    accumulatedRef.current += Date.now() - startedAtRef.current
    clearTimer()
    recorder.pause()
    setStatus('paused')
  }, [clearTimer])

  const resume = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state !== 'paused') return

    startedAtRef.current = Date.now()
    recorder.resume()
    setStatus('recording')
    startTimer()
  }, [startTimer])

  const stop = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state === 'inactive') return

    accumulatedRef.current += Date.now() - startedAtRef.current
    clearTimer()
    recorder.stop()
  }, [clearTimer])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      clearTimer()
      if (recorderRef.current && recorderRef.current.state !== 'inactive') {
        recorderRef.current.ondataavailable = null
        recorderRef.current.onstop = null
        recorderRef.current.onerror = null
        recorderRef.current.stop()
      }
      stopStream()
      revokePreview()
    }
  }, [clearTimer, revokePreview, stopStream])

  return {
    status,
    error,
    elapsedMs,
    result,
    supportsPause,
    start,
    pause,
    resume,
    stop,
    reset,
  }
}
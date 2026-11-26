// Caption langsung berbahasa Indonesia dari Web Speech API (Fase 1).
//
// Ini HANYA bantuan visually saat merekam. Teks caption tidak dikirim ke
// backend, tidak disimpan, dan BUKAN sumber notulen yang bisa diaudit.
// Sumber notulen tetap rekaman yang sudah disimpan + transkripsi backend.

import { useCallback, useEffect, useRef, useState } from 'react'

interface CaptionAlternative {
  transcript?: string
}

interface CaptionResult {
  isFinal: boolean
  alternatives?: CaptionAlternative[]
}

interface CaptionEvent {
  resultIndex: number
  results: ArrayLike<CaptionResult>
}

interface CaptionErrorEvent {
  error: string
}

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: CaptionEvent) => void) | null
  onerror: ((event: CaptionErrorEvent) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
}

type RecognitionCtor = new () => SpeechRecognitionLike

function getRecognitionCtor(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null
  const candidate = window as unknown as {
    SpeechRecognition?: RecognitionCtor
    webkitSpeechRecognition?: RecognitionCtor
  }
  return candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null
}

const ERROR_MESSAGES: Record<string, string> = {
  'not-allowed': 'Akses mikrofon/caption ditolak. Izinkan di browser Anda.',
  'service-not-allowed': 'Layanan caption tidak tersedia di browser ini.',
  'no-speech': 'Tidak ada suara yang terdeteksi. Coba lagi.',
  network: 'Jaringan/browser tidak dapat menjangkau layanan caption.',
}

export interface LiveCaption {
  supported: boolean
  listening: boolean
  text: string
  error: string
  start: () => void
  stop: () => void
  reset: () => void
}

export function useLiveCaption(): LiveCaption {
  const supported = getRecognitionCtor() !== null
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const finalTextRef = useRef('')
  const [listening, setListening] = useState(false)
  const [text, setText] = useState('')
  const [error, setError] = useState('')

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
    recognitionRef.current = null
    setListening(false)
  }, [])

  const start = useCallback(() => {
    const Recognition = getRecognitionCtor()
    if (!Recognition || recognitionRef.current) return

    const recognition = new Recognition()
    recognition.lang = 'id-ID'
    recognition.continuous = true
    recognition.interimResults = true
    finalTextRef.current = ''
    setText('')
    setError('')

    recognition.onresult = (event) => {
      let finalChunk = ''
      let interimChunk = ''
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        const piece = result.alternatives?.[0]?.transcript?.trim() ?? ''
        if (!piece) continue
        if (result.isFinal) finalChunk += `${piece} `
        else interimChunk += `${piece} `
      }
      if (finalChunk) {
        finalTextRef.current = `${finalTextRef.current} ${finalChunk}`.trim()
      }
      setText(`${finalTextRef.current} ${interimChunk}`.trim())
    }

    recognition.onerror = (event) => {
      setError(ERROR_MESSAGES[event.error] ?? 'Caption langsung gagal. Coba lagi.')
      recognitionRef.current = null
      setListening(false)
    }

    recognition.onend = () => setListening(false)

    recognitionRef.current = recognition
    try {
      recognition.start()
      setListening(true)
    } catch {
      recognitionRef.current = null
      setError('Caption langsung gagal dimulai.')
      setListening(false)
    }
  }, [])

  const reset = useCallback(() => {
    finalTextRef.current = ''
    setText('')
    setError('')
  }, [])

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop()
      recognitionRef.current = null
    }
  }, [])

  return { supported, listening, text, error, start, stop, reset }
}

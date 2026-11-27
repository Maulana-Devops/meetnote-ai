// Helper keamanan untuk data yang datang dari API.
// Sengaja murni (tanpa React / import.meta) agar bisa diuji dengan node:test.

const MAX_ERROR_MESSAGE_LENGTH = 200
const MAX_DETAIL_ITEMS = 3

// Tolak path absolut, URL, markup, dan pola token. Backend tidak pernah
// mengirim ini ke klien, tetapi proxy/DEBUG atau input klien yang dipantulkan
// tidak boleh tampil apa adanya di UI.
const UNSAFE_MESSAGE = /[\\/<>]|\b(?:sk-[A-Za-z0-9_-]+|AIza[0-9A-Za-z_-]+|Bearer\s+\S+)\b/i

/** Batasi satu pesan error; kembalikan fallback bila mencurigakan. */
export function sanitizeErrorMessage(raw: unknown, fallback: string): string {
  if (typeof raw !== 'string') return fallback
  const value = raw.replace(/\s+/g, ' ').trim()
  if (!value || value.length > MAX_ERROR_MESSAGE_LENGTH) return fallback
  if (UNSAFE_MESSAGE.test(value)) return fallback
  return value
}

/** Ambil pesan dari `detail` FastAPI (string atau array item `msg`). */
export function readDetailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return sanitizeErrorMessage(detail, fallback)
  if (Array.isArray(detail)) {
    const messages = detail
      .slice(0, 10)
      .map((item) =>
        item && typeof item === 'object' && 'msg' in item
          ? sanitizeErrorMessage((item as { msg: unknown }).msg, '')
          : '',
      )
      .filter((message) => message.length > 0)
      .slice(0, MAX_DETAIL_ITEMS)
    return messages.length ? messages.join('; ') : fallback
  }
  return fallback
}

/** URL same-origin yang dipakai bila `playback_url` tidak valid. */
export const SAFE_PLAYBACK_FALLBACK_PATH = '/api/v1/health'

function isLoopbackHost(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
}

/**
 * Pastikan audio hanya dimuat dari base URL backend yang sama.
 * Menerima path relatif `/api/...` atau URL absolut dengan origin yang sama.
 */
export function resolvePlaybackUrl(raw: unknown, apiBaseUrl: string): string {
  const base = apiBaseUrl.replace(/\/+$/, '')
  const fallback = `${base}${SAFE_PLAYBACK_FALLBACK_PATH}`
  const value = typeof raw === 'string' ? raw.trim() : ''

  if (value.startsWith('/api/') && !value.startsWith('//')) return `${base}${value}`

  try {
    const parsed = new URL(value)
    if (parsed.origin !== new URL(base).origin) return fallback
    if (parsed.protocol === 'https:') return parsed.toString()
    if (parsed.protocol === 'http:' && isLoopbackHost(parsed.hostname)) return parsed.toString()
  } catch {
    // Bukan URL absolut yang valid.
  }
  return fallback
}

/** Judul aman untuk dialog konfirmasi (bukan vektor XSS, tapi bisa menyesatkan). */
export function safeConfirmTitle(raw: unknown, maxLength = 80): string {
  const text =
    typeof raw === 'string'
      ? raw.replace(/[\u0000-\u001f\u007f\u2028\u2029]/g, ' ').replace(/\s+/g, ' ').trim()
      : ''
  if (!text) return '(tanpa judul)'
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}\u2026` : text
}

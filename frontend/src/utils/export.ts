// Helper export notulen (Sprint 10).
// Fungsi di sini sengaja murni/Tanpa React agar dapat diuji dengan node:test
// bawaan Node.js tanpa menambah framework testing.

export type ExportFormat = 'txt' | 'pdf'

/** Nama file fallback yang aman bila backend tidak mengirim header filename. */
export function fallbackExportFilename(meetingId: string, format: ExportFormat): string {
  const safeId = meetingId.replace(/[^A-Za-z0-9-]/g, '').slice(0, 8) || 'rapat'
  return `notulen-${safeId}.${format}`
}

/** Nama file hanya boleh memuat ASCII aman dan ekstensi sesuai format. */
function isSafeFilename(value: string, format: ExportFormat): boolean {
  if (!value || value.length > 120) return false
  if (!/^[A-Za-z0-9][A-Za-z0-9._ -]*$/.test(value)) return false
  if (value.includes('..')) return false
  return value.toLowerCase().endsWith(`.${format}`)
}

/**
 * Ambil nama file dari header Content-Disposition.
 * Format backend: attachment; filename="notulen-rapat.txt"
 * Bila header tidak ada/tidak aman, pakai fallback berdasarkan ID meeting.
 */
export function resolveExportFilename(
  contentDisposition: string | null | undefined,
  meetingId: string,
  format: ExportFormat,
): string {
  const header = contentDisposition ?? ''
  const quoted = /filename\s*=\s*"([^"]*)"/i.exec(header)
  const bare = /filename\s*=\s*([^;\s]+)/i.exec(header)
  const candidate = quoted?.[1] ?? bare?.[1] ?? ''
  return isSafeFilename(candidate, format) ? candidate : fallbackExportFilename(meetingId, format)
}

/**
 * Simpan Blob ke disk browser melalui anchor sementara.
 * Object URL selalu dicabut, sehingga tidak ada memori/file yang tertinggal.
 */
export function saveBlob(blob: Blob, filename: string, revokeDelayMs = 1000): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
  }
  // Beri browser waktu memulai unduhan sebelum object URL dicabut.
  setTimeout(() => URL.revokeObjectURL(url), revokeDelayMs)
}

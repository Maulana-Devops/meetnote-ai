// Pengujian helper keamanan pesan error dan URL playback.
// Memakai node:test bawaan Node.js — tanpa framework baru.

import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  readDetailMessage,
  resolvePlaybackUrl,
  safeConfirmTitle,
  SAFE_PLAYBACK_FALLBACK_PATH,
  sanitizeErrorMessage,
} from '../src/utils/apiSafety.ts'

const FALLBACK = 'Gagal memuat data (HTTP 500).'
const BASE = 'https://meetnote.example.test'
const FALLBACK_URL = `${BASE}${SAFE_PLAYBACK_FALLBACK_PATH}`

test('pesan error aman diterima apa adanya', () => {
  assert.equal(readDetailMessage('Meeting tidak ditemukan.', FALLBACK), 'Meeting tidak ditemukan.')
  assert.equal(sanitizeErrorMessage('Format audio tidak didukung.', FALLBACK), 'Format audio tidak didukung.')
})

test('pesan error yang membocorkan path, URL, markup, atau token diganti fallback', () => {
  for (const value of [
    '/app/storage/meetings/rahasia.wav',
    'C:\\Users\\private\\meetnote.db',
    'https://internal.example.test/v1',
    '<img src=x onerror=alert(1)>',
    'kunci sk-abcdefghijklmnop',
    'Authorization: Bearer abc.def',
    'a'.repeat(5000),
    '',
    '   ',
  ]) {
    assert.equal(readDetailMessage(value, FALLBACK), FALLBACK, value)
  }
  assert.equal(readDetailMessage(42, FALLBACK), FALLBACK)
  assert.equal(readDetailMessage(undefined, FALLBACK), FALLBACK)
})

test('array detail dibatasi tiga pesan dan item tidak valid dibuang', () => {
  const detail = Array.from({ length: 50 }, (_, index) => ({ msg: `Kesalahan ${index + 1}` }))
  assert.equal(
    readDetailMessage(detail, FALLBACK),
    'Kesalahan 1; Kesalahan 2; Kesalahan 3',
  )

  assert.equal(
    readDetailMessage(
      [
        { msg: 'Aman' },
        { msg: '/tmp/rahasia' },
        { msg: 123 },
        { msg: 'Juga aman' },
      ],
      FALLBACK,
    ),
    'Aman; Juga aman',
  )
  assert.equal(readDetailMessage([{ msg: '/tmp/rahasia' }], FALLBACK), FALLBACK)
})

test('playbackUrl menerima path relatif /api dan URL absolut origin yang sama', () => {
  assert.equal(
    resolvePlaybackUrl('/api/v1/meetings/abc/recording/play', BASE),
    `${BASE}/api/v1/meetings/abc/recording/play`,
  )
  assert.equal(
    resolvePlaybackUrl(`${BASE}/api/v1/meetings/abc/recording/play`, `${BASE}/`),
    `${BASE}/api/v1/meetings/abc/recording/play`,
  )
  assert.equal(
    resolvePlaybackUrl('http://localhost:8000/api/v1/recording/play', 'http://localhost:8000'),
    'http://localhost:8000/api/v1/recording/play',
  )
})

test('playbackUrl menolak origin lain, skema asing, dan path非-API', () => {
  for (const value of [
    '//evil.test/audio',
    'http://evil.test/audio',
    'https://evil.test/audio',
    'javascript:alert(1)',
    'data:audio/mpeg,AAAA',
    '/health',
    '/app/storage/recording.wav',
    'C:\\private\\recording.wav',
    '',
    null,
  ]) {
    assert.equal(resolvePlaybackUrl(value, BASE), FALLBACK_URL, String(value))
  }
  assert.equal(
    resolvePlaybackUrl('http://meetnote.example.test/api/audio', BASE),
    FALLBACK_URL,
  )
})

test('judul konfirmasi dibersihkan dari kontrol dan dipotong', () => {
  assert.equal(safeConfirmTitle('Kirim laporan'), 'Kirim laporan')
  assert.equal(safeConfirmTitle('  Kirim\n  laporan  '), 'Kirim laporan')
  assert.equal(safeConfirmTitle(null), '(tanpa judul)')
  assert.equal(safeConfirmTitle('a'.repeat(200)).length, 80)
  assert.equal(safeConfirmTitle('a'.repeat(200)).endsWith('\u2026'), true)
})

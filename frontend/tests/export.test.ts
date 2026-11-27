// Pengujian helper export notulen (Sprint 10).
// Memakai node:test bawaan Node.js — tanpa Vitest/Jest/dependency baru.
// Jalankan: npm test

import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  fallbackExportFilename,
  resolveExportFilename,
  saveBlob,
} from '../src/utils/export.ts'

const MEETING_ID = '9f1c2a3e-4b5d-6e7f-8a9b-0c1d2e3f4a5b'

test('mengambil nama file dari header Content-Disposition backend', () => {
  const header = 'attachment; filename="notulen-rapat-rilis.txt"'
  assert.equal(
    resolveExportFilename(header, MEETING_ID, 'txt'),
    'notulen-rapat-rilis.txt',
  )
})

test('mendukung header tanpa tanda kutip dan huruf besar', () => {
  assert.equal(
    resolveExportFilename('Attachment; Filename=notulen-rapat.pdf', MEETING_ID, 'pdf'),
    'notulen-rapat.pdf',
  )
})

test('menolak header dengan path traversal lalu memakai fallback', () => {
  const expected = fallbackExportFilename(MEETING_ID, 'txt')
  assert.equal(expected, 'notulen-9f1c2a3e.txt')
  assert.equal(
    resolveExportFilename('attachment; filename="../../etc/passwd.txt"', MEETING_ID, 'txt'),
    expected,
  )
  assert.equal(
    resolveExportFilename('attachment; filename="..\\rahasia.pdf"', MEETING_ID, 'pdf'),
    fallbackExportFilename(MEETING_ID, 'pdf'),
  )
})

test('menolak quote, newline, dan nama file terlalu panjang', () => {
  const fallback = fallbackExportFilename(MEETING_ID, 'pdf')
  assert.equal(resolveExportFilename('filename="rapat\\".pdf"', MEETING_ID, 'pdf'), fallback)
  assert.equal(resolveExportFilename('filename="rapat\nxyz.pdf"', MEETING_ID, 'pdf'), fallback)
  assert.equal(resolveExportFilename(`filename="${'a'.repeat(200)}.pdf"`, MEETING_ID, 'pdf'), fallback)
})

test('menolak filename* RFC 5987, separator, unicode aneh, dan leading dot', () => {
  const expected = fallbackExportFilename(MEETING_ID, 'txt')
  assert.equal(
    resolveExportFilename("attachment; filename*=UTF-8''evil%2F.txt", MEETING_ID, 'txt'),
    expected,
  )
  assert.equal(resolveExportFilename('filename="a;b.txt"', MEETING_ID, 'txt'), expected)
  assert.equal(resolveExportFilename('filename="\u2028x.txt"', MEETING_ID, 'txt'), expected)
  assert.equal(resolveExportFilename('filename=".bashrc"', MEETING_ID, 'txt'), expected)
})

test('menolak nama file dengan ekstensi yang tidak sesuai format', () => {
  const expected = fallbackExportFilename(MEETING_ID, 'pdf')
  assert.equal(
    resolveExportFilename('filename="notulen-rapat.txt"', MEETING_ID, 'pdf'),
    expected,
  )
  assert.equal(
    resolveExportFilename('filename="notulen-rapat.PDF"', MEETING_ID, 'pdf'),
    'notulen-rapat.PDF',
  )
})

test('fallback memakai 8 karakter ID pertama dan ekstensi sesuai format', () => {
  assert.equal(fallbackExportFilename('ABCD-1234-xyz', 'txt'), 'notulen-ABCD-123.txt')
  assert.equal(fallbackExportFilename('!!', 'pdf'), 'notulen-rapat.pdf')
})

test('header kosong memakai fallback', () => {
  assert.equal(
    resolveExportFilename(null, MEETING_ID, 'txt'),
    fallbackExportFilename(MEETING_ID, 'txt'),
  )
  assert.equal(
    resolveExportFilename(undefined, MEETING_ID, 'pdf'),
    fallbackExportFilename(MEETING_ID, 'pdf'),
  )
})

test('saveBlob membuat anchor, mengkliknya, lalu membersihkan object URL', async () => {
  const clicks: string[] = []
  const revocations: string[] = []
  const appended: string[] = []
  const removed: string[] = []

  const anchor = {
    href: '',
    download: '',
    style: { display: '' },
    click() {
      clicks.push(this.download)
    },
    remove() {
      removed.push(this.download)
    },
  }

  const originalCreate = URL.createObjectURL
  const originalRevoke = URL.revokeObjectURL
  const originalDocument = globalThis.document

  const fakeDocument = {
    createElement: () => anchor,
    body: {
      appendChild(node: typeof anchor) {
        appended.push(node.download)
        return node
      },
    },
  }

  URL.createObjectURL = (() => 'blob:notulen-test') as typeof URL.createObjectURL
  URL.revokeObjectURL = ((url: string) => {
    revocations.push(url)
  }) as typeof URL.revokeObjectURL
  globalThis.document = fakeDocument as unknown as Document

  try {
    saveBlob(new Blob(['isi']), 'notulen-rapat.txt', 0)
    // Beri setTimeout(revokeDelayMs=0) kesempatan berjalan.
    await new Promise((resolve) => setTimeout(resolve, 10))
  } finally {
    URL.createObjectURL = originalCreate
    URL.revokeObjectURL = originalRevoke
    globalThis.document = originalDocument
  }

  assert.deepEqual(clicks, ['notulen-rapat.txt'])
  assert.deepEqual(appended, ['notulen-rapat.txt'])
  assert.deepEqual(removed, ['notulen-rapat.txt'])
  assert.deepEqual(revocations, ['blob:notulen-test'])
  assert.equal(anchor.href, 'blob:notulen-test')
})

// Detail meeting: putar rekaman, transkripsi, diarisasi, hapus hasil,
// atau tambah rekaman baru. Sprint 4/5 menambah alur pekerjaan background.

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  deleteActionItem,
  deleteActionItems,
  deleteDiarization,
  deleteRecording,
  deleteSummary,
  deleteTranscript,
  downloadExport,
  fetchActionItems,
  fetchDiarization,
  fetchSummary,
  fetchTranscription,
  playbackUrl,
  refreshMeeting,
  startActionItems,
  startDiarization,
  startSummary,
  startTranscription,
  updateActionItem,
} from '../api'
import type {
  ActionItem,
  ActionItemListDetail,
  ActionItemStatus,
  ActionItemUpdate,
  DiarizationDetail,
  Meeting,
  SpeakerSummary,
  SummaryDecision,
  SummaryDetail,
  SummarySourceRef,
  SummaryTopic,
  TranscriptSegment,
  TranscriptionDetail,
} from '../types'
import { saveBlob, type ExportFormat } from '../utils/export'
import { formatBytes, formatDuration } from '../utils/format'
import { SpeakerManager } from './SpeakerManager'
import { StatusBadge } from './StatusBadge'
import { TranscriptEditor } from './TranscriptEditor'

const POLL_INTERVAL_MS = 1500
// ~210 detik; lebih panjang dari timeout provider terbesar (diarisasi 180 detik).
const MAX_POLL_ATTEMPTS = 140

interface MeetingDetailProps {
  meeting: Meeting
  justSaved: boolean
  onBack: () => void
  onAddRecording: () => void
  onDeleted: (meeting: Meeting) => void
  onMeetingUpdated: (meeting: Meeting) => void
}

/** Tampilan waktu pendek untuk referensi sumber ringkasan. */
function formatSummaryClock(seconds: number) {
  const safe = Number.isFinite(seconds) && seconds >= 0 ? seconds : 0
  const minutes = Math.floor(safe / 60)
  const rest = safe % 60
  return `${minutes}:${rest.toFixed(1).padStart(4, '0')}`
}

/**
 * Setelah posisi digeser, langsung putar dari situ. Klik tombol adalah user
 * gesture sehingga autoplay umumnya diizinkan; bila browser tetap menolak,
 * pengguna bisa menekan Play manual tanpa melihat error mengganggu.
 */
function playAfterSeek(audio: HTMLAudioElement) {
  void audio.play().catch(() => {
    // Autoplay ditolak kebijakan browser — posisi tetap tersimpan.
  })
}

export function MeetingDetail({
  meeting,
  justSaved,
  onBack,
  onAddRecording,
  onDeleted,
  onMeetingUpdated,
}: MeetingDetailProps) {
  const [current, setCurrent] = useState(meeting)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [notice, setNotice] = useState('')

  // Sprint 10: export notulen. Satu format aktif untuk mencegah klik ganda.
  const [exporting, setExporting] = useState<ExportFormat | null>(null)
  const [exportError, setExportError] = useState('')
  // Ref menutup celah klik ganda dalam satu tick sebelum React me-render ulang.
  const exportInFlightRef = useRef(false)

  const [transcription, setTranscription] = useState<TranscriptionDetail | null>(null)
  const [transcriptLoading, setTranscriptLoading] = useState(true)
  const [transcribing, setTranscribing] = useState(false)
  const [deletingTranscript, setDeletingTranscript] = useState(false)
  const [transcriptError, setTranscriptError] = useState('')
  const [transcriptNotice, setTranscriptNotice] = useState('')

  const [diarization, setDiarization] = useState<DiarizationDetail | null>(null)
  const [diarizationLoading, setDiarizationLoading] = useState(true)
  const [diarizing, setDiarizing] = useState(false)
  const [deletingDiarization, setDeletingDiarization] = useState(false)
  const [diarizationError, setDiarizationError] = useState('')
  const [diarizationNotice, setDiarizationNotice] = useState('')

  // Sprint 7: ringkasan AI berasal HANYA dari transkrip yang tersimpan.
  const [summary, setSummary] = useState<SummaryDetail | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summarizing, setSummarizing] = useState(false)
  const [deletingSummary, setDeletingSummary] = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const [summaryNotice, setSummaryNotice] = useState('')

  // Sprint 8: action items berasal dari transkrip yang sama, dikelola terpisah.
  const [actionDetail, setActionDetail] = useState<ActionItemListDetail | null>(null)
  const [actionLoading, setActionLoading] = useState(true)
  const [extracting, setExtracting] = useState(false)
  const [deletingActionItems, setDeletingActionItems] = useState(false)
  const [actionError, setActionError] = useState('')
  const [actionNotice, setActionNotice] = useState('')
  const [editingItemId, setEditingItemId] = useState<string | null>(null)
  const [actionDraft, setActionDraft] = useState<ActionItemUpdate>({})
  const [savingActionItem, setSavingActionItem] = useState(false)

  // Sprint 6: satu elemen audio yang sama dipakai untuk playback dan seek.
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [audioUnavailable, setAudioUnavailable] = useState(false)

  /** Sinkronkan status Meeting setelah job background selesai/gagal. */
  const syncMeeting = useCallback(
    async (meetingId: string) => {
      try {
        const updated = await refreshMeeting(meetingId)
        setCurrent(updated)
        onMeetingUpdated(updated)
      } catch {
        // Status pada endpoint transcription tetap menjadi sumber utama.
      }
    },
    [onMeetingUpdated],
  )

  /** Segmen transkrip perlu diambil ulang agar label speaker terbaru tampil. */
  const refreshTranscriptDetail = useCallback(async (meetingId: string) => {
    const detail = await fetchTranscription(meetingId)
    setTranscription(detail)
    return detail
  }, [])

  /** Sprint 6: pindahkan pemutar yang sudah ada, jangan buat unduhan baru. */
  function handleSeek(seconds: number) {
    const audio = audioRef.current
    if (!audio || audioUnavailable) {
      setTranscriptNotice('Pemutar audio tidak tersedia untuk meeting ini.')
      return
    }
    if (!Number.isFinite(seconds) || seconds < 0) return

    try {
      if (audio.readyState === 0) {
        audio.addEventListener(
          'loadedmetadata',
          () => {
            audio.currentTime = seconds
            playAfterSeek(audio)
          },
          { once: true },
        )
        return
      }
      if (Number.isFinite(audio.duration) && audio.duration > 0 && seconds > audio.duration) {
        setTranscriptNotice('Waktu segmen berada di luar durasi rekaman.')
        return
      }
      audio.currentTime = seconds
      playAfterSeek(audio)
    } catch {
      setAudioUnavailable(true)
      setTranscriptNotice('Browser tidak mendukung perpindahan waktu pada pemutar ini.')
    }
  }

  /** Sprint 7: satu tombol sumber memakai audio element yang sama (tanpa unduhan baru). */
  function renderSourceRef(ref: SummarySourceRef, key: string) {
    const label = `${formatSummaryClock(ref.start_seconds)}–${formatSummaryClock(ref.end_seconds)}`
    return (
      <button
        key={key}
        className="source-ref"
        type="button"
        title={`Putar dari ${label} (${ref.segment_ids.length} segmen)`}
        onClick={() => handleSeek(ref.start_seconds)}
      >
        ▶ {label}
      </button>
    )
  }

  function renderTopic(topic: SummaryTopic, index: number) {
    return (
      <li key={`topic-${index}-${topic.segment_ids.join('-')}`} className="summary-item">
        <div className="summary-item__head">
          <strong>{topic.title}</strong>
          {renderSourceRef(topic, `topic-ref-${index}`)}
        </div>
        <p>{topic.detail}</p>
      </li>
    )
  }

  function renderDecision(decision: SummaryDecision, index: number) {
    return (
      <li key={`decision-${index}-${decision.segment_ids.join('-')}`} className="summary-item">
        <div className="summary-item__head">
          <span>{decision.text}</span>
          {renderSourceRef(decision, `decision-ref-${index}`)}
        </div>
      </li>
    )
  }

  function handleSegmentTextSaved(updated: TranscriptSegment) {
    setTranscription((previous) => {
      if (!previous) return previous
      const next = previous.segments.map((item) => (item.id === updated.id ? updated : item))
      return {
        ...previous,
        segments: next,
        full_text: next.map((item) => item.text).join('\n'),
      }
    })
    setTranscriptNotice('Teks segmen disimpan.')
  }

  function handleSegmentSpeakerSaved(updated: TranscriptSegment) {
    setTranscription((previous) =>
      previous
        ? {
            ...previous,
            segments: previous.segments.map((item) => (item.id === updated.id ? updated : item)),
          }
        : previous,
    )
    setTranscriptNotice('Speaker segmen diperbarui.')

    // Jumlah segmen per speaker ikut berubah; segarkan tanpa menimpa editor.
    void fetchDiarization(current.id)
      .then((detail) => setDiarization(detail))
      .catch(() => {
        // Data segmen sudah benar dari response PATCH.
      })
  }

  function handleSpeakerUpdated(updated: SpeakerSummary) {
    setDiarization((previous) =>
      previous
        ? {
            ...previous,
            speakers: previous.speakers.map((item) => (item.id === updated.id ? updated : item)),
          }
        : previous,
    )
    setTranscription((previous) =>
      previous
        ? {
            ...previous,
            segments: previous.segments.map((item) =>
              item.speaker_id === updated.id
                ? { ...item, speaker_display_name: updated.display_name }
                : item,
            ),
          }
        : previous,
    )
    setDiarizationNotice('Nama speaker diperbarui.')
  }

  /** Sprint 10: unduh satu format; klik lain diabaikan selama proses berjalan. */
  async function handleExport(format: ExportFormat) {
    if (exportInFlightRef.current) return
    exportInFlightRef.current = true
    setExporting(format)
    setExportError('')
    try {
      const { blob, filename } = await downloadExport(current.id, format)
      saveBlob(blob, filename)
    } catch (error) {
      setExportError(
        error instanceof Error ? error.message : 'Gagal mengunduh notulen.',
      )
    } finally {
      exportInFlightRef.current = false
      setExporting(null)
    }
  }

  useEffect(() => {
    let cancelled = false

    setCurrent(meeting)
    setNotice('')
    setDeleteError('')
    setTranscriptError('')
    setTranscriptNotice('')
    setTranscription(null)
    setTranscriptLoading(true)
    setTranscribing(false)
    setDeletingTranscript(false)
    setDiarization(null)
    setDiarizationLoading(true)
    setDiarizing(false)
    setDeletingDiarization(false)
    setDiarizationError('')
    setDiarizationNotice('')
    setSummary(null)
    setSummaryLoading(true)
    setSummarizing(false)
    setDeletingSummary(false)
    setSummaryError('')
    setSummaryNotice('')
    setActionDetail(null)
    setActionLoading(true)
    setExtracting(false)
    setDeletingActionItems(false)
    setActionError('')
    setActionNotice('')
    setEditingItemId(null)
    setActionDraft({})
    setSavingActionItem(false)
    setAudioUnavailable(false)

    void fetchTranscription(meeting.id)
      .then((detail) => {
        if (!cancelled) setTranscription(detail)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setTranscriptError(
            error instanceof Error ? error.message : 'Gagal memuat status transkripsi.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setTranscriptLoading(false)
      })

    void fetchDiarization(meeting.id)
      .then((detail) => {
        if (!cancelled) setDiarization(detail)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setDiarizationError(
            error instanceof Error ? error.message : 'Gagal memuat status diarisasi.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setDiarizationLoading(false)
      })

    void fetchSummary(meeting.id)
      .then((detail) => {
        if (!cancelled) setSummary(detail)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSummaryError(
            error instanceof Error ? error.message : 'Gagal memuat status ringkasan.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false)
      })

    void fetchActionItems(meeting.id)
      .then((detail) => {
        if (!cancelled) setActionDetail(detail)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setActionError(
            error instanceof Error ? error.message : 'Gagal memuat status action items.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setActionLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [meeting])

  // Background task berjalan di server. Polling ringan menggantikan websocket.
  useEffect(() => {
    if (transcription?.status !== 'PROCESSING') return

    let cancelled = false
    let attempts = 0
    const maxAttempts = MAX_POLL_ATTEMPTS
    const timer = window.setInterval(() => {
      if (cancelled) return
      attempts += 1
      if (attempts > maxAttempts) {
        window.clearInterval(timer)
        setTranscriptNotice(
          'Status transkripsi belum final. Tekan Refresh untuk memeriksa ulang.',
        )
        return
      }

      void fetchTranscription(current.id)
        .then((detail) => {
          if (cancelled) return
          setTranscription(detail)
          if (detail.status !== 'PROCESSING') {
            window.clearInterval(timer)
            void syncMeeting(current.id)
          }
        })
        .catch(() => {
          // Gangguan sementara: polling dilanjutkan sampai batas attempts.
        })
    }, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [current.id, transcription?.status, syncMeeting])

  // Job diarisasi juga berjalan di server; polling sampai status final.
  useEffect(() => {
    if (diarization?.status !== 'PROCESSING') return

    let cancelled = false
    let attempts = 0
    const maxAttempts = MAX_POLL_ATTEMPTS
    const timer = window.setInterval(() => {
      if (cancelled) return
      attempts += 1
      if (attempts > maxAttempts) {
        window.clearInterval(timer)
        setDiarizationNotice(
          'Status diarisasi belum final. Tekan Refresh untuk memeriksa ulang.',
        )
        return
      }

      void fetchDiarization(current.id)
        .then(async (detail) => {
          if (cancelled) return
          setDiarization(detail)
          if (detail.status !== 'PROCESSING') {
            window.clearInterval(timer)
            try {
              await refreshTranscriptDetail(current.id)
            } catch {
              // Status diarisasi tetap menjadi sumber utama.
            }
          }
        })
        .catch(() => {
          // Gangguan sementara: polling dilanjutkan sampai batas attempts.
        })
    }, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [current.id, diarization?.status, refreshTranscriptDetail])

  // Job ringkasan juga berjalan di server; polling sampai status final.
  useEffect(() => {
    if (summary?.status !== 'PROCESSING') return

    let cancelled = false
    let attempts = 0
    const maxAttempts = MAX_POLL_ATTEMPTS
    const timer = window.setInterval(() => {
      if (cancelled) return
      attempts += 1
      if (attempts > maxAttempts) {
        window.clearInterval(timer)
        setSummaryNotice('Status ringkasan belum final. Tekan Refresh untuk memeriksa ulang.')
        return
      }

      void fetchSummary(current.id)
        .then((detail) => {
          if (cancelled) return
          setSummary(detail)
          if (detail.status !== 'PROCESSING') {
            window.clearInterval(timer)
            if (detail.status === 'COMPLETED') {
              setSummaryNotice('Ringkasan selesai dibuat dari transkrip tersimpan.')
            }
          }
        })
        .catch(() => {
          // Gangguan sementara: polling dilanjutkan sampai batas attempts.
        })
    }, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [current.id, summary?.status])

  // Job ekstraksi action items juga berjalan di server; polling sampai final.
  useEffect(() => {
    if (actionDetail?.status !== 'PROCESSING') return

    let cancelled = false
    let attempts = 0
    const maxAttempts = MAX_POLL_ATTEMPTS
    const timer = window.setInterval(() => {
      if (cancelled) return
      attempts += 1
      if (attempts > maxAttempts) {
        window.clearInterval(timer)
        setActionNotice('Status action items belum final. Tekan Refresh untuk memeriksa ulang.')
        return
      }

      void fetchActionItems(current.id)
        .then((detail) => {
          if (cancelled) return
          setActionDetail(detail)
          if (detail.status !== 'PROCESSING') {
            window.clearInterval(timer)
            if (detail.status === 'COMPLETED') {
              setActionNotice('Action items selesai diekstrak dari transkrip tersimpan.')
            }
          }
        })
        .catch(() => {
          // Gangguan sementara: polling dilanjutkan sampai batas attempts.
        })
    }, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [current.id, actionDetail?.status])

  async function handleDelete() {
    if (!window.confirm('Hapus rekaman ini dari server? Tindakan ini tidak dapat dibatalkan.')) {
      return
    }

    setDeleting(true)
    setDeleteError('')

    try {
      await deleteRecording(current.id)
      const updated: Meeting = {
        ...current,
        status: 'PENDING',
        has_recording: false,
        recording: null,
      }
      setCurrent(updated)
      setTranscription(null)
      setTranscriptError('')
      setTranscriptNotice('')
      setDiarization(null)
      setDiarizationError('')
      setDiarizationNotice('')
      setSummary(null)
      setSummaryError('')
      setSummaryNotice('')
      setActionDetail(null)
      setActionError('')
      setActionNotice('Action items ikut dihapus karena rekaman/transkripnya tidak ada lagi.')
      setEditingItemId(null)
      setNotice('Rekaman berhasil dihapus. Anda dapat merekam atau mengunggah lagi.')
      onDeleted(updated)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Gagal menghapus rekaman.')
    } finally {
      setDeleting(false)
    }
  }

  async function handleTranscribe() {
    if (!asset || isProcessing || transcribing) return

    setTranscribing(true)
    setTranscriptError('')
    setTranscriptNotice('')

    try {
      const result = await startTranscription(current.id)
      setTranscription(result)
      setCurrent((previous) => ({ ...previous, status: result.meeting_status }))
      setTranscriptNotice(
        result.status === 'PROCESSING'
          ? 'Transkripsi sedang berjalan. Status akan diperbarui otomatis.'
          : 'Transkripsi selesai.',
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Gagal memulai transkripsi.'
      setTranscriptError(message)
      // Ambil ulang status agar error 409 (duplikat) tetap menjelaskan kondisi.
      try {
        setTranscription(await fetchTranscription(current.id))
      } catch {
        // Pesan error utama sudah cukup jelas.
      }
    } finally {
      setTranscribing(false)
    }
  }

  async function handleRefreshTranscription() {
    setTranscriptError('')
    setTranscriptLoading(true)

    try {
      const detail = await fetchTranscription(current.id)
      setTranscription(detail)
      if (detail.status !== 'PROCESSING') void syncMeeting(current.id)
    } catch (error) {
      setTranscriptError(
        error instanceof Error ? error.message : 'Gagal menyegarkan status transkripsi.',
      )
    } finally {
      setTranscriptLoading(false)
    }
  }

  async function handleDeleteTranscript() {
    if (!window.confirm('Hapus transkrip ini? Rekaman audio tidak akan dihapus.')) return

    setDeletingTranscript(true)
    setTranscriptError('')
    setTranscriptNotice('')

    try {
      const result = await deleteTranscript(current.id)
      await refreshTranscriptDetail(current.id)
      setDiarization(await fetchDiarization(current.id))
      setTranscriptNotice(
        `Transkrip dihapus (${result.segments_deleted} segmen). Audio tetap tersimpan.`,
      )
      setDiarizationNotice('Diarisasi ikut dibatalkan karena transkrip dihapus.')
      setSummary(null)
      setSummaryError('')
      setSummaryNotice('Ringkasan ikut dihapus karena transkripnya tidak ada lagi.')
      setActionDetail(null)
      setActionError('')
      setActionNotice('Action items ikut dihapus karena transkripnya tidak ada lagi.')
      setEditingItemId(null)
      void syncMeeting(current.id)
    } catch (error) {
      setTranscriptError(
        error instanceof Error ? error.message : 'Gagal menghapus transkrip.',
      )
    } finally {
      setDeletingTranscript(false)
    }
  }

  async function handleDiarize() {
    if (!asset || !showTranscript || segments.length === 0 || diarizing || isDiarizationProcessing) {
      return
    }

    setDiarizing(true)
    setDiarizationError('')
    setDiarizationNotice('')

    try {
      const result = await startDiarization(current.id)
      setDiarization(result)
      if (result.status === 'PROCESSING') {
        setDiarizationNotice('Diarisasi sedang berjalan. Status akan diperbarui otomatis.')
      } else {
        await refreshTranscriptDetail(current.id)
        setDiarizationNotice('Diarisasi selesai. Label speaker ditampilkan pada segmen.')
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Gagal memulai diarisasi.'
      setDiarizationError(message)
      try {
        setDiarization(await fetchDiarization(current.id))
      } catch {
        // Pesan error utama sudah cukup jelas.
      }
    } finally {
      setDiarizing(false)
    }
  }

  async function handleRefreshDiarization() {
    setDiarizationError('')
    setDiarizationLoading(true)

    try {
      const detail = await fetchDiarization(current.id)
      setDiarization(detail)
      if (detail.status !== 'PROCESSING') await refreshTranscriptDetail(current.id)
      if (detail.status === 'COMPLETED') {
        setDiarizationNotice(
          `${detail.speakers.length} speaker dikenali (${detail.mapped_segments} segmen dipetakan).`,
        )
      }
    } catch (error) {
      setDiarizationError(
        error instanceof Error ? error.message : 'Gagal menyegarkan status diarisasi.',
      )
    } finally {
      setDiarizationLoading(false)
    }
  }

  async function handleDeleteDiarization() {
    if (!window.confirm('Hapus hasil diarisasi? Transkrip dan rekaman audio tidak akan dihapus.')) {
      return
    }

    setDeletingDiarization(true)
    setDiarizationError('')
    setDiarizationNotice('')

    try {
      const result = await deleteDiarization(current.id)
      await refreshTranscriptDetail(current.id)
      setDiarization(await fetchDiarization(current.id))
      setDiarizationNotice(
        `Diarisasi dihapus (${result.speakers_deleted} speaker, ${result.segments_unassigned} segmen dilepaskan).`,
      )
    } catch (error) {
      setDiarizationError(
        error instanceof Error ? error.message : 'Gagal menghapus hasil diarisasi.',
      )
    } finally {
      setDeletingDiarization(false)
    }
  }

  async function handleGenerateSummary() {
    if (!asset || !showTranscript || segments.length === 0 || summarizing || isSummaryProcessing) {
      return
    }

    setSummarizing(true)
    setSummaryError('')
    setSummaryNotice('')

    try {
      const result = await startSummary(current.id)
      setSummary(result)
      if (result.status === 'PROCESSING') {
        setSummaryNotice('Ringkasan sedang dibuat. Status akan diperbarui otomatis.')
      } else {
        setSummaryNotice('Ringkasan selesai dibuat dari transkrip tersimpan.')
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Gagal memulai ringkasan.'
      setSummaryError(message)
      try {
        setSummary(await fetchSummary(current.id))
      } catch {
        // Pesan error utama sudah cukup jelas.
      }
    } finally {
      setSummarizing(false)
    }
  }

  async function handleRefreshSummary() {
    setSummaryError('')
    setSummaryLoading(true)

    try {
      const detail = await fetchSummary(current.id)
      setSummary(detail)
      if (detail.status !== 'PROCESSING') setSummaryNotice('Status ringkasan disegarkan.')
    } catch (error) {
      setSummaryError(
        error instanceof Error ? error.message : 'Gagal menyegarkan status ringkasan.',
      )
    } finally {
      setSummaryLoading(false)
    }
  }

  async function handleDeleteSummary() {
    if (!window.confirm('Hapus ringkasan ini? Transkrip dan rekaman audio tidak akan dihapus.')) {
      return
    }

    setDeletingSummary(true)
    setSummaryError('')
    setSummaryNotice('')

    try {
      const result = await deleteSummary(current.id)
      setSummary(await fetchSummary(current.id))
      setSummaryNotice(result.detail)
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : 'Gagal menghapus ringkasan.')
    } finally {
      setDeletingSummary(false)
    }
  }

  async function handleGenerateActionItems() {
    if (!asset || !showTranscript || segments.length === 0 || extracting || isActionItemsProcessing) {
      return
    }

    setExtracting(true)
    setActionError('')
    setActionNotice('')
    setEditingItemId(null)

    try {
      const result = await startActionItems(current.id)
      setActionDetail(result)
      setActionNotice(
        result.status === 'PROCESSING'
          ? 'Action items sedang diekstrak. Status akan diperbarui otomatis.'
          : 'Action items selesai diekstrak dari transkrip tersimpan.',
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Gagal mengekstrak action items.'
      setActionError(message)
      try {
        setActionDetail(await fetchActionItems(current.id))
      } catch {
        // Pesan error utama sudah cukup jelas.
      }
    } finally {
      setExtracting(false)
    }
  }

  async function handleRefreshActionItems() {
    setActionError('')
    setActionLoading(true)

    try {
      const detail = await fetchActionItems(current.id)
      setActionDetail(detail)
      if (detail.status !== 'PROCESSING') setActionNotice('Status action items disegarkan.')
    } catch (error) {
      setActionError(
        error instanceof Error ? error.message : 'Gagal menyegarkan action items.',
      )
    } finally {
      setActionLoading(false)
    }
  }

  async function handleDeleteActionItems() {
    if (!window.confirm('Hapus seluruh action items? Transkrip dan rekaman audio tidak akan dihapus.')) {
      return
    }

    setDeletingActionItems(true)
    setActionError('')
    setActionNotice('')
    setEditingItemId(null)

    try {
      const result = await deleteActionItems(current.id)
      setActionDetail(await fetchActionItems(current.id))
      setActionNotice(result.detail)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Gagal menghapus action items.')
    } finally {
      setDeletingActionItems(false)
    }
  }

  function handleStartEdit(item: ActionItem) {
    setEditingItemId(item.id)
    setActionDraft({
      title: item.title,
      description: item.description,
      assignee_speaker_id: item.assignee_speaker_id,
      assignee_text: item.assignee_text ?? '',
      deadline_text: item.deadline_text ?? '',
      due_date: item.due_date,
      status: item.status,
    })
    setActionError('')
  }

  async function handleSaveActionItem() {
    if (!editingItemId) return

    setSavingActionItem(true)
    setActionError('')

    try {
      const body: ActionItemUpdate = {
        ...actionDraft,
        title: (actionDraft.title ?? '').trim(),
        description: actionDraft.description ?? '',
        assignee_text: actionDraft.assignee_text?.trim() || null,
        deadline_text: actionDraft.deadline_text?.trim() || null,
        due_date: actionDraft.due_date || null,
      }
      const updated = await updateActionItem(current.id, editingItemId, body)
      setActionDetail((previous) =>
        previous
          ? {
              ...previous,
              items: previous.items.map((item) => (item.id === updated.id ? updated : item)),
            }
          : previous,
      )
      setEditingItemId(null)
      setActionNotice('Action item disimpan. Perubahan manual dipertahankan saat regenerasi.')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Gagal menyimpan action item.')
    } finally {
      setSavingActionItem(false)
    }
  }

  async function handleActionStatus(item: ActionItem, nextStatus: ActionItemStatus) {
    if (item.status === nextStatus) return
    setActionError('')

    try {
      const updated = await updateActionItem(current.id, item.id, { status: nextStatus })
      setActionDetail((previous) =>
        previous
          ? {
              ...previous,
              items: previous.items.map((entry) => (entry.id === updated.id ? updated : entry)),
            }
          : previous,
      )
      setActionNotice(`Status action item diubah menjadi ${nextStatus}.`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Gagal mengubah status action item.')
    }
  }

  async function handleDeleteActionItem(item: ActionItem) {
    if (!window.confirm(`Hapus action item "${item.title}"?`)) return

    setActionError('')
    try {
      await deleteActionItem(current.id, item.id)
      setActionDetail((previous) =>
        previous
          ? { ...previous, items: previous.items.filter((entry) => entry.id !== item.id) }
          : previous,
      )
      if (editingItemId === item.id) setEditingItemId(null)
      setActionNotice('Action item dihapus.')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Gagal menghapus action item.')
    }
  }

  const asset = current.recording
  const isProcessing =
    transcription?.status === 'PROCESSING' || current.status === 'TRANSCRIBING'
  const segments = transcription?.segments ?? []
  // Hanya speaker milik meeting ini yang boleh dipilih pada tiap segmen.
  const speakers = diarization?.speakers ?? []
  const showTranscript = transcription !== null && transcription.status !== 'NOT_STARTED'
  const isDiarizationProcessing =
    diarization?.status === 'PROCESSING' || current.status === 'DIARIZING'
  const showDiarization = diarization !== null && diarization.status !== 'NOT_STARTED'
  const isSummaryProcessing =
    summary?.status === 'PROCESSING' || summarizing || current.status === 'SUMMARIZING'
  const hasSummaryContent = Boolean(
    summary && (summary.overview || summary.topics.length > 0 || summary.decisions.length > 0),
  )
  const showSummary = summary !== null && (summary.status !== 'NOT_STARTED' || hasSummaryContent)
  const isActionItemsProcessing =
    actionDetail?.status === 'PROCESSING' || extracting
  const hasActionItemsContent = Boolean(actionDetail && actionDetail.items.length > 0)
  const showActionItems =
    actionDetail !== null && (actionDetail.status !== 'NOT_STARTED' || hasActionItemsContent)

  return (
    <section className="new-meeting">
      <button className="button button--ghost" type="button" onClick={onBack}>
        ← Kembali ke Dashboard
      </button>

      <div className="panel">
        {justSaved && (
          <div className="success-banner" role="status">
            ✅ Rekaman berhasil disimpan ke server.
          </div>
        )}
        {notice && <div className="success-banner" role="status">{notice}</div>}

        <div className="panel__header">
          <div>
            <h2>{current.title}</h2>
            <p className="muted">Status: <StatusBadge status={current.status} /></p>
          </div>
          <span className="meeting-id">ID: {current.id.slice(0, 8)}…</span>
        </div>

        <div className="preview export-panel">
          <h3>Ekspor Notulen</h3>
          <p className="muted">
            Unduh ringkasan, keputusan, action items, dan transkrip yang sudah tersimpan.
            Ekspor tidak menjalankan AI baru dan tidak memerlukan file audio.
          </p>
          <div className="button-row">
            <button
              className="button button--primary"
              type="button"
              onClick={() => void handleExport('txt')}
              disabled={exporting !== null}
            >
              {exporting === 'txt' ? 'Menyiapkan…' : 'Unduh TXT'}
            </button>
            <button
              className="button button--ghost"
              type="button"
              onClick={() => void handleExport('pdf')}
              disabled={exporting !== null}
            >
              {exporting === 'pdf' ? 'Menyiapkan…' : 'Unduh PDF'}
            </button>
          </div>
          {exportError && <p className="inline-error" role="alert">{exportError}</p>}
        </div>

        {asset ? (
          <div className="preview">
            <h3>Rekaman</h3>
            <audio
              ref={audioRef}
              controls
              preload="metadata"
              src={playbackUrl(asset)}
              onLoadedMetadata={() => setAudioUnavailable(false)}
              onError={() => setAudioUnavailable(true)}
            />
            {audioUnavailable && (
              <p className="notice" role="status">
                Pemutar audio tidak dapat memuat rekaman ini. Timestamp transkrip tetap
                bisa dibaca, tetapi tombol putar dari segmen tidak aktif.
              </p>
            )}
            <dl className="metadata">
              <div><dt>Durasi</dt><dd>{formatDuration(asset.duration_seconds)}</dd></div>
              <div><dt>Ukuran</dt><dd>{formatBytes(asset.file_size_bytes)}</dd></div>
              <div><dt>Format</dt><dd>{asset.mime_type}</dd></div>
              <div>
                <dt>Diunggah</dt>
                <dd>{new Date(asset.created_at).toLocaleString('id-ID')}</dd>
              </div>
            </dl>

            <div className="button-row">
              <button
                className="button button--danger"
                type="button"
                onClick={() => void handleDelete()}
                disabled={deleting || isProcessing || isDiarizationProcessing}
              >
                {deleting ? 'Menghapus…' : 'Delete Recording'}
              </button>
            </div>
            {deleteError && <p className="inline-error" role="alert">{deleteError}</p>}
          </div>
        ) : (
          <div className="preview">
            <p className="muted">Meeting ini belum memiliki rekaman.</p>
            <div className="button-row">
              <button className="button button--primary" type="button" onClick={onAddRecording}>
                + Tambah Rekaman
              </button>
            </div>
          </div>
        )}

        <div className="preview transcription">
          <h3>Transkripsi</h3>
          <p className="muted">
            Ubah rekaman menjadi teks bertimestamp. Pastikan rekaman dibuat dengan
            sepengetahuan dan persetujuan semua peserta.
          </p>

          <div className="button-row">
            <button
              className="button button--primary"
              type="button"
              onClick={() => void handleTranscribe()}
              disabled={!asset || transcribing || isProcessing || deletingTranscript}
            >
              {transcribing || isProcessing ? 'Memproses…' : 'Transcribe'}
            </button>
            <button
              className="button button--ghost"
              type="button"
              onClick={() => void handleRefreshTranscription()}
              disabled={transcriptLoading}
            >
              {transcriptLoading ? 'Memuat…' : '↻ Refresh'}
            </button>
            {showTranscript && segments.length > 0 && (
              <button
                className="button button--danger"
                type="button"
                onClick={() => void handleDeleteTranscript()}
                disabled={deletingTranscript || isProcessing}
              >
                {deletingTranscript ? 'Menghapus…' : 'Hapus Transkrip'}
              </button>
            )}
          </div>

          {!asset && <p className="muted">Tambahkan rekaman terlebih dahulu untuk dapat ditranskripsi.</p>}
          {isProcessing && (
            <p className="notice" role="status">
              ⏳ Transkripsi sedang diproses di background. Silakan tunggu atau tekan Refresh.
            </p>
          )}
          {transcriptNotice && <div className="success-banner" role="status">{transcriptNotice}</div>}
          {transcriptError && <p className="inline-error" role="alert">{transcriptError}</p>}

          {showTranscript && (
            <>
              <dl className="metadata">
                <div>
                  <dt>Status transkripsi</dt>
                  <dd><StatusBadge status={transcription.status} /></dd>
                </div>
                <div>
                  <dt>Provider</dt>
                  <dd>{transcription.provider ?? '—'}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>{transcription.model ?? '—'}</dd>
                </div>
                <div>
                  <dt>Segmen</dt>
                  <dd>{segments.length}</dd>
                </div>
              </dl>

              {transcription.error && (
                <p className="inline-error" role="alert">
                  Transkripsi gagal: {transcription.error}
                </p>
              )}

              <TranscriptEditor
                segments={segments}
                speakers={speakers}
                hasTimestamps={transcription.has_timestamps}
                disabled={isProcessing || isDiarizationProcessing || deletingTranscript}
                onSeek={handleSeek}
                onSegmentTextSaved={handleSegmentTextSaved}
                onSegmentSpeakerSaved={handleSegmentSpeakerSaved}
              />
            </>
          )}
        </div>

        <div className="preview diarization">
          <h3>Diarisasi Pembicara</h3>
          <p className="muted">
            Tandai giliran pembicara secara anonim (Speaker 1, Speaker 2, …).
            Tidak ada identitas dunia nyata yang ditebak. Rekaman tetap harus
            dibuat dengan sepengetahuan dan persetujuan peserta.
          </p>

          <div className="button-row">
            {showTranscript && segments.length > 0 && asset && (
              <button
                className="button button--primary"
                type="button"
                onClick={() => void handleDiarize()}
                disabled={
                  diarizing ||
                  isProcessing ||
                  isDiarizationProcessing ||
                  deletingDiarization
                }
              >
                {diarizing || isDiarizationProcessing ? 'Memproses…' : 'Diarize Speakers'}
              </button>
            )}
            <button
              className="button button--ghost"
              type="button"
              onClick={() => void handleRefreshDiarization()}
              disabled={diarizationLoading}
            >
              {diarizationLoading ? 'Memuat…' : '↻ Refresh'}
            </button>
            {showDiarization && diarization?.speakers.length ? (
              <button
                className="button button--danger"
                type="button"
                onClick={() => void handleDeleteDiarization()}
                disabled={deletingDiarization || isDiarizationProcessing}
              >
                {deletingDiarization ? 'Menghapus…' : 'Hapus Diarisasi'}
              </button>
            ) : null}
          </div>

          {!asset && <p className="muted">Tambahkan rekaman terlebih dahulu untuk dapat diarisasi.</p>}
          {asset && !showTranscript && (
            <p className="muted">Selesaikan transkripsi terlebih dahulu sebelum diarisasi.</p>
          )}
          {isDiarizationProcessing && (
            <p className="notice" role="status">
              ⏳ Diarisasi sedang diproses di background. Silakan tunggu atau tekan Refresh.
            </p>
          )}
          {diarizationNotice && <div className="success-banner" role="status">{diarizationNotice}</div>}
          {diarizationError && <p className="inline-error" role="alert">{diarizationError}</p>}

          {diarization && showDiarization && (
            <>
              <dl className="metadata">
                <div>
                  <dt>Status diarisasi</dt>
                  <dd><StatusBadge status={diarization.status} /></dd>
                </div>
                <div>
                  <dt>Provider</dt>
                  <dd>{diarization.provider ?? '—'}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>{diarization.model ?? '—'}</dd>
                </div>
                <div>
                  <dt>Speaker</dt>
                  <dd>{diarization.speakers.length}</dd>
                </div>
                <div>
                  <dt>Segmen dipetakan</dt>
                  <dd>{diarization.mapped_segments}</dd>
                </div>
              </dl>

              {diarization.is_mock && (
                <p className="notice" role="status">
                  [MOCK] Provider simulasi sedang dipakai. Ini bukan hasil diarisasi sungguhan.
                </p>
              )}
              {diarization.error && (
                <p className="inline-error" role="alert">
                  Diarisasi gagal: {diarization.error}
                </p>
              )}
              <p className="muted">
                Nama di bawah ini murni catatan Anda, bukan hasil pengenalan identitas.
                Label `Speaker 1`, `Speaker 2`, … tidak dapat diubah.
              </p>
              <SpeakerManager
                speakers={speakers}
                disabled={isProcessing || isDiarizationProcessing || deletingDiarization}
                onSpeakerUpdated={handleSpeakerUpdated}
              />
              {segments.some((segment) => !segment.speaker_label) && (
                <p className="muted">
                  Speaker ? berarti tidak ada overlap yang cukup andal; segmen sengaja
                  tidak diberi label rekaan.
                </p>
              )}
            </>
          )}
        </div>

        <div className="preview summary">
          <h3>AI Summary</h3>
          <p className="muted">
            Ringkasan dibuat hanya dari transkrip yang tersimpan: overview, topik, dan
            keputusan eksplisit. Tidak ada action item, assignee, atau deadline.
          </p>

          <div className="button-row">
            {showTranscript && segments.length > 0 && asset && (
              <button
                className="button button--primary"
                type="button"
                onClick={() => void handleGenerateSummary()}
                disabled={summarizing || isSummaryProcessing || deletingSummary}
              >
                {summarizing || isSummaryProcessing
                  ? 'Memproses…'
                  : hasSummaryContent
                    ? 'Regenerate Summary'
                    : 'Generate Summary'}
              </button>
            )}
            <button
              className="button button--ghost"
              type="button"
              onClick={() => void handleRefreshSummary()}
              disabled={summaryLoading}
            >
              {summaryLoading ? 'Memuat…' : '↻ Refresh'}
            </button>
            {hasSummaryContent && (
              <button
                className="button button--danger"
                type="button"
                onClick={() => void handleDeleteSummary()}
                disabled={deletingSummary || isSummaryProcessing}
              >
                {deletingSummary ? 'Menghapus…' : 'Hapus Ringkasan'}
              </button>
            )}
          </div>

          {!asset && <p className="muted">Tambahkan rekaman terlebih dahulu untuk dapat diringkas.</p>}
          {asset && !showTranscript && (
            <p className="muted">Selesaikan transkripsi terlebih dahulu sebelum membuat ringkasan.</p>
          )}
          {isSummaryProcessing && (
            <p className="notice" role="status">
              ⏳ Ringkasan sedang diproses di background. Tekan Refresh bila perlu.
            </p>
          )}
          {summaryNotice && <div className="success-banner" role="status">{summaryNotice}</div>}
          {summaryError && <p className="inline-error" role="alert">{summaryError}</p>}

          {showSummary && (
            <>
              <dl className="metadata">
                <div>
                  <dt>Status ringkasan</dt>
                  <dd><StatusBadge status={summary.status} /></dd>
                </div>
                <div>
                  <dt>Provider</dt>
                  <dd>{summary.provider ?? '—'}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>{summary.model ?? '—'}</dd>
                </div>
                <div>
                  <dt>Topik</dt>
                  <dd>{summary.topics.length}</dd>
                </div>
                <div>
                  <dt>Keputusan</dt>
                  <dd>{summary.decisions.length}</dd>
                </div>
              </dl>

              {summary.is_mock && (
                <p className="notice" role="status">
                  [MOCK] Provider simulasi sedang dipakai. Ini bukan ringkasan AI sungguhan.
                </p>
              )}
              {summary.error && (
                <p className="inline-error" role="alert">
                  Ringkasan gagal: {summary.error}
                </p>
              )}

              {hasSummaryContent && (
                <div className="summary-content">
                  <div>
                    <h4>Overview</h4>
                    <p>{summary.overview || '—'}</p>
                  </div>
                  <div>
                    <h4>Topics</h4>
                    {summary.topics.length ? (
                      <ul className="summary-list">{summary.topics.map(renderTopic)}</ul>
                    ) : (
                      <p className="muted">Tidak ada topik yang tercatat dari transkrip.</p>
                    )}
                  </div>
                  <div>
                    <h4>Decisions</h4>
                    {summary.decisions.length ? (
                      <ul className="summary-list">{summary.decisions.map(renderDecision)}</ul>
                    ) : (
                      <p className="muted">
                        Tidak ada keputusan eksplisit yang tercatat dari transkrip.
                      </p>
                    )}
                  </div>
                  <p className="muted">
                    Tombol waktu di samping item memutar cuplikan rekaman asli. Jika regenerasi
                    gagal, ringkasan sebelumnya tetap ditampilkan.
                  </p>
                </div>
              )}
            </>
          )}
        </div>

        <div className="preview action-items">
          <h3>Action Items</h3>
          <p className="muted">
            Tugas/tindak lanjut diekstrak hanya dari pernyataan eksplisit di transkrip.
            Penanggung jawab dan deadline tidak dikarang. Hasil AI dapat Anda edit,
            konfirmasi, atau hapus.
          </p>

          <div className="button-row">
            {showTranscript && segments.length > 0 && asset && (
              <button
                className="button button--primary"
                type="button"
                onClick={() => void handleGenerateActionItems()}
                disabled={extracting || isActionItemsProcessing || deletingActionItems}
              >
                {extracting || isActionItemsProcessing
                  ? 'Memproses…'
                  : hasActionItemsContent
                    ? 'Regenerate Action Items'
                    : 'Generate Action Items'}
              </button>
            )}
            <button
              className="button button--ghost"
              type="button"
              onClick={() => void handleRefreshActionItems()}
              disabled={actionLoading}
            >
              {actionLoading ? 'Memuat…' : '↻ Refresh'}
            </button>
            {hasActionItemsContent && (
              <button
                className="button button--danger"
                type="button"
                onClick={() => void handleDeleteActionItems()}
                disabled={deletingActionItems || isActionItemsProcessing}
              >
                {deletingActionItems ? 'Menghapus…' : 'Hapus Semua Action Items'}
              </button>
            )}
          </div>

          {!asset && <p className="muted">Tambahkan rekaman terlebih dahulu sebelum mengekstrak action items.</p>}
          {asset && !showTranscript && (
            <p className="muted">Selesaikan transkripsi terlebih dahulu sebelum mengekstrak action items.</p>
          )}
          {isActionItemsProcessing && (
            <p className="notice" role="status">
              ⏳ Ekstraksi action items berjalan di background. Tekan Refresh bila perlu.
            </p>
          )}
          {actionNotice && <div className="success-banner" role="status">{actionNotice}</div>}
          {actionError && <p className="inline-error" role="alert">{actionError}</p>}

          {showActionItems && actionDetail && (
            <>
              <dl className="metadata">
                <div>
                  <dt>Status ekstraksi</dt>
                  <dd><StatusBadge status={actionDetail.status} /></dd>
                </div>
                <div>
                  <dt>Provider</dt>
                  <dd>{actionDetail.provider ?? '—'}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>{actionDetail.model ?? '—'}</dd>
                </div>
                <div>
                  <dt>Action items</dt>
                  <dd>{actionDetail.items.length}</dd>
                </div>
              </dl>

              {actionDetail.is_mock && (
                <p className="notice" role="status">
                  [MOCK] Provider simulasi sedang dipakai. Ini bukan ekstraksi AI sungguhan.
                </p>
              )}
              {actionDetail.error && (
                <p className="inline-error" role="alert">
                  Ekstraksi gagal: {actionDetail.error}
                </p>
              )}

              {!hasActionItemsContent && actionDetail.status === 'COMPLETED' && (
                <p className="muted">
                  Tidak ada action item yang benar-benar didukung transkrip. Ini hasil yang valid.
                </p>
              )}
              {!hasActionItemsContent && actionDetail.status === 'NOT_STARTED' && (
                <p className="muted">Action items belum pernah diekstrak untuk meeting ini.</p>
              )}

              {hasActionItemsContent && (
                <ul className="action-list">
                  {actionDetail.items.map((item) => {
                    const speaker = actionDetail.speakers.find(
                      (option) => option.id === item.assignee_speaker_id,
                    )
                    const assignee = speaker?.label ?? item.assignee_text
                    const isEditing = editingItemId === item.id

                    return (
                      <li key={item.id} className="action-item">
                        <div className="action-item__head">
                          <strong>{item.title}</strong>
                          <div className="action-item__tools">
                            <StatusBadge status={item.status} />
                            {renderSourceRef(item, `action-ref-${item.id}`)}
                          </div>
                        </div>

                        {item.description && <p className="action-item__description">{item.description}</p>}
                        <p className="action-item__meta">
                          Penanggung jawab: {assignee ?? '—'}
                          {item.deadline_text && ` · Deadline: ${item.deadline_text}`}
                          {item.due_date && ` (${item.due_date})`}
                          {item.is_manually_edited && ' · ✎ diedit manual'}
                        </p>

                        {isEditing ? (
                          <div className="action-form">
                            <label>
                              Judul
                              <input
                                className="speaker-manager__input"
                                type="text"
                                value={actionDraft.title ?? ''}
                                onChange={(event) =>
                                  setActionDraft((previous) => ({
                                    ...previous,
                                    title: event.target.value,
                                  }))
                                }
                              />
                            </label>
                            <label>
                              Deskripsi
                              <textarea
                                className="transcript-segment__input"
                                rows={2}
                                value={actionDraft.description ?? ''}
                                onChange={(event) =>
                                  setActionDraft((previous) => ({
                                    ...previous,
                                    description: event.target.value,
                                  }))
                                }
                              />
                            </label>
                            <label>
                              Penanggung jawab (speaker meeting ini)
                              <select
                                className="transcript-segment__select"
                                value={actionDraft.assignee_speaker_id ?? ''}
                                onChange={(event) =>
                                  setActionDraft((previous) => ({
                                    ...previous,
                                    assignee_speaker_id: event.target.value || null,
                                  }))
                                }
                              >
                                <option value="">Tidak ditentukan</option>
                                {actionDetail.speakers.map((option) => (
                                  <option key={option.id} value={option.id}>{option.label}</option>
                                ))}
                              </select>
                            </label>
                            <label>
                              Nama/keterangan penanggung jawab (jika disebut eksplisit)
                              <input
                                className="speaker-manager__input"
                                type="text"
                                value={actionDraft.assignee_text ?? ''}
                                onChange={(event) =>
                                  setActionDraft((previous) => ({
                                    ...previous,
                                    assignee_text: event.target.value,
                                  }))
                                }
                              />
                            </label>
                            <label>
                              Frasa deadline asli
                              <input
                                className="speaker-manager__input"
                                type="text"
                                value={actionDraft.deadline_text ?? ''}
                                onChange={(event) =>
                                  setActionDraft((previous) => ({
                                    ...previous,
                                    deadline_text: event.target.value,
                                  }))
                                }
                              />
                            </label>
                            <label>
                              Tanggal (opsional, jika tidak ambigu)
                              <input
                                className="speaker-manager__input"
                                type="date"
                                value={actionDraft.due_date ?? ''}
                                onChange={(event) =>
                                  setActionDraft((previous) => ({
                                    ...previous,
                                    due_date: event.target.value || null,
                                  }))
                                }
                              />
                            </label>
                            <label>
                              Status
                              <select
                                className="transcript-segment__select"
                                value={actionDraft.status ?? 'OPEN'}
                                onChange={(event) =>
                                  setActionDraft((previous) => ({
                                    ...previous,
                                    status: event.target.value as ActionItemStatus,
                                  }))
                                }
                              >
                                <option value="OPEN">OPEN</option>
                                <option value="COMPLETED">COMPLETED</option>
                                <option value="CANCELLED">CANCELLED</option>
                              </select>
                            </label>
                            <div className="button-row">
                              <button
                                className="button button--primary button--small"
                                type="button"
                                onClick={() => void handleSaveActionItem()}
                                disabled={savingActionItem || !(actionDraft.title ?? '').trim()}
                              >
                                {savingActionItem ? 'Menyimpan…' : 'Simpan'}
                              </button>
                              <button
                                className="button button--ghost button--small"
                                type="button"
                                onClick={() => setEditingItemId(null)}
                                disabled={savingActionItem}
                              >
                                Batal
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="button-row action-item__actions">
                            <button
                              className="button button--ghost button--small"
                              type="button"
                              onClick={() => handleStartEdit(item)}
                            >
                              Edit
                            </button>
                            {item.status !== 'COMPLETED' && (
                              <button
                                className="button button--small"
                                type="button"
                                onClick={() => void handleActionStatus(item, 'COMPLETED')}
                              >
                                ✓ Selesai
                              </button>
                            )}
                            {item.status !== 'CANCELLED' && (
                              <button
                                className="button button--small"
                                type="button"
                                onClick={() => void handleActionStatus(item, 'CANCELLED')}
                              >
                                Batalkan
                              </button>
                            )}
                            {item.status !== 'OPEN' && (
                              <button
                                className="button button--small"
                                type="button"
                                onClick={() => void handleActionStatus(item, 'OPEN')}
                              >
                                Buka lagi
                              </button>
                            )}
                            <button
                              className="button button--danger button--small"
                              type="button"
                              onClick={() => void handleDeleteActionItem(item)}
                            >
                              Hapus
                            </button>
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}

              <p className="muted">
                Tombol waktu memutar cuplikan asli pada pemutar yang sama. Jika regenerasi
                gagal, action items lama tetap tersimpan. Item yang pernah Anda edit tidak
                ditimpa atau dihapus oleh regenerasi.
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

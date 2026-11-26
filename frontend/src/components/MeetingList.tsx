// Daftar meeting. Menampilkan placeholder ramah saat database masih kosong.

import { playbackUrl } from '../api'
import type { Meeting } from '../types'
import { formatBytes, formatDuration } from '../utils/format'
import { StatusBadge } from './StatusBadge'

interface MeetingListProps {
  meetings: Meeting[]
  onOpen?: (meeting: Meeting) => void
}

export function MeetingList({ meetings, onOpen }: MeetingListProps) {
  if (meetings.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon" aria-hidden="true">📭</div>
        <h2>Belum ada meeting</h2>
        <p>
          Saat ini database masih kosong. Klik <strong>New Meeting</strong> untuk
          membuat pertemuan pertama Anda.
        </p>
      </div>
    )
  }

  return (
    <div className="meeting-list">
      {meetings.map((meeting) => (
        <article className="meeting-card" key={meeting.id}>
          <div className="meeting-card__header">
            {onOpen ? (
              <button className="meeting-card__title" type="button" onClick={() => onOpen(meeting)}>
                {meeting.title}
              </button>
            ) : (
              <h3>{meeting.title}</h3>
            )}
            <StatusBadge status={meeting.status} />
          </div>

          <p className="meeting-card__meta">
            Dibuat {new Date(meeting.created_at).toLocaleString('id-ID')}
          </p>

          {meeting.has_recording && meeting.recording ? (
            <div className="meeting-card__audio">
              <span className="meeting-card__audio-label">🎙️ Rekaman tersimpan</span>
              <span>
                {formatDuration(meeting.recording.duration_seconds)} ·{' '}
                {formatBytes(meeting.recording.file_size_bytes)} ·{' '}
                {meeting.recording.mime_type}
              </span>
              <audio controls preload="none" src={playbackUrl(meeting.recording)} />
            </div>
          ) : (
            <p className="meeting-card__meta">Belum ada rekaman.</p>
          )}
        </article>
      ))}
    </div>
  )
}
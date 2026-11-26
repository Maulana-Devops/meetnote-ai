// Daftar segmen transkrip yang sudah diurutkan backend. Komponen ini hanya
// mengatur layout daftar; logika edit ada di TranscriptSegmentItem.

import type { SpeakerSummary, TranscriptSegment } from '../types'
import { TranscriptSegmentItem } from './TranscriptSegmentItem'

interface TranscriptEditorProps {
  segments: TranscriptSegment[]
  speakers: SpeakerSummary[]
  hasTimestamps: boolean
  disabled: boolean
  onSeek: (seconds: number) => void
  onSegmentTextSaved: (updated: TranscriptSegment) => void
  onSegmentSpeakerSaved: (updated: TranscriptSegment) => void
}

export function TranscriptEditor({
  segments,
  speakers,
  hasTimestamps,
  disabled,
  onSeek,
  onSegmentTextSaved,
  onSegmentSpeakerSaved,
}: TranscriptEditorProps) {
  if (segments.length === 0) {
    return <p className="muted">Belum ada segmen transkrip.</p>
  }

  return (
    <>
      <p className="muted">
        Klik timestamp untuk memutar rekaman dari posisi itu. Tombol Edit
        menyunting teks, pilihan speaker hanya berisi pembicara meeting ini.
        Perubahan langsung disimpan ke server tanpa mengulang transkripsi.
      </p>
      <ol className="transcript-segments">
        {segments.map((segment) => (
          <TranscriptSegmentItem
            key={segment.id}
            segment={segment}
            speakers={speakers}
            hasTimestamps={hasTimestamps}
            disabled={disabled}
            onSeek={onSeek}
            onTextSaved={onSegmentTextSaved}
            onSpeakerSaved={onSegmentSpeakerSaved}
          />
        ))}
      </ol>
    </>
  )
}

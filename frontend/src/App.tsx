// Dashboard utama MeetNote AI.
//
// Sprint 1: fondasi UI + integrasi API.
// Sprint 2: navigasi sederhana ke halaman New Meeting / detail tanpa library router.
// Sprint 3: upload file lokal + hapus/tambah ulang rekaman lewat halaman detail.
// Sprint 4: transkripsi audio di halaman detail + status background.

import { useCallback, useEffect, useState } from 'react'

import { fetchHealth, fetchMeetings } from './api'
import { MeetingDetail } from './components/MeetingDetail'
import { MeetingList } from './components/MeetingList'
import { NewMeeting } from './components/NewMeeting'
import type { Meeting } from './types'

type LoadState = 'loading' | 'ready' | 'error'
type View = 'dashboard' | 'new' | 'detail'

export default function App() {
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const [state, setState] = useState<LoadState>('loading')
  const [errorMessage, setErrorMessage] = useState('')
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null)

  const [view, setView] = useState<View>('dashboard')
  const [selected, setSelected] = useState<Meeting | null>(null)
  const [justSaved, setJustSaved] = useState(false)
  // `true` = halaman New Meeting dipakai untuk menambah rekaman ke meeting yang sudah ada.
  const [addingToExisting, setAddingToExisting] = useState(false)

  const loadMeetings = useCallback(async () => {
    setState('loading')
    setErrorMessage('')

    try {
      const [data, health] = await Promise.all([
        fetchMeetings(),
        fetchHealth().catch(() => null),
      ])
      setMeetings(data)
      setBackendHealthy(health !== null)
      setState('ready')
    } catch (error) {
      setBackendHealthy(false)
      setErrorMessage(
        error instanceof Error ? error.message : 'Terjadi kesalahan yang tidak diketahui.',
      )
      setState('error')
    }
  }, [])

  useEffect(() => {
    void loadMeetings()
  }, [loadMeetings])

  function openNewMeeting() {
    setSelected(null)
    setAddingToExisting(false)
    setJustSaved(false)
    setView('new')
  }

  function openDetail(meeting: Meeting) {
    setSelected(meeting)
    setAddingToExisting(false)
    setJustSaved(false)
    setView('detail')
  }

  function addRecordingToSelected() {
    setJustSaved(false)
    setAddingToExisting(true)
    setView('new')
  }

  function closeNewMeeting() {
    if (addingToExisting && selected) {
      setView('detail')
    } else {
      setView('dashboard')
      void loadMeetings()
    }
  }

  function handleSaved(meeting: Meeting) {
    setSelected(meeting)
    setJustSaved(true)
    setAddingToExisting(false)
    setView('detail')
    void loadMeetings()
  }

  // Dipakai setelah hapus rekaman maupun setelah status transkripsi berubah.
  const handleMeetingUpdated = useCallback((meeting: Meeting) => {
    setSelected(meeting)
    setMeetings((previous) => previous.map((item) => (item.id === meeting.id ? meeting : item)))
    setJustSaved(false)
  }, [])

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__inner">
          <div className="brand">
            <span className="brand__logo" aria-hidden="true">✍️</span>
            <div>
              <h1>MeetNote AI</h1>
              <p>Notulen rapat otomatis berbasis AI</p>
            </div>
          </div>

          <div className="header-actions">
            <span className={`connection ${backendHealthy === false ? 'connection--bad' : ''}`}>
              <span className="connection__dot" />
              {backendHealthy === null
                ? 'Menghubungkan…'
                : backendHealthy
                  ? 'Backend online'
                  : 'Backend offline'}
            </span>
            <button className="button button--primary" type="button" onClick={openNewMeeting}>
              + New Meeting
            </button>
          </div>
        </div>
      </header>

      <main className="main-content">
        {view === 'new' && (
          <NewMeeting
            existingMeeting={addingToExisting ? selected : null}
            onBack={closeNewMeeting}
            onCreated={(meeting) => setSelected(meeting)}
            onSaved={handleSaved}
          />
        )}

        {view === 'detail' && selected && (
          <MeetingDetail
            meeting={selected}
            justSaved={justSaved}
            onBack={() => setView('dashboard')}
            onAddRecording={addRecordingToSelected}
            onDeleted={handleMeetingUpdated}
            onMeetingUpdated={handleMeetingUpdated}
          />
        )}

        {view === 'dashboard' && (
          <>
            <section className="dashboard-heading">
              <div>
                <h2>Dashboard</h2>
                <p>Kelola semua pertemuan Anda dalam satu tempat.</p>
              </div>
              <button className="button button--ghost" type="button" onClick={() => void loadMeetings()}>
                ↻ Muat ulang
              </button>
            </section>

            {state === 'loading' && <p className="notice">Memuat daftar meeting…</p>}

            {state === 'error' && (
              <div className="notice notice--error" role="alert">
                <p>{errorMessage}</p>
                <button className="button button--ghost" type="button" onClick={() => void loadMeetings()}>
                  Coba lagi
                </button>
              </div>
            )}

            {state === 'ready' && <MeetingList meetings={meetings} onOpen={openDetail} />}
          </>
        )}
      </main>

      <footer className="app-footer">
        <span>MeetNote AI · Sprint 11 — Validasi Integrasi & Kesiapan Rilis</span>
      </footer>
    </div>
  )
}

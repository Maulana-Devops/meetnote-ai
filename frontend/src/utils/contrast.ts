// Preferensi kontras tinggi (Fase 1). Tidak bergantung pada library i18n/UI.

export const CONTRAST_STORAGE_KEY = 'meetnote-high-contrast'

export function readContrastPreference(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(CONTRAST_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function applyContrastPreference(enabled: boolean): void {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('high-contrast', enabled)
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(CONTRAST_STORAGE_KEY, String(enabled))
  } catch {
    // localStorage bisa diblokir; tampilan tetap mengikuti state React.
  }
}

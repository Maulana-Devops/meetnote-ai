// Tampilan status meeting sebagai badge warna-warni.
// Status tambahan akan mudah ditambahkan di sprint berikutnya.

interface StatusBadgeProps {
  status: string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = status.toLowerCase()
  const className = `badge badge--${normalized}`

  return <span className={className}>{status}</span>
}
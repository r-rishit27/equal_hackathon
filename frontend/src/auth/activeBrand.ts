export function activeBrandId(): string | null {
  try {
    const raw = sessionStorage.getItem('onsum_active_brand')
    return raw ? (JSON.parse(raw)?.id ?? null) : null
  } catch {
    return null
  }
}

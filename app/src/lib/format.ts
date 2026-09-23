/** Presentation helpers. No business logic lives here. */

export function bytes(n: number | null | undefined): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function ms(n: number | null | undefined): string {
  if (n == null) return "—";
  return n < 1000 ? `${n} ms` : `${(n / 1000).toFixed(1)} s`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function shortHash(sha: string | null | undefined, n = 12): string {
  return sha ? sha.slice(0, n) : "—";
}

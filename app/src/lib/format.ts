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

/** ADDENDUM C2: the frozen Static Recovery v2 evidence still labels licensing code PROTECTED_SUBSYSTEM; every current
 *  AB surface shows the canonical role and keeps the original label as provenance (tooltip). */
export const ROLE_ALIASES: Record<string, string> = { PROTECTED_SUBSYSTEM: "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" };
export function canonicalRole(role: string | null | undefined): string {
  if (!role) return "—";
  return ROLE_ALIASES[role] ?? role;
}
export function roleTitle(role: string | null | undefined): string | undefined {
  return role && ROLE_ALIASES[role] ? `frozen static engine label: ${role} (alias)` : undefined;
}


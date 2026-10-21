export const fmtNumber = (n: number) => new Intl.NumberFormat('en-US').format(n);

export const fmtCompact = (n: number) =>
  new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n);

export const fmtDate = (iso: string) =>
  new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

/** "just now", "5 min ago", "3 hours ago", "2 days ago" (falls back to the date after a month). */
export function fmtAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? '' : 's'} ago`;
  const d = Math.round(h / 24);
  if (d < 31) return `${d} day${d === 1 ? '' : 's'} ago`;
  return fmtDate(iso);
}

export const cx = (...c: Array<string | false | null | undefined>) => c.filter(Boolean).join(' ');

/** Score band shared by rings, bars, and badges. */
export function scoreBand(score: number | null) {
  if (score === null) return { label: 'Not checked yet', tone: 'neutral' as const, color: 'rgb(var(--ink-subtle))' };
  if (score >= 80) return { label: 'Healthy', tone: 'good' as const, color: 'rgb(var(--good))' };
  if (score >= 65) return { label: 'Fair', tone: 'warn' as const, color: 'rgb(var(--warn))' };
  return { label: 'Needs attention', tone: 'bad' as const, color: 'rgb(var(--bad))' };
}

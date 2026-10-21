import type { ReactNode } from 'react';
import { useSettings } from '@/api/queries';
import { fmtDate } from '@/lib/format';
import type { ReportBranding } from '@/types';

export const DEFAULT_BRANDING: ReportBranding = {
  companyName: null,
  logoDataUrl: null,
  accentColor: null,
  preparedBy: null,
  footerNote: null,
  showAquarient: true,
};

export function useBranding(): ReportBranding {
  const s = useSettings();
  return { ...DEFAULT_BRANDING, ...(s.data?.branding ?? {}) };
}

/** Report header with the consultant's own logo, name and colour (white-label). */
export function BrandedHeader({ branding, title, subtitle, right }: { branding: ReportBranding; title: ReactNode; subtitle?: ReactNode; right?: ReactNode }) {
  const accent = branding.accentColor ?? undefined;
  return (
    <header className="report-header flex flex-wrap items-start justify-between gap-4 border-b border-line bg-muted/50 px-8 py-6" style={accent ? { borderTop: `4px solid ${accent}` } : undefined}>
      <div className="flex min-w-0 items-start gap-4">
        {branding.logoDataUrl && <img src={branding.logoDataUrl} alt={branding.companyName ?? 'Logo'} className="h-12 max-w-[160px] object-contain" />}
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: accent ?? 'rgb(var(--brand))' }}>
            {branding.companyName ? `${branding.companyName} · CRM Health Report` : 'Aquarient CRM Health Report'}
          </p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>}
        </div>
      </div>
      <div className="text-right text-xs text-ink-subtle">
        <p>Generated {fmtDate(new Date().toISOString())}</p>
        {branding.preparedBy && <p>Prepared by {branding.preparedBy}</p>}
        {right}
      </div>
    </header>
  );
}

export function BrandedFooter({ branding }: { branding: ReportBranding }) {
  const parts = [
    branding.footerNote,
    branding.showAquarient ? 'Prepared with the Aquarient CRM Health & Data Quality Platform.' : null,
    'Confidential.',
  ].filter(Boolean);
  return <footer className="border-t border-line px-8 py-3 text-[11px] text-ink-subtle">{parts.join(' ')}</footer>;
}

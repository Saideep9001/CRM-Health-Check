import { ImagePlus, Trash2 } from 'lucide-react';
import { useEffect, useState, type ChangeEvent } from 'react';
import { errorMessage } from '@/api/client';
import { useUpdateSettings } from '@/api/queries';
import { BrandedHeader, DEFAULT_BRANDING } from '@/components/reports/Branding';
import { Button } from '@/components/ui/Button';
import { Field, Toggle } from '@/components/ui/Form';
import { SectionCard } from '@/components/ui/Page';
import { useToast } from '@/context/ToastContext';
import type { AppSettings } from '@/types';

const MAX_LOGO_BYTES = 300 * 1024;

/** White-label branding for reports, and proposal defaults. */
export function ConsultingSettings({ settings }: { settings: AppSettings }) {
  const update = useUpdateSettings();
  const { notify } = useToast();
  const [draft, setDraft] = useState(settings);
  useEffect(() => setDraft(settings), [settings]);
  const b = { ...DEFAULT_BRANDING, ...(draft.branding ?? {}) };
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);
  const setB = (patch: Partial<typeof b>) => setDraft((d) => ({ ...d, branding: { ...b, ...patch } }));
  const text = (v: string) => (v.trim() ? v : null);

  const onLogo = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!/^image\/(png|jpeg|webp|svg\+xml)$/.test(file.type)) return notify('Unsupported image', 'Use a PNG, JPG, WebP or SVG file.', 'warning');
    if (file.size > MAX_LOGO_BYTES) return notify('Logo is too large', 'Keep it under 300 KB.', 'warning');
    const reader = new FileReader();
    reader.onload = () => setB({ logoDataUrl: String(reader.result) });
    reader.readAsDataURL(file);
  };

  const save = () =>
    update.mutate(draft, {
      onSuccess: () => notify('Settings saved', undefined, 'success'),
      onError: (e) => notify('Couldn’t save', errorMessage(e), 'warning'),
    });

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[1.2fr,1fr]">
        <SectionCard title="Report branding (white-label)" description="Your logo, name and colour on every printed report and proposal.">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              {b.logoDataUrl ? (
                <img src={b.logoDataUrl} alt="Logo preview" className="h-12 max-w-[160px] rounded border border-line object-contain p-1" />
              ) : (
                <div className="flex h-12 w-24 items-center justify-center rounded border border-dashed border-line text-xs text-ink-subtle">No logo</div>
              )}
              <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-muted">
                <ImagePlus className="h-4 w-4" /> Upload logo
                <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" className="sr-only" onChange={onLogo} />
              </label>
              {b.logoDataUrl && (
                <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setB({ logoDataUrl: null })}>
                  Remove
                </Button>
              )}
            </div>
            <Field label="Company name">
              <input className="input" value={b.companyName ?? ''} maxLength={120} onChange={(e) => setB({ companyName: text(e.target.value) })} placeholder="e.g. Northwind Consulting" />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Accent colour">
                <div className="flex items-center gap-2">
                  <input type="color" value={b.accentColor ?? '#058cc9'} onChange={(e) => setB({ accentColor: e.target.value })} className="h-9 w-12 cursor-pointer rounded border border-line bg-surface" aria-label="Accent colour" />
                  {b.accentColor && <button className="text-xs text-ink-subtle hover:underline" onClick={() => setB({ accentColor: null })}>Use default</button>}
                </div>
              </Field>
              <Field label="Prepared by">
                <input className="input" value={b.preparedBy ?? ''} maxLength={120} onChange={(e) => setB({ preparedBy: text(e.target.value) })} placeholder="e.g. Jane Doe, Senior Consultant" />
              </Field>
            </div>
            <Field label="Footer note" hint="Shown at the bottom of every report, e.g. your contact details.">
              <input className="input" value={b.footerNote ?? ''} maxLength={300} onChange={(e) => setB({ footerNote: text(e.target.value) })} />
            </Field>
            <Toggle checked={b.showAquarient} onChange={(v) => setB({ showAquarient: v })} label="Show “Prepared with Aquarient”" description="Turn off for fully white-labelled reports." />
          </div>
        </SectionCard>

        <div className="space-y-6">
          <SectionCard title="Preview">
            <div className="overflow-hidden rounded-lg border border-line">
              <BrandedHeader branding={b} title="Summary for leadership" subtitle="Client org · Health check" />
            </div>
          </SectionCard>
          <SectionCard title="Proposals" description="Defaults for the Proposal (SOW) report. You can change the rate on each proposal.">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Hourly rate">
                <input type="number" min={0} max={5000} className="input" value={draft.hourlyRate ?? 150} onChange={(e) => setDraft((d) => ({ ...d, hourlyRate: Math.max(0, Number(e.target.value) || 0) }))} />
              </Field>
              <Field label="Currency" hint="3-letter code, e.g. USD, EUR, INR">
                <input className="input uppercase" maxLength={3} value={draft.currency ?? 'USD'} onChange={(e) => setDraft((d) => ({ ...d, currency: e.target.value.toUpperCase().replace(/[^A-Z]/g, '') }))} />
              </Field>
            </div>
          </SectionCard>
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <Button onClick={() => setDraft(settings)} disabled={!dirty}>Discard changes</Button>
        <Button variant="primary" onClick={save} disabled={!dirty || update.isPending}>{update.isPending ? 'Saving…' : 'Save changes'}</Button>
      </div>
    </div>
  );
}

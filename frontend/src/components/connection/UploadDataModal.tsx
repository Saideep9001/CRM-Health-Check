import { ArrowLeft, FileSpreadsheet, Upload } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadApi } from '@/api/endpoints';
import { useImportUpload, useUploadPreview } from '@/api/queries';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Form';
import { Modal } from '@/components/ui/Overlay';
import { InlineError } from '@/components/ui/States';
import { useToast } from '@/context/ToastContext';
import { cx, fmtNumber } from '@/lib/format';
import type { UploadPreview } from '@/types';

const OBJECTS = [
  { value: 'Account', label: 'Accounts' },
  { value: 'Contact', label: 'Contacts' },
  { value: 'Lead', label: 'Leads' },
  { value: 'Opportunity', label: 'Opportunities' },
  { value: 'other', label: 'Something else' },
];
const KEEP = '';
const LEAVE_OUT = '-';
const TYPE_LABEL: Record<string, string> = {
  string: 'Text', textarea: 'Long text', email: 'Email', phone: 'Phone', url: 'Website', date: 'Date', datetime: 'Date & time',
  int: 'Number', double: 'Number', currency: 'Money', percent: 'Percent', boolean: 'Yes / No', picklist: 'Picklist', reference: 'Link',
  id: 'Record ID',
};

/** Upload a CSV or Excel export and check it like a connected Salesforce org. */
export function UploadDataModal({ open, onClose, addTo }: { open: boolean; onClose: () => void; addTo?: { orgId: string; name: string } | null }) {
  const preview = useUploadPreview();
  const load = useImportUpload();
  const { notify } = useToast();
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [choice, setChoice] = useState('Account');
  const [custom, setCustom] = useState('');
  const [name, setName] = useState('');
  const [target, setTarget] = useState<'add' | 'new'>(addTo ? 'add' : 'new');
  const [data, setData] = useState<UploadPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);
  const [rematching, setRematching] = useState(false);
  const [rematchError, setRematchError] = useState<unknown>(null);

  const object = choice === 'other' ? custom.trim().replace(/\s+/g, '_') : choice;
  const objectOk = /^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(object);

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setData(null);
    setMapping({});
    setName('');
    setTarget(addTo ? 'add' : 'new');
    preview.reset();
    load.reset();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyPreview = (p: UploadPreview) => {
    setData(p);
    setMapping(Object.fromEntries(p.columns.map((c) => [c.header, c.field ?? KEEP])));
  };

  const read = (f: File) => {
    setFile(f);
    if (!name) setName(f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' '));
    if (objectOk) preview.mutate({ file: f, object }, { onSuccess: applyPreview });
  };

  // Changing the object re-matches the same file's columns to that object's fields.
  useEffect(() => {
    if (!data || !objectOk || data.object === object) return;
    let live = true;
    setRematching(true);
    setRematchError(null);
    uploadApi
      .previewAgain(data.token, object)
      .then((p) => live && applyPreview(p))
      .catch((e) => live && setRematchError(e))
      .finally(() => live && setRematching(false));
    return () => {
      live = false;
    };
  }, [object]); // eslint-disable-line react-hooks/exhaustive-deps

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) read(f);
  };

  const used = useMemo(() => new Map(Object.entries(mapping).filter(([, v]) => v && v !== LEAVE_OUT).map(([h, v]) => [v, h])), [mapping]);
  const counts = useMemo(() => {
    const vals = Object.values(mapping);
    return { matched: vals.filter((v) => v && v !== LEAVE_OUT).length, custom: vals.filter((v) => v === KEEP).length, out: vals.filter((v) => v === LEAVE_OUT).length };
  }, [mapping]);

  const submit = () => {
    if (!data) return;
    load.mutate(
      {
        token: data.token,
        object,
        mapping: Object.fromEntries(Object.entries(mapping).map(([h, v]) => [h, v === KEEP ? null : v])),
        orgId: target === 'add' && addTo ? addTo.orgId : null,
        name: target === 'new' ? name.trim() || undefined : undefined,
      },
      {
        onSuccess: (r) => {
          notify(`${fmtNumber(r.rows)} records loaded`, `${r.name} is now the active data. Run a Data Quality check to see its score.`, 'success');
          onClose();
          navigate('/assessment/data-quality');
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={data ? `Check ${fmtNumber(data.rows)} rows from ${data.filename}` : 'Upload CRM data'}
      description={data ? 'Each column becomes a Salesforce field. Change any that are matched wrongly.' : 'A CSV or Excel export from Salesforce or any CRM. It’s checked with the same rules as a connected org.'}
      footer={
        data ? (
          <>
            <Button icon={<ArrowLeft className="h-4 w-4" />} onClick={() => { setData(null); setFile(null); preview.reset(); }}>Choose another file</Button>
            <Button variant="primary" onClick={submit} disabled={load.isPending || rematching || !objectOk || counts.matched + counts.custom === 0}>
              {load.isPending ? 'Loading…' : `Load ${fmtNumber(data.rows)} ${OBJECTS.find((o) => o.value === object)?.label ?? object}`}
            </Button>
          </>
        ) : (
          <Button onClick={onClose}>Cancel</Button>
        )
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="What does the file hold?">
            <select className="input" value={choice} onChange={(e) => setChoice(e.target.value)}>
              {OBJECTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
          {choice === 'other' ? (
            <Field label="Name for these records" hint="e.g. Invoice or Case">
              <input className="input" value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Invoice" />
            </Field>
          ) : addTo ? (
            <Field label="Where should it go?">
              <select className="input" value={target} onChange={(e) => setTarget(e.target.value as 'add' | 'new')}>
                <option value="add">Add to “{addTo.name}”</option>
                <option value="new">A new upload</option>
              </select>
            </Field>
          ) : null}
          {target === 'new' && (
            <Field label="Name this data" hint="Shown in Client Portfolio, like an org">
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme CRM export" maxLength={120} />
            </Field>
          )}
        </div>
        {choice === 'other' && custom && !objectOk && <p className="text-xs text-bad">Use letters, numbers and spaces, starting with a letter.</p>}

        {!data && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cx('flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition', dragging ? 'border-brand bg-brand-soft' : 'border-line bg-muted/40')}
          >
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-soft text-brand"><FileSpreadsheet className="h-5 w-5" /></span>
            <p className="text-sm font-medium">{preview.isPending ? `Reading ${file?.name ?? 'the file'}…` : 'Drop a file here, or choose one'}</p>
            <p className="text-xs text-ink-subtle">.csv or .xlsx · up to 200,000 rows · the first row holds the column names</p>
            <input ref={input} type="file" accept=".csv,.txt,.tsv,.xlsx,.xlsm" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) read(f); e.target.value = ''; }} />
            <Button size="sm" variant="primary" icon={<Upload className="h-3.5 w-3.5" />} disabled={preview.isPending || !objectOk} onClick={() => input.current?.click()}>
              Choose file
            </Button>
          </div>
        )}
        <InlineError error={preview.error ?? rematchError} />

        {data && (
          <>
            <p className="text-xs text-ink-muted">
              <span className="font-semibold text-ink">{counts.matched}</span> columns match Salesforce fields ·{' '}
              <span className="font-semibold text-ink">{counts.custom}</span> kept as custom fields
              {counts.out > 0 && <> · <span className="font-semibold text-ink">{counts.out}</span> left out</>}
              {rematching && ' · matching…'}
            </p>
            <div className="scrollbar-thin max-h-[46vh] overflow-auto rounded-lg border border-line">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-muted text-[11px] uppercase tracking-wide text-ink-subtle">
                  <tr>
                    <th className="px-3 py-2">Column</th>
                    <th className="px-3 py-2">Example</th>
                    <th className="px-3 py-2 text-right">Filled</th>
                    <th className="px-3 py-2">Becomes</th>
                  </tr>
                </thead>
                <tbody>
                  {data.columns.map((c) => {
                    const v = mapping[c.header] ?? KEEP;
                    return (
                      <tr key={c.header} className={cx('border-t border-line', v === LEAVE_OUT && 'opacity-50')}>
                        <td className="px-3 py-1.5 font-medium text-ink">{c.header}</td>
                        <td className="max-w-[10rem] truncate px-3 py-1.5 text-ink-muted" title={c.sample}>{c.sample || '—'}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-ink-muted">{data.rows ? Math.round((100 * c.filled) / data.rows) : 0}%</td>
                        <td className="px-3 py-1">
                          <select className="input h-8 py-0 text-xs" value={v} onChange={(e) => setMapping((m) => ({ ...m, [c.header]: e.target.value }))}>
                            <option value={KEEP}>Custom field ({TYPE_LABEL[c.type] ?? c.type})</option>
                            <option value={LEAVE_OUT}>Leave out</option>
                            <optgroup label="Salesforce field">
                              {data.standardFields.map((f) => (
                                <option key={f.name} value={f.name} disabled={used.has(f.name) && used.get(f.name) !== c.header}>
                                  {f.label} ({f.name})
                                </option>
                              ))}
                            </optgroup>
                          </select>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-ink-subtle">
              Stays on this server and is only read. Things a file can’t include — page layouts, flows, history, users — are left out of the checks.
            </p>
          </>
        )}
        <InlineError error={load.error} />
      </div>
    </Modal>
  );
}

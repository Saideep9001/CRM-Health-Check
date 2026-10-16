import type { DataField } from '@/types';
import { fmtDate } from '@/lib/format';

/** Salesforce sends "+0000"; some browsers only parse "+00:00". */
const isoFix = (s: string) => s.replace(/([+-]\d{2})(\d{2})$/, '$1:$2');

const num = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

/** Turn a raw Salesforce value into readable text for tables and the record panel. */
export function formatValue(field: DataField | undefined, value: unknown, refName?: string): string {
  if (value === null || value === undefined || value === '') return '—';
  if (refName) return refName;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') {
    // Compound fields such as addresses.
    return Object.entries(value as Record<string, unknown>)
      .filter(([k, v]) => v !== null && v !== '' && typeof v !== 'object' && !/latitude|longitude|geocode/i.test(k))
      .map(([, v]) => String(v))
      .join(', ') || '—';
  }
  const type = field?.type;
  if (type === 'date' && typeof value === 'string') return fmtDate(value);
  if (type === 'datetime' && typeof value === 'string') {
    const d = new Date(isoFix(value));
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
  }
  if (typeof value === 'number') {
    if (type === 'percent') return `${num.format(value)}%`;
    return num.format(value);
  }
  return String(value);
}

/** Plain-language names for Salesforce field types. */
export function typeLabel(f: DataField): string {
  switch (f.type) {
    case 'id':
      return 'Record ID';
    case 'reference':
      return f.referenceTo.length ? `Link to ${f.referenceTo.join(' / ')}` : 'Link';
    case 'string':
      return 'Text';
    case 'textarea':
      return 'Long text';
    case 'picklist':
      return 'Pick list';
    case 'multipicklist':
      return 'Multi-select list';
    case 'boolean':
      return 'Checkbox';
    case 'datetime':
      return 'Date & time';
    case 'double':
    case 'int':
    case 'long':
      return 'Number';
    default:
      return f.type.charAt(0).toUpperCase() + f.type.slice(1);
  }
}

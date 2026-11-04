import { ExternalLink } from 'lucide-react';
import { cx, fmtNumber } from '@/lib/format';
import type { RuleListItem } from '@/types';

/** Lead Assignment Rules behind a card: each rule's status, its entries in words with the open Leads each would match
 *  (inactive rules: potential matches only), and a link to the rule in Salesforce Setup. */
export function RulesBehind({ rules }: { rules: RuleListItem[] }) {
  if (!rules.length) return <p className="rounded-lg bg-muted/50 px-4 py-3 text-sm text-ink-muted">No Lead Assignment Rules were found in Setup.</p>;
  return (
    <div className="space-y-3">
      {rules.map((r) => (
        <article key={r.name} className={cx('overflow-hidden rounded-xl border', r.active ? 'border-good/30' : 'border-line')}>
          <header className={cx('flex flex-wrap items-center gap-2 border-b px-3 py-2', r.active ? 'border-good/20 bg-good-soft/40' : 'border-line bg-muted/50')}>
            <span className="text-sm font-semibold">{r.name}</span>
            <span className={cx('rounded-full px-2 py-0.5 text-[11px] font-semibold', r.active ? 'bg-good-soft text-good' : 'bg-warn-soft text-warn')}>
              {r.active ? 'Active' : 'Inactive'}
            </span>
            {!r.active && r.matches != null && (
              <span className={cx('rounded-full px-2 py-0.5 text-[11px] tabular-nums', r.matches ? 'bg-brand-soft text-brand-ink' : 'bg-surface text-ink-muted')}>
                {r.matches ? `${fmtNumber(r.matches)} potential match${r.matches === 1 ? '' : 'es'}` : 'Matches no open Lead'}
              </span>
            )}
            {r.url && (
              <a
                href={r.url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                title="Open this rule in Salesforce Setup"
              >
                Open in Salesforce <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </header>
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-xs">
              <thead className="text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                <tr>
                  <th className="px-3 py-2">Entry</th>
                  <th className="px-3 py-2">Criteria</th>
                  <th className="px-3 py-2">Assigns to</th>
                  {!r.active && <th className="px-3 py-2 text-right">Potential matches</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {r.entries.map((e) => (
                  <tr key={e.order}>
                    <td className="px-3 py-2 tabular-nums text-ink-muted">{e.order}</td>
                    <td className="px-3 py-2">{e.criteria}</td>
                    <td className="px-3 py-2 text-ink-muted">{e.assignedTo}</td>
                    {!r.active && <td className="px-3 py-2 text-right font-semibold tabular-nums">{e.matches == null ? '—' : fmtNumber(e.matches)}</td>}
                  </tr>
                ))}
                {r.entries.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-3 text-center text-ink-subtle">This rule has no entries.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
      ))}
      <p className="text-[11px] text-ink-subtle">
        Potential matches are the open Leads an inactive rule would assign if it were active. An inactive rule assigns nothing, so they don’t mean those Leads are wrongly assigned.
      </p>
    </div>
  );
}

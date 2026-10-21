import { Trophy } from 'lucide-react';
import { useBenchmarks } from '@/api/queries';
import { getCategory } from '@/config/categories';
import { cx } from '@/lib/format';

/** How this org compares with the other orgs in the portfolio (needs a few orgs before it's meaningful). */
export function BenchmarkCard({ assessmentId }: { assessmentId: string }) {
  const q = useBenchmarks(assessmentId);
  const b = q.data;
  if (!b) return null;
  return (
    <section className="card mb-6 p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Trophy className="h-4 w-4 text-brand" />
        <h3 className="text-sm font-semibold">How this org compares</h3>
        <span className="text-xs text-ink-subtle">against the latest check of {b.peers} other org{b.peers === 1 ? '' : 's'} in your portfolio</span>
      </div>
      {!b.ready ? (
        <p className="text-sm text-ink-muted">
          Benchmarks appear once you’ve checked at least {b.minPeers} other orgs ({b.peers} so far). They compare scores across your own clients only — no data leaves your workspace.
        </p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {b.lines.map((l) => {
            const p = l.percentile;
            const tone = p === null ? 'text-ink-muted' : p >= 66 ? 'text-good' : p >= 33 ? 'text-warn' : 'text-bad';
            return (
              <div key={l.key} className="rounded-lg border border-line px-3 py-2">
                <p className="truncate text-xs text-ink-muted">{l.key === 'overall' ? 'Overall' : getCategory(l.key)?.shortName ?? l.label}</p>
                <p className={cx('text-lg font-semibold', tone)}>{p === null ? '—' : p >= 50 ? `Top ${100 - p}%` : `Bottom ${p + 1}%`}</p>
                <p className="text-[11px] text-ink-subtle">Score {l.score ?? '—'} · median {l.median ?? '—'} ({l.peers} orgs)</p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

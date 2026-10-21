import { AnimatePresence, motion } from 'framer-motion';
import { FileSearch, Layers, Search, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CATEGORIES, DIAGNOSTIC_AREAS, getCategory } from '@/config/categories';
import { NAV_ITEMS } from '@/config/navigation';
import { useRole } from '@/api/queries';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import type { Finding } from '@/types';
import { cx } from '@/lib/format';
import { CategoryIcon } from '../ui/CategoryIcon';

interface Result {
  key: string;
  group: 'Pages' | 'Topics' | 'Areas' | 'Problems (latest check)';
  label: string;
  sub?: string;
  to: string;
  icon: React.ReactNode;
}

function buildIndex(findings: Finding[], assessmentId: string | null, isAdmin: boolean): Result[] {
  return [
    ...NAV_ITEMS.filter((n) => !n.adminOnly || isAdmin).map<Result>((n) => ({
      key: `p-${n.to}`,
      group: 'Pages',
      label: n.label,
      to: n.to,
      icon: <n.icon className="h-4 w-4" />,
    })),
    ...CATEGORIES.map<Result>((c) => ({
      key: `c-${c.id}`,
      group: 'Topics',
      label: c.name,
      sub: c.release === 'coming-soon' ? 'Coming Soon' : undefined,
      to: `/assessment/${c.id}`,
      icon: <CategoryIcon id={c.id} className="h-4 w-4" />,
    })),
    ...DIAGNOSTIC_AREAS.map<Result>((a) => ({
      key: `a-${a.id}`,
      group: 'Areas',
      label: `Area ${a.number}: ${a.name}`,
      sub: getCategory(a.categoryId)?.name,
      to: `/assessment/${a.categoryId}/${a.id}`,
      icon: <Layers className="h-4 w-4" />,
    })),
    ...findings.map<Result>((f) => ({
      key: `f-${f.id}`,
      group: 'Problems (latest check)',
      label: f.name,
      sub: f.id,
      to: `/results?assessment=${encodeURIComponent(assessmentId ?? '')}&finding=${encodeURIComponent(f.id)}`,
      icon: <TriangleAlert className="h-4 w-4" />,
    })),
  ];
}

export function GlobalSearch() {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { findings, latest } = useLatestAssessment();
  const { isAdmin } = useRole();
  const index = useMemo(() => buildIndex(findings, latest?.id ?? null, isAdmin), [findings, latest, isAdmin]);

  const results = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return [];
    return index
      .filter((r) => r.label.toLowerCase().includes(term) || r.sub?.toLowerCase().includes(term))
      .slice(0, 12);
  }, [q, index]);

  useEffect(() => setActive(0), [q]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    const onDown = (e: MouseEvent) => boxRef.current && !boxRef.current.contains(e.target as Node) && setOpen(false);
    window.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, []);

  const go = (r: Result) => {
    navigate(r.to);
    setQ('');
    setOpen(false);
    inputRef.current?.blur();
  };

  let lastGroup = '';

  return (
    <div ref={boxRef} className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
      <input
        ref={inputRef}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, results.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === 'Enter' && results[active]) {
            go(results[active]);
          } else if (e.key === 'Escape') {
            setOpen(false);
            inputRef.current?.blur();
          }
        }}
        placeholder="Search topics, areas, problems…"
        aria-label="Global search"
        className="input h-9 bg-muted pl-9 pr-14 focus:bg-surface"
      />
      <kbd className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-line bg-surface px-1.5 text-[10px] font-medium text-ink-subtle sm:block">
        Ctrl K
      </kbd>

      <AnimatePresence>
        {open && q.trim() && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.14 }}
            className="card scrollbar-thin absolute left-0 right-0 top-full z-50 mt-2 max-h-[420px] overflow-y-auto p-1.5 shadow-pop"
          >
            {results.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-4 py-8 text-center text-sm text-ink-muted">
                <FileSearch className="h-6 w-6 text-ink-subtle" />
                No matches for “{q}”
              </div>
            ) : (
              results.map((r, i) => {
                const header = r.group !== lastGroup;
                lastGroup = r.group;
                return (
                  <div key={r.key}>
                    {header && <p className="label px-2.5 pb-1 pt-2.5">{r.group}</p>}
                    <button
                      onMouseEnter={() => setActive(i)}
                      onClick={() => go(r)}
                      className={cx(
                        'flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left text-sm',
                        i === active ? 'bg-muted' : '',
                      )}
                    >
                      <span className="text-ink-subtle">{r.icon}</span>
                      <span className="min-w-0 flex-1 truncate">{r.label}</span>
                      {r.sub && <span className="shrink-0 truncate text-xs text-ink-subtle">{r.sub}</span>}
                    </button>
                  </div>
                );
              })
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

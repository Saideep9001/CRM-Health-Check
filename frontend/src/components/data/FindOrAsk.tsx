import { CornerDownLeft, Loader2, Search, Sparkles, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDataAsk, useDataSearch } from '@/api/queries';
import { loadMyList } from '@/components/data/ObjectList';
import { cx } from '@/lib/format';
import type { DataSearchHit } from '@/types';

const EXAMPLES = [
  'Open deals over 50k closing this month',
  'Accounts without contacts',
  'How many leads were created this week?',
  'Contacts with no email',
  'Opportunities not updated in 90 days',
  'Technology accounts in California',
];

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

type Item = { kind: 'ask' } | { kind: 'hit'; object: string; label: string; hit: DataSearchHit };

/**
 * One box for both: find a record by name, email or phone across all objects,
 * or ask a question in plain English ("open deals over 50k") and see the matching records.
 */
export function FindOrAsk({ current }: { current?: string }) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const term = useDebounced(text.trim());
  const myList = useMemo(() => loadMyList(), [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const search = useDataSearch(term, myList.length ? myList : undefined, open);
  const ask = useDataAsk();

  // Press "/" anywhere on the page to jump to the box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.key === '/' && !e.ctrlKey && !e.metaKey && !(el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)))) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const groups = term.length >= 2 ? search.data ?? [] : [];
  const items: Item[] = useMemo(
    () => [
      ...(text.trim() ? [{ kind: 'ask' } as Item] : []),
      ...groups.flatMap((g) => g.records.map((hit) => ({ kind: 'hit', object: g.object, label: g.label, hit }) as Item)),
    ],
    [text, groups],
  );
  useEffect(() => setActive(0), [text]);

  const runAsk = (question: string) => {
    const q = question.trim();
    if (!q) return;
    ask.mutate(
      { question: q, objects: myList, context: current },
      {
        onSuccess: (a) => {
          const p = new URLSearchParams({ ask: a.question });
          if (a.filters.length) p.set('f', JSON.stringify(a.filters));
          if (a.ignored.length) p.set('ig', a.ignored.join(','));
          if (a.sort) {
            p.set('sort', a.sort);
            p.set('dir', a.dir ?? 'desc');
          }
          navigate(`/data/${encodeURIComponent(a.object)}?${p.toString()}`);
          setOpen(false);
          inputRef.current?.blur();
        },
      },
    );
  };

  const choose = (item: Item | undefined) => {
    if (!item) return;
    if (item.kind === 'ask') return runAsk(text);
    navigate(`/data/${encodeURIComponent(item.object)}?only=${encodeURIComponent(item.hit.id)}`, {
      state: { from: `found by searching “${text.trim()}”` },
    });
    setOpen(false);
    inputRef.current?.blur();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(items.length - 1, 0)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(items[active]);
    } else if (e.key === 'Escape') {
      setOpen(false);
      inputRef.current?.blur();
    }
  };

  let idx = text.trim() ? 1 : 0; // running index of search hits in `items`

  return (
    <div className="relative mb-6">
      <div
        className={cx(
          'flex items-center gap-3 rounded-2xl border bg-surface px-4 shadow-sm transition',
          open ? 'border-brand ring-4 ring-brand/10' : 'border-line hover:border-ink-subtle/40',
        )}
      >
        {ask.isPending ? <Loader2 className="h-5 w-5 shrink-0 animate-spin text-brand" /> : <Sparkles className="h-5 w-5 shrink-0 text-brand" />}
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            if (ask.error) ask.reset();
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          className="h-12 min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-ink-subtle focus:outline-none focus-visible:outline-none focus-visible:ring-0"
          placeholder="Find a record, or ask: “open deals over 50k closing this month”"
          aria-label="Find a record or ask a question about your data"
          role="combobox"
          aria-expanded={open}
          aria-controls="find-or-ask-list"
          autoComplete="off"
        />
        {text ? (
          <button onMouseDown={(e) => e.preventDefault()} onClick={() => setText('')} className="rounded-full p-1 text-ink-subtle hover:text-ink" aria-label="Clear">
            <X className="h-4 w-4" />
          </button>
        ) : (
          <kbd className="hidden rounded border border-line px-1.5 text-[11px] text-ink-subtle sm:inline">/</kbd>
        )}
      </div>

      {open && (
        <div
          id="find-or-ask-list"
          role="listbox"
          onMouseDown={(e) => e.preventDefault()} // keep focus in the box while clicking
          className="scrollbar-thin absolute inset-x-0 top-full z-30 mt-2 max-h-[420px] overflow-y-auto rounded-2xl border border-line bg-surface p-2 shadow-xl"
        >
          {!text.trim() ? (
            <div className="p-2">
              <p className="mb-2 text-xs font-medium text-ink-muted">Try asking</p>
              <div className="flex flex-wrap gap-1.5">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    onClick={() => {
                      setText(ex);
                      runAsk(ex);
                    }}
                    className="rounded-full border border-line px-3 py-1 text-xs text-ink-muted transition hover:border-brand hover:text-brand"
                  >
                    {ex}
                  </button>
                ))}
              </div>
              <p className="mt-3 text-[11px] text-ink-subtle">Or type a name, email or phone number to find a record in any object.</p>
            </div>
          ) : (
            <>
              <button
                role="option"
                aria-selected={active === 0}
                onMouseEnter={() => setActive(0)}
                onClick={() => runAsk(text)}
                className={cx('flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left', active === 0 && 'bg-brand-soft')}
              >
                <Sparkles className="h-4 w-4 shrink-0 text-brand" />
                <span className="min-w-0 flex-1 truncate text-sm">
                  Ask <span className="font-semibold">“{text.trim()}”</span>
                </span>
                <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-ink-subtle" />
              </button>
              {ask.error && (
                <p className="mx-3 mb-1 rounded-lg bg-bad-soft px-3 py-2 text-xs text-bad">{(ask.error as Error).message}</p>
              )}

              <div className="mt-1 border-t border-line pt-1">
                {term.length < 2 ? null : search.isLoading ? (
                  <p className="flex items-center gap-2 px-3 py-2 text-xs text-ink-subtle">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Searching your records…
                  </p>
                ) : search.error ? (
                  <p className="px-3 py-2 text-xs text-ink-subtle">Search isn’t available right now. You can still ask.</p>
                ) : groups.length === 0 ? (
                  term.split(/\s+/).length >= 3 ? null : // a question, not a name: the Ask row is enough
                  <p className="flex items-center gap-2 px-3 py-2 text-xs text-ink-subtle">
                    <Search className="h-3.5 w-3.5" /> No records match “{term}”.
                  </p>
                ) : (
                  groups.map((g) => (
                    <div key={g.object} className="py-1">
                      <p className="px-3 pb-0.5 pt-1 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">{g.labelPlural}</p>
                      {g.records.map((hit) => {
                        const i = idx++;
                        return (
                          <button
                            key={hit.id}
                            role="option"
                            aria-selected={active === i}
                            onMouseEnter={() => setActive(i)}
                            onClick={() => choose(items[i])}
                            className={cx('flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left', active === i && 'bg-muted')}
                          >
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium">{hit.name}</span>
                              {hit.detail && <span className="block truncate text-xs text-ink-subtle">{hit.detail}</span>}
                            </span>
                            <span className="shrink-0 rounded-full bg-muted px-2 text-[11px] text-ink-muted">{g.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

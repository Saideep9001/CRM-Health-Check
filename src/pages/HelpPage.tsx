import { AnimatePresence, motion } from 'framer-motion';
import { BookOpen, ChevronDown, Cloud, ListChecks, Mail, Play, PlayCircle, Search, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useWelcomeTour } from '@/components/onboarding/WelcomeTour';
import { SeverityBadge } from '@/components/ui/Badges';
import { Button, LinkButton } from '@/components/ui/Button';
import { SearchInput } from '@/components/ui/Form';
import { PageHeader, SectionCard } from '@/components/ui/Page';
import { CATEGORIES, CATEGORY_COLORS } from '@/config/categories';
import { GLOSSARY, SCORE_BANDS, URGENCY_HELP } from '@/config/glossary';
import { cx } from '@/lib/format';
import { SEVERITIES } from '@/lib/health';

const STEPS = [
  { icon: Cloud, title: 'Connect Salesforce', text: 'Sign in on Salesforce’s own page.', to: '/connection', cta: 'Connect' },
  { icon: Play, title: 'Run a health check', text: 'Open a topic and press Check.', to: '/assessment', cta: 'Start a check' },
  { icon: ListChecks, title: 'Fix what matters', text: 'Start with Critical problems.', to: '/results', cta: 'See results' },
];

const FAQ = [
  {
    q: 'Do I need to be technical to use this?',
    a: 'No. Every problem is explained simply, with a fix.',
  },
  {
    q: 'Will this change anything in our Salesforce?',
    a: 'No. We only read your data.',
  },
  {
    q: 'How long does a health check take?',
    a: 'Usually a few minutes. You can leave the page while it runs.',
  },
  {
    q: 'Where should I start once I have results?',
    a: 'Open My Results and start with Critical problems.',
  },
  {
    q: 'What does “Coming Soon” mean?',
    a: 'You can see it now, but can’t check it yet.',
  },
  {
    q: 'How often should we run a health check?',
    a: 'Every few months, and after you fix problems.',
  },
  {
    q: 'Something isn’t working — what should I do?',
    a: 'Click Try again. If it still fails, contact your Aquarient consultant.',
  },
];

export default function HelpPage() {
  const tour = useWelcomeTour();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<number | null>(0);

  const terms = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? GLOSSARY.filter((g) => g.term.toLowerCase().includes(t) || g.plain.toLowerCase().includes(t)) : GLOSSARY;
  }, [q]);

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Help & guide"
        description="Simple answers to common questions."
        actions={
          <Button variant="primary" icon={<PlayCircle className="h-4 w-4" />} onClick={tour.open}>
            Replay the quick tour
          </Button>
        }
      />

      {/* 3 steps */}
      <SectionCard title="3 simple steps">
        <ol className="grid gap-4 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex flex-col rounded-xl border border-line p-5">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand text-white">
                  <s.icon className="h-5 w-5" />
                </span>
                <span className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">Step {i + 1}</span>
              </div>
              <h3 className="mt-3 text-base font-semibold">{s.title}</h3>
              <p className="mt-1 flex-1 text-sm text-ink-muted">{s.text}</p>
              <LinkButton to={s.to} size="sm" className="mt-4 self-start">
                {s.cta}
              </LinkButton>
            </li>
          ))}
        </ol>
      </SectionCard>

      {/* Reading results */}
      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <SectionCard title="What do the scores mean?" description="0 to 100. Higher is better.">
          <ul className="space-y-3">
            {SCORE_BANDS.map((b) => (
              <li key={b.label} className="flex items-center gap-3">
                <span className="flex h-10 w-14 items-center justify-center rounded-lg text-sm font-bold text-white" style={{ background: b.color }}>
                  {b.text}
                </span>
                <span>
                  <span className="block text-sm font-semibold">{b.label}</span>
                  <span className="block text-xs text-ink-muted">
                    {b.min >= 80 ? 'In good shape.' : b.min >= 65 ? 'Some gaps to fix.' : 'Needs work soon.'}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
        <SectionCard title="What does urgency mean?" description="Start with the most urgent.">
          <ul className="space-y-3">
            {SEVERITIES.map((s) => (
              <li key={s} className="flex items-center gap-3">
                <span className="w-20 shrink-0">
                  <SeverityBadge severity={s} />
                </span>
                <span className="text-sm text-ink-muted">{URGENCY_HELP[s]}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      </div>

      {/* Topics */}
      <SectionCard className="mt-6" title="The six topics we check" description="21 areas in total.">
        <div className="grid gap-3 sm:grid-cols-2">
          {CATEGORIES.map((c) => (
            <div key={c.id} className="flex gap-3 rounded-lg border border-line p-3">
              <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: CATEGORY_COLORS[c.id] }} />
              <div>
                <p className="text-sm font-semibold">
                  {c.name}
                  {c.release === 'coming-soon' && <span className="ml-2 text-xs font-medium text-warn">Coming Soon</span>}
                </p>
                <p className="mt-0.5 text-xs text-ink-muted">{c.purpose}</p>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Glossary */}
      <SectionCard
        className="mt-6"
        title={
          <span className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-brand" /> Glossary — words you’ll see
          </span>
        }
        actions={<SearchInput value={q} onChange={setQ} placeholder="Search a word…" className="w-56" />}
      >
        {terms.length === 0 ? (
          <p className="flex items-center gap-2 py-6 text-sm text-ink-muted">
            <Search className="h-4 w-4" /> No matching words. Try another search.
          </p>
        ) : (
          <dl className="grid gap-x-8 gap-y-5 md:grid-cols-2">
            {terms.map((g) => (
              <div key={g.term}>
                <dt className="text-sm font-semibold">{g.term}</dt>
                <dd className="mt-1 text-sm text-ink-muted">{g.plain}</dd>
                {g.example && <dd className="mt-1 text-xs italic text-ink-subtle">{g.example}</dd>}
              </div>
            ))}
          </dl>
        )}
      </SectionCard>

      {/* FAQ */}
      <SectionCard className="mt-6" title="Common questions" bodyClassName="px-5 py-1">
        {FAQ.map((f, i) => (
          <div key={f.q} className="border-b border-line last:border-0">
            <button onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i} className="flex w-full items-center justify-between gap-4 py-4 text-left">
              <span className="text-sm font-semibold">{f.q}</span>
              <ChevronDown className={cx('h-4 w-4 shrink-0 text-ink-subtle transition-transform', open === i && 'rotate-180')} />
            </button>
            <AnimatePresence initial={false}>
              {open === i && (
                <motion.p initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden pb-4 pr-8 text-sm leading-relaxed text-ink-muted">
                  {f.a}
                </motion.p>
              )}
            </AnimatePresence>
          </div>
        ))}
      </SectionCard>

      <div className="mt-6 flex flex-col items-start gap-3 rounded-xl border border-line bg-surface p-5 sm:flex-row sm:items-center">
        <ShieldCheck className="h-8 w-8 shrink-0 text-good" />
        <p className="flex-1 text-sm text-ink-muted">
          <span className="font-semibold text-ink">Your data is safe.</span> We only read it, and never see your password.
        </p>
        <span className="inline-flex items-center gap-1.5 text-sm text-ink-muted">
          <Mail className="h-4 w-4" /> Questions? Contact your Aquarient consultant.
        </span>
      </div>
    </div>
  );
}

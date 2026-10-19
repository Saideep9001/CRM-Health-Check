import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowRight,
  BarChart3,
  Check,
  ChevronDown,
  ClipboardList,
  Cloud,
  FileBarChart,
  Gauge,
  History,
  KeyRound,
  Layers,
  ListChecks,
  Lock,
  Menu,
  Play,
  Rocket,
  ShieldCheck,
  SlidersHorizontal,
  Target,
  Undo2,
  X,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useMe, useAuthStatus } from '@/api/queries';
import { ThemeToggle } from '@/components/layout/Header';
import { HeroVisual } from '@/components/marketing/HeroVisual';
import { ComingSoonBadge, ReleaseBadge } from '@/components/ui/Badges';
import { BrandMark } from '@/components/ui/Brand';
import { InfoTip } from '@/components/ui/HelpTip';
import { LinkButton } from '@/components/ui/Button';
import { CategoryTile } from '@/components/ui/CategoryIcon';
import { CATEGORIES, CATEGORY_COLORS, DIAGNOSTIC_AREAS, getAreaRelease, getAreasForCategory } from '@/config/categories';
import { cx } from '@/lib/format';

const NAV = [
  { href: '#platform', label: 'Platform' },
  { href: '#categories', label: 'What we check' },
  { href: '#how-it-works', label: 'How it works' },
  { href: '#security', label: 'Security' },
  { href: '#faq', label: 'FAQ' },
];

const MVP_CATEGORY_COUNT = CATEGORIES.filter((c) => c.release === 'mvp').length;
const MVP_AREA_COUNT = DIAGNOSTIC_AREAS.filter((a) => getAreaRelease(a) === 'mvp').length;

const FACTS = [
  { value: String(CATEGORIES.length), label: 'Topics we check' },
  { value: String(DIAGNOSTIC_AREAS.length), label: 'Areas we check' },
  { value: String(MVP_AREA_COUNT), label: 'Ready to check today' },
  { value: 'Read-only', label: 'We never change your data' },
];

const FEATURES = [
  { icon: Gauge, title: 'Health score', text: 'One score out of 100, plus a score for each topic.' },
  { icon: ListChecks, title: 'Problems in order', text: 'See the most urgent problems first.' },
  { icon: Target, title: 'Clear fixes', text: 'Every problem comes with a simple fix.' },
  { icon: ClipboardList, title: 'Track your fixes', text: 'Mark problems as fixed and add notes.' },
  { icon: FileBarChart, title: 'Easy reports', text: 'Print or download reports to share.' },
  { icon: History, title: 'Progress over time', text: 'Check again later to see your score improve.' },
];

const STEPS = [
  { icon: Cloud, title: 'Connect Salesforce', text: 'Sign in on Salesforce’s own page. It takes about a minute.' },
  { icon: SlidersHorizontal, title: 'Choose what to check', text: 'Keep everything selected, or pick the topics you want.' },
  { icon: Play, title: 'Run the check', text: 'It runs by itself. You can leave the page.' },
  { icon: Rocket, title: 'Fix what matters', text: 'Start with the most urgent problems.' },
];

const SECURITY = [
  { icon: KeyRound, title: 'No passwords', text: 'You sign in on Salesforce. We never see your password.' },
  { icon: Lock, title: 'Keys kept safe', text: 'Access keys stay on our server, not in your browser.' },
  { icon: ShieldCheck, title: 'Read-only', text: 'We look at your data. We never change or delete it.' },
  { icon: Undo2, title: 'Leave any time', text: 'Disconnect whenever you want.' },
];

const FAQ = [
  {
    q: 'Which Salesforce does it work with?',
    a: 'Salesforce Sales Cloud, including test copies.',
  },
  {
    q: 'Will it change anything in our Salesforce?',
    a: 'No. It only reads your data. Nothing is changed or deleted.',
  },
  {
    q: 'What can be checked today?',
    a: `${MVP_CATEGORY_COUNT} of the 6 topics. The other 2 are coming soon — you can already see what they will cover.`,
  },
  {
    q: 'Does it use up our Salesforce limits?',
    a: 'A little. You can see how much is left on the Connect page.',
  },
  {
    q: 'Can we check again later?',
    a: 'Yes. Every check is saved, so you can compare your scores over time.',
  },
  {
    q: 'How do we get access?',
    a: 'Ask your Aquarient consultant to set you up.',
  },
];

function Section({ id, eyebrow, title, intro, children, className }: { id?: string; eyebrow: string; title: string; intro?: string; children: ReactNode; className?: string }) {
  return (
    <section id={id} className={cx('scroll-mt-20 px-4 py-20 sm:px-6 lg:py-24', className)}>
      <div className="mx-auto max-w-6xl">
        <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-80px' }} transition={{ duration: 0.5 }} className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-brand">{eyebrow}</p>
          <h2 className="mt-2 inline-flex items-center gap-2 text-3xl font-semibold tracking-tight sm:text-4xl">
            {title}
            {intro && (
              <InfoTip size="md" align="center" label="More about this">
                {intro}
              </InfoTip>
            )}
          </h2>
        </motion.div>
        <div className="mt-12">{children}</div>
      </div>
    </section>
  );
}

function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  return (
    <motion.div initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-60px' }} transition={{ duration: 0.45, delay }} className={className}>
      {children}
    </motion.div>
  );
}

function SiteHeader() {
  const AUTH_REQUIRED = useAuthStatus().data?.authRequired ?? true;
  const me = useMe();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);
  const signedIn = !AUTH_REQUIRED || !!me.data;

  return (
    <header className={cx('sticky top-0 z-40 transition-colors', scrolled ? 'border-b border-line bg-surface/85 backdrop-blur-md' : 'bg-transparent')}>
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
        <Link to="/" aria-label="Aquarient home">
          <BrandMark />
        </Link>
        <nav className="hidden flex-1 items-center justify-center gap-1 md:flex" aria-label="Sections">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className="rounded-md px-3 py-2 text-sm font-medium text-ink-muted transition hover:bg-muted hover:text-ink">
              {n.label}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2 md:ml-0">
          <ThemeToggle />
          {signedIn ? (
            <LinkButton to="/dashboard" variant="primary" size="sm" iconRight={<ArrowRight className="h-3.5 w-3.5" />}>
              Open dashboard
            </LinkButton>
          ) : (
            <>
              <LinkButton to="/login" variant="ghost" size="sm" className="hidden sm:inline-flex">
                Sign in
              </LinkButton>
              <LinkButton to="/login" variant="primary" size="sm">
                Get started
              </LinkButton>
            </>
          )}
          <button className="rounded-md p-2 text-ink-muted hover:bg-muted md:hidden" onClick={() => setOpen((o) => !o)} aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open}>
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
      <AnimatePresence>
        {open && (
          <motion.nav initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden border-t border-line bg-surface md:hidden">
            <div className="space-y-1 px-4 py-3">
              {NAV.map((n) => (
                <a key={n.href} href={n.href} onClick={() => setOpen(false)} className="block rounded-md px-3 py-2 text-sm font-medium text-ink-muted hover:bg-muted hover:text-ink">
                  {n.label}
                </a>
              ))}
            </div>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}

function FaqItem({ q, a, open, onToggle }: { q: string; a: string; open: boolean; onToggle: () => void }) {
  return (
    <div className="border-b border-line last:border-0">
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-center justify-between gap-4 py-5 text-left">
        <span className="text-[15px] font-semibold">{q}</span>
        <ChevronDown className={cx('h-5 w-5 shrink-0 text-ink-subtle transition-transform duration-200', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <p className="pb-5 pr-8 text-sm leading-relaxed text-ink-muted">{a}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function HomePage() {
  const AUTH_REQUIRED = useAuthStatus().data?.authRequired ?? true;
  const APP_ENTRY_PATH = AUTH_REQUIRED ? '/login' : '/dashboard';
  const [faqOpen, setFaqOpen] = useState<number | null>(0);
  const [activeCat, setActiveCat] = useState(CATEGORIES[0].id);
  const cat = CATEGORIES.find((c) => c.id === activeCat)!;

  useEffect(() => {
    document.title = 'Aquarient CRM Health — Salesforce Sales Cloud health & data quality';
    return () => {
      document.title = 'Aquarient CRM Health';
    };
  }, []);

  return (
    <div className="min-h-screen bg-bg">
      <SiteHeader />

      {/* ---------------- Hero ---------------- */}
      <section className="relative overflow-hidden px-4 pb-20 pt-10 sm:px-6 lg:pb-28 lg:pt-16">
        <div
          className="pointer-events-none absolute inset-0 opacity-60 dark:opacity-40"
          style={{
            backgroundImage: 'radial-gradient(circle at 1px 1px, rgb(var(--line)) 1px, transparent 0)',
            backgroundSize: '24px 24px',
            maskImage: 'radial-gradient(ellipse at 50% 30%, black 20%, transparent 70%)',
            WebkitMaskImage: 'radial-gradient(ellipse at 50% 30%, black 20%, transparent 70%)',
          }}
        />
        <div className="relative mx-auto grid max-w-6xl items-center gap-12 lg:grid-cols-[1.05fr,1fr]">
          <div>
            <motion.span initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-muted shadow-card">
              <span className="h-1.5 w-1.5 rounded-full bg-good" />
              Salesforce health check
            </motion.span>
            <motion.h1 initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }} className="mt-5 text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl lg:text-[56px]">
              Know exactly how healthy your{' '}
              <span className="bg-gradient-to-r from-brand to-accent bg-clip-text text-transparent">Salesforce CRM</span> is.
            </motion.h1>
            <motion.p initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }} className="mt-5 max-w-xl text-lg leading-relaxed text-ink-muted">
              We check your Salesforce for problems and show you what to fix first.
            </motion.p>
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="mt-8 flex flex-wrap gap-3">
              <LinkButton to={APP_ENTRY_PATH} variant="primary" className="h-11 px-6 text-[15px]" iconRight={<ArrowRight className="h-4 w-4" />}>
                {AUTH_REQUIRED ? 'Sign in to your workspace' : 'Open the platform'}
              </LinkButton>
              <a href="#how-it-works" className="inline-flex h-11 items-center gap-2 rounded-lg border border-line bg-surface px-6 text-[15px] font-medium transition hover:bg-muted">
                See how it works
              </a>
            </motion.div>
            <motion.ul initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }} className="mt-8 grid gap-2 text-sm text-ink-muted sm:grid-cols-2">
              {['We only read your data', 'Nothing is ever changed', 'Clear list of problems', 'Easy-to-share reports'].map((t) => (
                <li key={t} className="flex items-center gap-2">
                  <Check className="h-4 w-4 shrink-0 text-good" /> {t}
                </li>
              ))}
            </motion.ul>
          </div>
          <HeroVisual />
        </div>
      </section>

      {/* ---------------- Facts strip ---------------- */}
      <div className="border-y border-line bg-surface px-4 sm:px-6">
        <dl className="mx-auto grid max-w-6xl grid-cols-2 divide-line md:grid-cols-4 md:divide-x">
          {FACTS.map((f, i) => (
            <Reveal key={f.label} delay={i * 0.06} className="flex flex-col-reverse px-4 py-8 text-center">
              <dt className="mt-1 text-sm text-ink-muted">{f.label}</dt>
              <dd className="text-3xl font-semibold tracking-tight">{f.value}</dd>
            </Reveal>
          ))}
        </dl>
      </div>

      {/* ---------------- Platform / features ---------------- */}
      <Section
        id="platform"
        eyebrow="What you get"
        title="Know what to fix, and why"
        intro="A simple, clear view of how healthy your Salesforce is."
      >
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={i * 0.05}>
              <motion.div whileHover={{ y: -4 }} className="card h-full p-6">
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-ink">
                  <f.icon className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-base font-semibold">{f.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{f.text}</p>
              </motion.div>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ---------------- Categories explorer ---------------- */}
      <Section
        id="categories"
        eyebrow="What we check"
        title={`${CATEGORIES.length} topics. ${DIAGNOSTIC_AREAS.length} areas.`}
        intro="Click a topic to see what it covers."
        className="bg-surface"
      >
        <div className="grid gap-6 lg:grid-cols-[320px,1fr]">
          <div className="flex gap-2 overflow-x-auto pb-2 lg:flex-col lg:overflow-visible lg:pb-0" role="tablist" aria-label="Assessment categories">
            {CATEGORIES.map((c) => {
              const active = c.id === activeCat;
              return (
                <button
                  key={c.id}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setActiveCat(c.id)}
                  className={cx(
                    'relative flex shrink-0 items-center gap-3 rounded-xl border px-4 py-3 text-left transition lg:w-full',
                    active ? 'border-transparent shadow-pop' : 'border-line hover:bg-muted',
                  )}
                >
                  {active && <motion.span layoutId="home-cat" className="absolute inset-0 rounded-xl border-2 bg-bg" style={{ borderColor: CATEGORY_COLORS[c.id] }} transition={{ type: 'spring', stiffness: 400, damping: 34 }} />}
                  <span className="relative">
                    <CategoryTile id={c.id} size="sm" />
                  </span>
                  <span className="relative min-w-0">
                    <span className="block whitespace-nowrap text-sm font-semibold lg:whitespace-normal">{c.name}</span>
                    <span className="block text-xs text-ink-subtle">
                      {c.areaIds.length} areas{c.release === 'coming-soon' ? ' · Coming Soon' : ''}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          <AnimatePresence mode="wait">
            <motion.div key={cat.id} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.22 }} className="card overflow-hidden" role="tabpanel">
              <div className="h-1.5" style={{ background: CATEGORY_COLORS[cat.id] }} />
              <div className="p-6 lg:p-8">
                <div className="flex flex-wrap items-center gap-3">
                  <CategoryTile id={cat.id} size="lg" />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">Topic {cat.order}</p>
                    <h3 className="text-xl font-semibold tracking-tight">{cat.name}</h3>
                  </div>
                  <ReleaseBadge release={cat.release} />
                </div>
                <p className="mt-4 text-sm leading-relaxed text-ink-muted">{cat.purpose}</p>
                <ol className="mt-6 space-y-3">
                  {getAreasForCategory(cat.id).map((a, i) => (
                    <motion.li key={a.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 + i * 0.05 }} className="rounded-xl border border-line p-4">
                      <div className="flex items-start gap-3">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm font-bold text-white" style={{ background: CATEGORY_COLORS[cat.id] }}>
                          {a.number}
                        </span>
                        <div className="min-w-0">
                          <p className="text-sm font-semibold">{a.name}</p>
                          <p className="mt-0.5 text-sm text-ink-muted">{a.description}</p>
                          <div className="mt-2.5 flex flex-wrap gap-1.5">
                            {a.indicators.map((ind) => (
                              <span key={ind} className="rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium text-ink-muted">
                                {ind}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </motion.li>
                  ))}
                </ol>
                {cat.release === 'coming-soon' && (
                  <p className="mt-5 flex items-center gap-2 text-sm text-ink-muted">
                    <ComingSoonBadge /> You can check this topic in a later release.
                  </p>
                )}
              </div>
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {CATEGORIES.map((c) => (
            <button key={c.id} onClick={() => setActiveCat(c.id)} className="rounded-xl border border-line bg-bg p-3 text-left transition hover:-translate-y-0.5 hover:shadow-card">
              <div className="flex items-center justify-between">
                <Layers className="h-4 w-4" style={{ color: CATEGORY_COLORS[c.id] }} />
                <span className="text-lg font-semibold tabular-nums">{c.areaIds.length}</span>
              </div>
              <p className="mt-2 truncate text-xs font-medium text-ink-muted">{c.shortName}</p>
            </button>
          ))}
        </div>
      </Section>

      {/* ---------------- How it works ---------------- */}
      <Section id="how-it-works" eyebrow="How it works" title="Four simple steps" intro="No spreadsheets. No technical setup.">
        <div className="relative grid gap-6 md:grid-cols-2 lg:grid-cols-4">
          <div className="absolute left-0 right-0 top-7 hidden h-px bg-gradient-to-r from-transparent via-line to-transparent lg:block" aria-hidden="true" />
          {STEPS.map((s, i) => (
            <Reveal key={s.title} delay={i * 0.08} className="relative">
              <div className="relative mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-line bg-surface text-brand shadow-card lg:mx-0">
                <s.icon className="h-6 w-6" />
                <span className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-brand text-[11px] font-bold text-white">{i + 1}</span>
              </div>
              <h3 className="mt-5 text-center text-base font-semibold lg:text-left">{s.title}</h3>
              <p className="mt-1.5 text-center text-sm leading-relaxed text-ink-muted lg:text-left">{s.text}</p>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ---------------- Results preview ---------------- */}
      <section className="px-4 sm:px-6">
        <div className="mx-auto grid max-w-6xl items-center gap-10 rounded-3xl border border-line bg-surface p-8 shadow-card lg:grid-cols-2 lg:p-12">
          <Reveal>
            <p className="text-xs font-semibold uppercase tracking-widest text-brand">Every problem shows</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">What’s wrong, and how to fix it</h2>
            <p className="mt-4 text-sm leading-relaxed text-ink-muted">
              Each problem is explained simply, with what to do next.
            </p>
            <LinkButton to={AUTH_REQUIRED ? '/login' : '/results'} variant="primary" className="mt-6" iconRight={<ArrowRight className="h-4 w-4" />}>
              {AUTH_REQUIRED ? 'Sign in to view results' : 'View results'}
            </LinkButton>
          </Reveal>
          <Reveal delay={0.1}>
            <div className="rounded-2xl border border-line bg-bg p-5">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">Finding anatomy</span>
                <BarChart3 className="h-4 w-4 text-ink-subtle" />
              </div>
              <ul className="mt-4 space-y-3">
                {[
                  ['Urgency', 'Critical, High, Medium, or Low'],
                  ['Topic & area', 'Where the problem is'],
                  ['Records affected', 'How many records have it'],
                  ['Why it matters', 'How it affects your sales'],
                  ['How to fix it', 'A clear next step'],
                  ['When to fix it', 'P1 (now) to P4 (later)'],
                ].map(([k, v], i) => (
                  <motion.li key={k} initial={{ opacity: 0, x: 10 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} transition={{ delay: 0.15 + i * 0.06 }} className="flex items-start gap-3 rounded-lg bg-surface p-3 shadow-card">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-good" />
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold">{k}</span>
                      <span className="block text-xs text-ink-muted">{v}</span>
                    </span>
                  </motion.li>
                ))}
              </ul>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------------- Security ---------------- */}
      <Section id="security" eyebrow="Safety" title="Safe for your live Salesforce" intro="We only read what we need. Nothing more.">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {SECURITY.map((s, i) => (
            <Reveal key={s.title} delay={i * 0.06}>
              <div className="card h-full p-6">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-good-soft text-good">
                  <s.icon className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-sm font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{s.text}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ---------------- FAQ ---------------- */}
      <Section id="faq" eyebrow="FAQ" title="Common questions" className="bg-surface">
        <div className="mx-auto max-w-3xl rounded-2xl border border-line bg-bg px-6">
          {FAQ.map((f, i) => (
            <FaqItem key={f.q} q={f.q} a={f.a} open={faqOpen === i} onToggle={() => setFaqOpen(faqOpen === i ? null : i)} />
          ))}
        </div>
      </Section>

      {/* ---------------- CTA ---------------- */}
      <section className="px-4 py-20 sm:px-6">
        <Reveal className="relative mx-auto max-w-5xl overflow-hidden rounded-3xl bg-brand px-8 py-14 text-center text-white shadow-pop">
          <div className="pointer-events-none absolute -left-20 -top-20 h-72 w-72 animate-floaty rounded-full bg-white/10 blur-2xl" />
          <div className="pointer-events-none absolute -bottom-24 -right-16 h-72 w-72 animate-floaty rounded-full bg-accent/30 blur-2xl" />
          <h2 className="relative text-3xl font-semibold tracking-tight sm:text-4xl">Ready to check your Salesforce?</h2>
          <p className="relative mx-auto mt-3 max-w-xl text-white/80">
            {AUTH_REQUIRED ? 'Sign in to your Aquarient workspace' : 'Open the platform'} to connect Salesforce and run your first check.
          </p>
          <div className="relative mt-8 flex flex-wrap justify-center gap-3">
            <Link to={APP_ENTRY_PATH} className="inline-flex h-11 items-center gap-2 rounded-lg bg-white px-6 text-[15px] font-semibold text-brand-ink shadow transition hover:bg-white/90">
              {AUTH_REQUIRED ? 'Sign in' : 'Open the platform'} <ArrowRight className="h-4 w-4" />
            </Link>
            <a href="#categories" className="inline-flex h-11 items-center rounded-lg border border-white/40 px-6 text-[15px] font-medium text-white transition hover:bg-white/10">
              Explore the diagnostics
            </a>
          </div>
        </Reveal>
      </section>

      {/* ---------------- Footer ---------------- */}
      <footer className="border-t border-line bg-surface px-4 py-12 sm:px-6">
        <div className="mx-auto grid max-w-6xl gap-8 sm:grid-cols-2 lg:grid-cols-4">
          <div className="lg:col-span-2">
            <BrandMark />
            <p className="mt-3 max-w-sm text-sm text-ink-muted">Salesforce health checks by Aquarient Technologies.</p>
          </div>
          <div>
            <p className="label">Product</p>
            <ul className="mt-3 space-y-2 text-sm">
              {NAV.slice(0, 3).map((n) => (
                <li key={n.href}>
                  <a href={n.href} className="text-ink-muted hover:text-ink">
                    {n.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="label">Account</p>
            <ul className="mt-3 space-y-2 text-sm">
              <li>
                <Link to={APP_ENTRY_PATH} className="text-ink-muted hover:text-ink">
                  {AUTH_REQUIRED ? 'Sign in' : 'Open the platform'}
                </Link>
              </li>
              <li>
                <a href="#security" className="text-ink-muted hover:text-ink">
                  Security
                </a>
              </li>
              <li>
                <a href="#faq" className="text-ink-muted hover:text-ink">
                  FAQ
                </a>
              </li>
            </ul>
          </div>
        </div>
        <div className="mx-auto mt-10 flex max-w-6xl flex-wrap justify-between gap-2 border-t border-line pt-6 text-xs text-ink-subtle">
          <span>© {new Date().getFullYear()} Aquarient Technologies LLC. All rights reserved.</span>
          <span>Salesforce and Sales Cloud are trademarks of Salesforce, Inc.</span>
        </div>
      </footer>
    </div>
  );
}

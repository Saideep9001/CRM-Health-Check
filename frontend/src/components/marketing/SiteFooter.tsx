import { motion } from 'framer-motion';
import { ArrowRight, ArrowUp, CircleHelp, ClipboardCheck, Gauge, Layers, Lock, LogIn, Route, ShieldCheck, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useApiHealth } from '@/api/queries';
import { BrandMark } from '@/components/ui/Brand';
import { CATEGORIES, DIAGNOSTIC_AREAS } from '@/config/categories';

const EASE = [0.16, 1, 0.3, 1] as const;

/** A footer link as a small row: icon tile, title and a one-line hint; lights up and slides on hover. */
function FooterLink({ icon: Icon, title, hint, href, to, index }: { icon: LucideIcon; title: string; hint: string; href?: string; to?: string; index: number }) {
  const cls = 'group relative flex items-center gap-3 rounded-xl border border-transparent px-3 py-2.5 transition-all duration-200 hover:border-white/10 hover:bg-white/[0.06]';
  const inner = (
    <>
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white/[0.07] text-[#5fd3ff] ring-1 ring-white/10 transition-all duration-200 group-hover:bg-[#058CC9] group-hover:text-white group-hover:shadow-[0_0_18px_rgba(37,170,225,0.55)]">
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-white/90 transition-colors group-hover:text-white">{title}</span>
        <span className="block truncate text-xs text-white/50">{hint}</span>
      </span>
      <ArrowRight className="h-4 w-4 shrink-0 -translate-x-2 text-[#5fd3ff] opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100" />
    </>
  );
  return (
    <motion.li initial={{ opacity: 0, x: -10 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} transition={{ duration: 0.4, delay: 0.1 + index * 0.07, ease: EASE }}>
      {to ? <Link to={to} className={cls}>{inner}</Link> : <a href={href} className={cls}>{inner}</a>}
    </motion.li>
  );
}

function Column({ title, children, delay }: { title: string; children: ReactNode; delay: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5, delay, ease: EASE }}>
      <p className="flex items-center gap-2 px-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#5fd3ff]">
        <span className="h-px w-4 bg-[#5fd3ff]/60" />
        {title}
      </p>
      <ul className="mt-3 space-y-1">{children}</ul>
    </motion.div>
  );
}

/** Is the platform's API answering right now? Shown as a small live status. */
function PlatformStatus() {
  const health = useApiHealth();
  const ok = !!health.data;
  const label = health.isLoading ? 'Checking platform status…' : ok ? 'All systems operational' : 'Platform unreachable right now';
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-white/80">
      <span className="relative flex h-2 w-2">
        {ok && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
        <span className={ok ? 'relative inline-flex h-2 w-2 rounded-full bg-emerald-400' : 'relative inline-flex h-2 w-2 rounded-full bg-amber-400'} />
      </span>
      {label}
    </span>
  );
}

export function SiteFooter({ nav, entryPath, entryLabel }: { nav: { href: string; label: string }[]; entryPath: string; entryLabel: string }) {
  const HINTS: Record<string, { icon: LucideIcon; hint: string }> = {
    '#platform': { icon: Gauge, hint: 'Score, problems and fixes' },
    '#categories': { icon: ClipboardCheck, hint: `${CATEGORIES.length} topics · ${DIAGNOSTIC_AREAS.length} areas` },
    '#how-it-works': { icon: Route, hint: 'Connect, check, fix' },
  };
  const product = nav.slice(0, 3).map((n) => ({ title: n.label, href: n.href, icon: HINTS[n.href]?.icon ?? Gauge, hint: HINTS[n.href]?.hint ?? '' }));
  const trust = [
    { icon: ShieldCheck, text: 'Read-only access' },
    { icon: Lock, text: 'Keys encrypted on our server' },
    { icon: Layers, text: `${DIAGNOSTIC_AREAS.length} areas checked` },
  ];

  return (
    <footer className="relative overflow-hidden bg-[#03294d] text-white">
      {/* soft brand glows */}
      <div className="pointer-events-none absolute -left-32 top-0 h-80 w-80 rounded-full bg-[#058CC9]/25 blur-3xl" aria-hidden="true" />
      <div className="pointer-events-none absolute -right-24 bottom-0 h-72 w-72 rounded-full bg-[#25AAE1]/15 blur-3xl" aria-hidden="true" />

      {/* heartbeat line that draws itself when the footer scrolls into view */}
      <svg viewBox="0 0 1200 40" preserveAspectRatio="none" className="relative block h-10 w-full" aria-hidden="true">
        <motion.path
          d="M0 24 H470 L492 24 L506 6 L522 36 L538 14 L550 24 H1200"
          fill="none"
          stroke="#25AAE1"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
          initial={{ pathLength: 0, opacity: 0.4 }}
          whileInView={{ pathLength: 1, opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 1.8, ease: EASE }}
        />
      </svg>

      <div className="relative mx-auto max-w-6xl px-4 pb-8 pt-10 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[1.6fr,1fr,1fr]">
          <motion.div initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5, ease: EASE }}>
            <BrandMark onDark />
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-white/70">
              Salesforce health checks by Aquarient Technologies — a clear score, the problems that matter, and how to fix them.
            </p>
            <ul className="mt-5 flex flex-wrap gap-2">
              {trust.map((t) => (
                <li key={t.text} className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-white/80">
                  <t.icon className="h-3.5 w-3.5 text-[#5fd3ff]" />
                  {t.text}
                </li>
              ))}
            </ul>
            <div className="mt-5">
              <PlatformStatus />
            </div>
          </motion.div>

          <Column title="Product" delay={0.08}>
            {product.map((l, i) => (
              <FooterLink key={l.title} index={i} icon={l.icon} title={l.title} hint={l.hint} href={l.href} />
            ))}
          </Column>

          <Column title="Account" delay={0.16}>
            <FooterLink index={0} icon={LogIn} title={entryLabel} hint="Open your workspace" to={entryPath} />
            <FooterLink index={1} icon={ShieldCheck} title="Security" hint="How we keep your data safe" href="#security" />
            <FooterLink index={2} icon={CircleHelp} title="FAQ" hint="Common questions, answered" href="#faq" />
          </Column>
        </div>

        <div className="mt-12 flex flex-col gap-4 border-t border-white/10 pt-6 text-xs text-white/50 sm:flex-row sm:items-center sm:justify-between">
          <span>© {new Date().getFullYear()} Aquarient Technologies LLC. All rights reserved.</span>
          <div className="flex flex-wrap items-center gap-4">
            <span>Salesforce and Sales Cloud are trademarks of Salesforce, Inc.</span>
            <button
              onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
              className="group inline-flex items-center gap-1.5 rounded-full border border-white/15 px-3 py-1.5 text-white/70 transition hover:border-white/40 hover:bg-white/5 hover:text-white"
            >
              <ArrowUp className="h-3.5 w-3.5 transition-transform duration-200 group-hover:-translate-y-0.5" />
              Back to top
            </button>
          </div>
        </div>
      </div>
    </footer>
  );
}

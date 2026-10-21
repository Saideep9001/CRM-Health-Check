import { AnimatePresence, motion } from 'framer-motion';
import { ArrowLeft, ArrowRight, Cloud, ListChecks, Play, Sparkles, type LucideIcon } from 'lucide-react';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { cx } from '@/lib/format';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Overlay';

const SEEN_KEY = 'aq-tour-seen';

interface Slide {
  icon: LucideIcon;
  color: string;
  title: string;
  body: string;
  points: string[];
}

const SLIDES: Slide[] = [
  {
    icon: Sparkles,
    color: 'rgb(var(--brand))',
    title: 'Welcome to your CRM Health Check',
    body: 'We check your Salesforce and tell you what to fix first.',
    points: ['A score from 0 to 100', 'Problems, most urgent first', 'A fix for each one'],
  },
  {
    icon: Cloud,
    color: '#00a1e0',
    title: 'Step 1 — Connect your Salesforce',
    body: 'Sign in on Salesforce’s own page. We only read your data.',
    points: ['Takes a minute', 'Works with test copies too', 'Disconnect any time'],
  },
  {
    icon: Play,
    color: 'rgb(var(--accent))',
    title: 'Step 2 — Run a health check',
    body: 'Keep the defaults and press Start.',
    points: ['Defaults already set', 'You can leave the page', 'Run again later'],
  },
  {
    icon: ListChecks,
    color: 'rgb(var(--good))',
    title: 'Step 3 — Read your results',
    body: 'See your score, then fix the problems.',
    points: ['Urgent ones first', 'Mark them as fixed', 'Share a report'],
  },
];

const Ctx = createContext<{ open: () => void } | null>(null);

/** Hosts the welcome tour; opens automatically on a user's first visit. */
export function WelcomeTourProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const [i, setI] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    try {
      if (!localStorage.getItem(SEEN_KEY)) setOpen(true);
    } catch {
      /* storage unavailable — don't auto-open */
    }
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    try {
      localStorage.setItem(SEEN_KEY, '1');
    } catch {
      /* ignore */
    }
  }, []);

  const open = useCallback(() => {
    setI(0);
    setOpen(true);
  }, []);

  const s = SLIDES[i];
  const last = i === SLIDES.length - 1;

  return (
    <Ctx.Provider value={{ open }}>
      {children}
      <Modal
        open={isOpen}
        onClose={close}
        title={`Quick tour · ${i + 1} of ${SLIDES.length}`}
        footer={
          <div className="flex w-full items-center justify-between gap-2">
            <button onClick={close} className="text-sm text-ink-muted hover:text-ink">
              Skip tour
            </button>
            <div className="flex gap-2">
              {i > 0 && (
                <Button icon={<ArrowLeft className="h-4 w-4" />} onClick={() => setI(i - 1)}>
                  Back
                </Button>
              )}
              {last ? (
                <Button
                  variant="primary"
                  icon={<Cloud className="h-4 w-4" />}
                  onClick={() => {
                    close();
                    navigate('/connection');
                  }}
                >
                  Connect Salesforce
                </Button>
              ) : (
                <Button variant="primary" iconRight={<ArrowRight className="h-4 w-4" />} onClick={() => setI(i + 1)}>
                  Next
                </Button>
              )}
            </div>
          </div>
        }
      >
        <AnimatePresence mode="wait">
          <motion.div key={i} initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -16 }} transition={{ duration: 0.2 }}>
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl text-white shadow" style={{ background: s.color }}>
              <s.icon className="h-7 w-7" />
            </span>
            <h3 className="mt-4 text-lg font-semibold">{s.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-muted">{s.body}</p>
            <ul className="mt-4 space-y-2">
              {s.points.map((p) => (
                <li key={p} className="flex items-center gap-2 text-sm">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: s.color }} />
                  {p}
                </li>
              ))}
            </ul>
          </motion.div>
        </AnimatePresence>
        <div className="mt-6 flex justify-center gap-1.5" aria-hidden="true">
          {SLIDES.map((_, n) => (
            <button key={n} onClick={() => setI(n)} className={cx('h-1.5 rounded-full transition-all', n === i ? 'w-6 bg-brand' : 'w-1.5 bg-line')} tabIndex={-1} />
          ))}
        </div>
      </Modal>
    </Ctx.Provider>
  );
}

export function useWelcomeTour() {
  const c = useContext(Ctx);
  if (!c) throw new Error('useWelcomeTour must be used within WelcomeTourProvider');
  return c;
}

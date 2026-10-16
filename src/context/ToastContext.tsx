import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle2, Info, TriangleAlert, X } from 'lucide-react';
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

type Tone = 'info' | 'success' | 'warning';
interface Toast {
  id: number;
  title: string;
  body?: string;
  tone: Tone;
}

const Ctx = createContext<{ notify: (title: string, body?: string, tone?: Tone) => void } | null>(null);

const icons = { info: Info, success: CheckCircle2, warning: TriangleAlert };
const tones = { info: 'text-brand', success: 'text-good', warning: 'text-warn' };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));

  const notify = useCallback((title: string, body?: string, tone: Tone = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, title, body, tone }]);
    setTimeout(() => dismiss(id), 4500);
  }, []);

  return (
    <Ctx.Provider value={{ notify }}>
      {children}
      <div
        className="pointer-events-none fixed bottom-24 right-4 z-[70] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2"
        aria-live="polite"
      >
        <AnimatePresence>
          {toasts.map((t) => {
            const Icon = icons[t.tone];
            return (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, y: 16, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, x: 40 }}
                className="card pointer-events-auto flex items-start gap-3 p-3.5 shadow-pop"
                role="status"
              >
                <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${tones[t.tone]}`} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{t.title}</p>
                  {t.body && <p className="mt-0.5 text-sm text-ink-muted">{t.body}</p>}
                </div>
                <button
                  onClick={() => dismiss(t.id)}
                  className="rounded p-0.5 text-ink-subtle hover:text-ink"
                  aria-label="Dismiss"
                >
                  <X className="h-4 w-4" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const c = useContext(Ctx);
  if (!c) throw new Error('useToast must be used within ToastProvider');
  return c;
}

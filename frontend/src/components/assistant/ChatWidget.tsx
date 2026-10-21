import { AnimatePresence, motion } from 'framer-motion';
import { Bot, ExternalLink, MessageCircle, RotateCcw, Send, X } from 'lucide-react';
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { assistantApi } from '@/api/assistant';
import { useAssessments, useConnection } from '@/api/queries';
import { answer, isDataQuestion, welcomeMessage, type GuideContext } from '@/assistant/guide';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { errorMessage } from '@/api/client';
import { cx, fmtDateTime } from '@/lib/format';
import type { CrmAnswer } from '@/types';

interface Msg {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  suggestions?: string[];
  source?: 'guide' | 'data';
  pending?: boolean;
}

const STORE_KEY = 'aq-assistant-chat';
let seq = Date.now();

/** Turns a live Salesforce answer into chat text with record links. */
function formatCrmAnswer(a: CrmAnswer): string {
  const lines = [`**${a.title}**`, a.summary];
  for (const r of a.rows) {
    const label = r.url ? `[${r.label.replace(/[[\]]/g, '')}](${r.url})` : `**${r.label}**`;
    lines.push(`- ${label}${r.detail ? ` — ${r.detail}` : ''}`);
  }
  if (a.id === 'group') lines.push(a.total !== null && a.rows.length >= 8 ? 'Showing the 8 largest groups.' : '');
  else if (a.total !== null && a.rows.length && a.total > a.rows.length) lines.push(`Showing ${a.rows.length} of ${a.total.toLocaleString('en-US')}.`);
  const links = [a.appUrl ? `[See all in Your Data](${a.appUrl})` : '', a.salesforceUrl ? `[Open in Salesforce](${a.salesforceUrl})` : ''].filter(Boolean);
  if (links.length) lines.push(links.join(' · '));
  lines.push(`Live from Salesforce · ${fmtDateTime(a.asOf)}`);
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Markdown-lite rendering: paragraphs, "- " bullets, **bold**, [label](/path).
// In-app paths navigate inside the app; https links (Salesforce records) open in a new tab.
// ---------------------------------------------------------------------------

const LINK_CLASS = 'font-medium text-brand underline decoration-brand/30 underline-offset-2 hover:decoration-brand';

function Inline({ text, onLink }: { text: string; onLink: (to: string) => void }) {
  const parts: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|\[([^\]]+)\]\((\/[^)\s]*|https:\/\/[^)\s]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[1]) parts.push(<strong key={m.index} className="font-semibold">{m[1]}</strong>);
    else if (m[3].startsWith('https://')) {
      parts.push(
        <a key={m.index} href={m[3]} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
          {m[2]}
          <ExternalLink className="ml-0.5 inline h-3 w-3 align-[-1px]" aria-hidden="true" />
        </a>,
      );
    } else {
      const to = m[3];
      parts.push(
        <button key={m.index} onClick={() => onLink(to)} className={LINK_CLASS}>
          {m[2]}
        </button>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

function RichText({ text, onLink }: { text: string; onLink: (to: string) => void }) {
  const blocks: ReactNode[] = [];
  const lines = text.split('\n');
  let bullets: string[] = [];
  const flush = (key: number) => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={`ul${key}`} className="my-1 space-y-1 pl-4">
        {bullets.map((b, i) => (
          <li key={i} className="list-disc marker:text-ink-subtle">
            <Inline text={b} onLink={onLink} />
          </li>
        ))}
      </ul>,
    );
    bullets = [];
  };
  lines.forEach((line, i) => {
    const t = line.trim();
    if (/^[-•*]\s+/.test(t)) bullets.push(t.replace(/^[-•*]\s+/, ''));
    else {
      flush(i);
      if (t) blocks.push(<p key={i} className="my-1"><Inline text={t} onLink={onLink} /></p>);
    }
  });
  flush(lines.length);
  return <>{blocks}</>;
}

function TypingDots() {
  return (
    <span className="inline-flex gap-1 py-1" aria-label="Assistant is typing">
      {[0, 1, 2].map((i) => (
        <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-ink-subtle" animate={{ y: [0, -4, 0] }} transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.15 }} />
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------------

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(STORE_KEY) ?? '[]') as Msg[];
    } catch {
      return [];
    }
  });
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const conn = useConnection();
  const all = useAssessments();
  const { latest, findings, results } = useLatestAssessment();

  const ctx: GuideContext = useMemo(
    () => ({
      pathname,
      connection: conn.data ?? null,
      latest,
      findings,
      results: results ?? null,
      running: (all.data ?? []).some((a) => a.status === 'running' || a.status === 'queued'),
    }),
    [pathname, conn.data, latest, findings, results, all.data],
  );

  // Greet on first open.
  useEffect(() => {
    if (open && msgs.length === 0) {
      const w = welcomeMessage(ctx);
      setMsgs([{ id: ++seq, role: 'assistant', text: w.text, suggestions: w.suggestions, source: 'guide' }]);
    }
    if (open) setTimeout(() => inputRef.current?.focus(), 150);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(msgs.filter((m) => !m.pending).slice(-40)));
    } catch {
      /* per-tab convenience only */
    }
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [msgs]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const goTo = (to: string) => {
    navigate(to);
    if (window.innerWidth < 640) setOpen(false);
  };

  const patch = (id: number, p: Partial<Msg>) => setMsgs((ms) => ms.map((m) => (m.id === id ? { ...m, ...p } : m)));

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setInput('');
    const userMsg: Msg = { id: ++seq, role: 'user', text: q };
    const botId = ++seq;
    const history = [...msgs.filter((m) => !m.pending), userMsg];
    setMsgs([...history, { id: botId, role: 'assistant', text: '', pending: true }]);
    setBusy(true);

    const guideReply = () => {
      const a = answer(q, ctx);
      patch(botId, { text: a.text, suggestions: a.suggestions, pending: false, source: 'guide' });
    };

    // Questions about the org's own records go to the read-only data engine first; anything the
    // guide doesn't recognise gets a second chance there too.
    const guided = answer(q, ctx);
    const isConnected = ctx.connection?.status === 'connected';
    const dataFirst = isConnected && isDataQuestion(q, ctx);
    if (dataFirst || (isConnected && guided.fallback)) {
      const onObject = pathname.match(/^\/data\/([^/?#]+)/);
      try {
        const res = await assistantApi.answer({ question: q, context: onObject ? decodeURIComponent(onObject[1]) : undefined });
        if (res) {
          patch(botId, { text: formatCrmAnswer(res), suggestions: ['What can I ask about my data?', 'Open deals by stage', 'What should I fix first?'], pending: false, source: 'data' });
          setBusy(false);
          return;
        }
      } catch (e) {
        if (dataFirst && !guided.crm) {
          patch(botId, {
            text: `I couldn’t get that from Salesforce. ${errorMessage(e)}`,
            suggestions: ['Is my Salesforce connected?', 'What can I ask about my data?'],
            pending: false,
            source: 'guide',
          });
          setBusy(false);
          return;
        }
      }
    }

    // Fixed read-only lookups (also explain what's possible when Salesforce isn't connected).
    if (guided.crm) {
      try {
        const res = await assistantApi.crmQuery(guided.crm);
        patch(botId, { text: formatCrmAnswer(res), suggestions: guided.suggestions, pending: false, source: 'data' });
      } catch (e) {
        patch(botId, {
          text: `I couldn’t get that from Salesforce. ${errorMessage(e)}`,
          suggestions: ['Is my Salesforce connected?', 'What can I ask about my data?'],
          pending: false,
          source: 'guide',
        });
      }
      setBusy(false);
      return;
    }

    await new Promise((r) => setTimeout(r, 350 + Math.random() * 300));
    guideReply();
    setBusy(false);
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      ask(input);
    }
  };

  const reset = () => {
    const w = welcomeMessage(ctx);
    setMsgs([{ id: ++seq, role: 'assistant', text: w.text, suggestions: w.suggestions, source: 'guide' }]);
  };

  const lastBot = [...msgs].reverse().find((m) => m.role === 'assistant' && !m.pending);

  return (
    <>
      {/* Launcher */}
      <AnimatePresence>
        {!open && (
          <motion.button
            key="launcher"
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            whileHover={{ scale: 1.06 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => setOpen(true)}
            className="no-print fixed bottom-5 right-5 z-[55] flex h-14 items-center gap-2 rounded-full bg-brand pl-4 pr-5 text-white shadow-pop"
            aria-label="Open help assistant"
          >
            <span className="absolute inset-0 animate-pulse-ring rounded-full border-2 border-brand" aria-hidden="true" />
            <MessageCircle className="h-6 w-6" />
            <span className="hidden text-sm font-semibold sm:inline">Ask Aqua</span>
          </motion.button>
        )}
      </AnimatePresence>

      {/* Panel */}
      <AnimatePresence>
        {open && (
          <motion.div
            key="panel"
            role="dialog"
            aria-label="Help assistant"
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ type: 'spring', stiffness: 380, damping: 32 }}
            className="no-print fixed inset-x-2 bottom-2 top-16 z-[55] flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-pop sm:inset-x-auto sm:bottom-5 sm:right-5 sm:top-auto sm:h-[min(620px,calc(100vh-6rem))] sm:w-[400px]"
          >
            {/* Header */}
            <div className="flex items-center gap-3 bg-brand px-4 py-3 text-white">
              <span className="relative flex h-9 w-9 items-center justify-center rounded-full bg-white/15">
                <Bot className="h-5 w-5" />
                <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-brand bg-good" />
              </span>
              <div className="min-w-0 flex-1 leading-tight">
                <p className="text-sm font-semibold">Aqua · Help assistant</p>
                <p className="flex items-center gap-1 text-[11px] text-white/75">
                  Platform, results & your live data
                </p>
              </div>
              <button onClick={reset} className="rounded-md p-1.5 text-white/80 hover:bg-white/10 hover:text-white" aria-label="Start a new conversation" title="New conversation">
                <RotateCcw className="h-4 w-4" />
              </button>
              <button onClick={() => setOpen(false)} className="rounded-md p-1.5 text-white/80 hover:bg-white/10 hover:text-white" aria-label="Close assistant">
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Messages */}
            <div ref={listRef} className="scrollbar-thin flex-1 space-y-3 overflow-y-auto bg-bg px-4 py-4" aria-live="polite">
              {msgs.map((m) => (
                <motion.div key={m.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={cx('flex gap-2', m.role === 'user' && 'justify-end')}>
                  {m.role === 'assistant' && (
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-ink">
                      <Bot className="h-4 w-4" />
                    </span>
                  )}
                  <div
                    className={cx(
                      'max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed',
                      m.role === 'user' ? 'rounded-br-md bg-brand text-white' : 'rounded-bl-md border border-line bg-surface text-ink',
                    )}
                  >
                    {m.pending ? <TypingDots /> : m.role === 'user' ? m.text : <RichText text={m.text} onLink={goTo} />}
                  </div>
                </motion.div>
              ))}

              {/* Quick replies for the latest answer */}
              {!busy && lastBot?.suggestions && lastBot === msgs[msgs.length - 1] && (
                <div className="flex flex-wrap gap-2 pl-9">
                  {lastBot.suggestions.map((s) => (
                    <Fragment key={s}>
                      <button onClick={() => ask(s)} className="rounded-full border border-brand/30 bg-surface px-3 py-1.5 text-xs font-medium text-brand-ink transition hover:bg-brand-soft">
                        {s}
                      </button>
                    </Fragment>
                  ))}
                </div>
              )}
            </div>

            {/* Composer */}
            <div className="border-t border-line bg-surface p-3">
              <div className="flex items-end gap-2 rounded-xl border border-line bg-bg px-3 py-2 focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={onKeyDown}
                  rows={1}
                  maxLength={1000}
                  placeholder="Ask a question in your own words…"
                  aria-label="Message"
                  className="max-h-28 min-h-[24px] flex-1 resize-none border-0 bg-transparent py-1 text-sm leading-6 text-ink placeholder:text-ink-subtle focus:outline-none focus-visible:ring-0 focus-visible:ring-offset-0"
                />
                <button
                  onClick={() => ask(input)}
                  disabled={!input.trim() || busy}
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-white transition disabled:opacity-40"
                  aria-label="Send message"
                >
                  <Send className="h-4 w-4" />
                </button>
              </div>
              <p className="mt-1.5 text-center text-[10px] text-ink-subtle">Press Enter to send · Shift + Enter for a new line</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

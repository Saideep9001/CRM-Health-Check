import { animate, motion, useInView, useMotionValue, useTransform } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { fmtNumber, scoreBand } from '@/lib/format';

/** Number that counts up from 0 when it scrolls into view. */
export function AnimatedNumber({
  value,
  format = fmtNumber,
  duration = 1.1,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const mv = useMotionValue(0);
  const [text, setText] = useState(format(0));

  useEffect(() => {
    if (!inView) return;
    const controls = animate(mv, value, { duration, ease: [0.16, 1, 0.3, 1] });
    const unsub = mv.on('change', (v) => setText(format(Math.round(v))));
    return () => {
      controls.stop();
      unsub();
    };
  }, [inView, value]);

  return (
    <span ref={ref} className="tabular-nums">
      {text}
    </span>
  );
}

/** Circular score gauge that draws itself on mount. */
export function ScoreRing({
  score,
  size = 120,
  stroke = 10,
  label,
  showBand = true,
}: {
  score: number | null;
  size?: number;
  stroke?: number;
  label?: string;
  showBand?: boolean;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const band = scoreBand(score);
  const progress = useMotionValue(0);
  const offset = useTransform(progress, (p) => c * (1 - p / 100));

  useEffect(() => {
    const ctl = animate(progress, score ?? 0, { duration: 1.4, ease: [0.16, 1, 0.3, 1], delay: 0.15 });
    return () => ctl.stop();
  }, [score]);

  return (
    <div className="relative inline-flex flex-col items-center" style={{ width: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--muted))" strokeWidth={stroke} />
        {score !== null && (
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={band.color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={c}
            style={{ strokeDashoffset: offset }}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center" style={{ height: size }}>
        <span className="font-semibold tracking-tight" style={{ fontSize: size * 0.27 }}>
          {score === null ? '—' : <AnimatedNumber value={score} />}
        </span>
        {label && <span className="text-[11px] font-medium text-ink-subtle">{label}</span>}
      </div>
      {showBand && (
        <span className="mt-2 text-xs font-medium" style={{ color: band.color }}>
          {band.label}
        </span>
      )}
    </div>
  );
}

/** Horizontal bar that grows to its value. */
export function ProgressBar({
  value,
  color,
  height = 6,
  delay = 0,
}: {
  value: number;
  color?: string;
  height?: number;
  delay?: number;
}) {
  return (
    <div className="w-full overflow-hidden rounded-full bg-muted" style={{ height }}>
      <motion.div
        className="h-full rounded-full"
        style={{ background: color ?? scoreBand(value).color }}
        initial={{ width: 0 }}
        whileInView={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        viewport={{ once: true }}
        transition={{ duration: 1, ease: [0.16, 1, 0.3, 1], delay }}
      />
    </div>
  );
}

/** Tiny trend line for KPI cards, drawn with a path animation. */
export function Sparkline({ data, color = 'rgb(var(--brand))' }: { data: number[]; color?: string }) {
  const w = 96;
  const h = 32;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - 3 - ((v - min) / (max - min || 1)) * (h - 6);
    return [x, y] as const;
  });
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const last = pts[pts.length - 1];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <motion.path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1.2, ease: 'easeOut' }}
      />
      <motion.circle
        cx={last[0]}
        cy={last[1]}
        r={3}
        fill={color}
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ delay: 1.1 }}
      />
    </svg>
  );
}

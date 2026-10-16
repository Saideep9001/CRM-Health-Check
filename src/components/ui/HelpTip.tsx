/**
 * InfoTip — a small "i" icon that reveals a short explanation.
 * Opens on mouse hover, keyboard focus, and tap/click (touch screens);
 * closes on a second tap, a tap elsewhere, or Escape.
 *
 * The bubble is rendered in a portal on <body> with fixed positioning, so cards or
 * panels with `overflow: hidden` can never clip it. It is placed below the icon (or
 * above when there isn't room) and kept inside the screen edges.
 *
 * Usage:
 *   <InfoTip>Your overall CRM health score out of 100.</InfoTip>
 */
import { Info } from 'lucide-react';
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cx } from '@/lib/format';

type Side = 'top' | 'bottom';
type Align = 'center' | 'start' | 'end';

const EDGE = 8; // minimum gap from the screen edge
const GAP = 8; // gap between icon and bubble

export function InfoTip({
  children,
  side = 'bottom',
  align = 'start',
  size = 'sm',
  label = 'More information',
  className,
}: {
  children: ReactNode;
  side?: Side | 'right' | 'left';
  align?: Align;
  size?: 'sm' | 'md';
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false); // pinned by tap/click
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [style, setStyle] = useState<CSSProperties>({ position: 'fixed', top: -9999, left: -9999 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);
  const id = useId();
  const visible = open || hover || focus;
  const preferTop = side === 'top';

  const place = useCallback(() => {
    const btn = btnRef.current;
    const tip = tipRef.current;
    if (!btn || !tip) return;
    const b = btn.getBoundingClientRect();
    const w = tip.offsetWidth;
    const h = tip.offsetHeight;
    // Visible area excludes scrollbars (innerWidth includes them).
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;

    // Vertical: preferred side, flipped when it doesn't fit.
    const below = b.bottom + GAP;
    const above = b.top - GAP - h;
    let top = preferTop ? above : below;
    if (preferTop && above < EDGE && below + h <= vh - EDGE) top = below;
    if (!preferTop && below + h > vh - EDGE && above >= EDGE) top = above;

    // Horizontal: requested alignment, then clamped inside the screen.
    let left = align === 'center' ? b.left + b.width / 2 - w / 2 : align === 'end' ? b.right - w : b.left;
    left = Math.max(EDGE, Math.min(left, vw - EDGE - w));

    setStyle({ position: 'fixed', top: Math.round(top), left: Math.round(left) });
  }, [align, preferTop]);

  // Position before paint whenever the bubble appears.
  useLayoutEffect(() => {
    if (visible) place();
  }, [visible, place]);

  // Follow the icon on scroll/resize while open.
  useEffect(() => {
    if (!visible) return;
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [visible, place]);

  // Close a pinned bubble on outside tap or Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!btnRef.current?.contains(t) && !tipRef.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const mouseOnly = (fn: () => void) => (e: React.PointerEvent) => e.pointerType === 'mouse' && fn();

  return (
    <span className={cx('relative inline-flex shrink-0 items-center align-middle', className)}>
      <button
        ref={btnRef}
        type="button"
        aria-label={label}
        aria-expanded={visible}
        aria-describedby={visible ? id : undefined}
        onPointerEnter={mouseOnly(() => setHover(true))}
        onPointerLeave={mouseOnly(() => setHover(false))}
        onFocus={(e) => e.currentTarget.matches(':focus-visible') && setFocus(true)}
        onBlur={() => setFocus(false)}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className={cx(
          'inline-flex items-center justify-center rounded-full text-ink-subtle transition-colors hover:text-brand focus-visible:text-brand',
          visible && 'text-brand',
          size === 'md' ? 'h-5 w-5' : 'h-4 w-4',
        )}
      >
        <Info className={size === 'md' ? 'h-[18px] w-[18px]' : 'h-3.5 w-3.5'} aria-hidden="true" />
      </button>
      {visible &&
        createPortal(
          <span
            ref={tipRef}
            id={id}
            role="tooltip"
            style={style}
            onPointerEnter={mouseOnly(() => setHover(true))}
            onPointerLeave={mouseOnly(() => setHover(false))}
            className="z-[80] block w-64 max-w-[calc(100vw-1rem)] rounded-lg border border-line bg-surface px-3 py-2 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-ink shadow-pop"
          >
            {children}
          </span>,
          document.body,
        )}
    </span>
  );
}

/** Back-compat name used by the KPI cards. */
export const HelpTip = InfoTip;

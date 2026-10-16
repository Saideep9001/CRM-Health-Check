import { useId } from 'react';
import { cx } from '@/lib/format';

/*
 * Aquarient CRM Health logo — part of the Aquarient Technologies family:
 * the lowercase "aquarient" wordmark and the Aquarient wave, here drawn as a heartbeat (CRM health),
 * with "CRM HEALTH" in place of "TECHNOLOGIES". The icon is our own simple cloud (cloud CRM) — never the
 * Salesforce cloud, which partners may only show unaltered via the official Salesforce Partner badge.
 * Colours are Aquarient's: #25AAE1 → #058CC9 → #043D72. Keep public/favicon.svg and public/brand/* in sync.
 */

export const CLOUD_PATH = 'M9 25h14.5a5.5 5.5 0 0 0 .9-10.93 7.5 7.5 0 0 0-14.8-.87A5.9 5.9 0 0 0 9 25Z';
export const PULSE_PATH = 'M7.6 20.4h3.9l1.6-3.6 2.4 6 2.2-4.4 1.2 2h5.4';

export function LogoGlyph({ className }: { className?: string }) {
  const id = useId().replace(/:/g, '');
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id={`aq-cloud-${id}`} x1="6" y1="7" x2="25" y2="27" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#25AAE1" />
          <stop offset="0.5" stopColor="#058CC9" />
          <stop offset="1" stopColor="#043D72" />
        </linearGradient>
      </defs>
      <path d={CLOUD_PATH} fill={`url(#aq-cloud-${id})`} />
      <path d={PULSE_PATH} fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The Aquarient wave, drawn as a heartbeat — sits under the wordmark like the wave in the Aquarient logo. */
function PulseWave({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 44 8" className={className} aria-hidden="true" preserveAspectRatio="none">
      <path d="M1 5.2h13l2.2-3.6 2.8 5.2 2.4-4.1 1.4 2.5H43" fill="none" stroke="#058CC9" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function BrandMark({ compact, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cx('flex items-center gap-2.5', className)}>
      <LogoGlyph className="h-9 w-9 shrink-0 drop-shadow-sm" />
      {!compact && (
        <div className="min-w-0 leading-none">
          <p className="truncate text-[17px] font-semibold tracking-tight text-[#043D72] dark:text-white">aquarient</p>
          <p className="mt-1 flex items-center gap-1.5">
            <PulseWave className="h-2 w-7 shrink-0" />
            <span className="truncate text-[9.5px] font-semibold uppercase tracking-[0.2em] text-ink-subtle">CRM Health</span>
          </p>
        </div>
      )}
    </div>
  );
}

/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
      },
      colors: {
        bg: v('bg'),
        surface: v('surface'),
        muted: v('muted'),
        line: v('line'),
        ink: v('ink'),
        'ink-muted': v('ink-muted'),
        'ink-subtle': v('ink-subtle'),
        brand: { DEFAULT: v('brand'), soft: v('brand-soft'), ink: v('brand-ink') },
        accent: { DEFAULT: v('accent'), soft: v('accent-soft') },
        good: { DEFAULT: v('good'), soft: v('good-soft') },
        warn: { DEFAULT: v('warn'), soft: v('warn-soft') },
        bad: { DEFAULT: v('bad'), soft: v('bad-soft') },
        sev: {
          critical: v('sev-critical'),
          high: v('sev-high'),
          medium: v('sev-medium'),
          low: v('sev-low'),
        },
      },
      boxShadow: {
        card: '0 1px 2px rgb(15 23 42 / 0.04), 0 1px 3px rgb(15 23 42 / 0.06)',
        pop: '0 10px 30px -10px rgb(15 23 42 / 0.25), 0 4px 12px -4px rgb(15 23 42 / 0.12)',
      },
      keyframes: {
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        sweep: { to: { transform: 'rotate(360deg)' } },
        floaty: { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-4px)' } },
        pulseRing: {
          '0%': { transform: 'scale(0.9)', opacity: '0.6' },
          '100%': { transform: 'scale(1.8)', opacity: '0' },
        },
        flow: { to: { strokeDashoffset: '-24' } },
      },
      animation: {
        shimmer: 'shimmer 1.6s infinite',
        sweep: 'sweep 6s linear infinite',
        floaty: 'floaty 4s ease-in-out infinite',
        'pulse-ring': 'pulseRing 2s cubic-bezier(0.2,0.6,0.4,1) infinite',
        flow: 'flow 1.2s linear infinite',
      },
    },
  },
  plugins: [],
};

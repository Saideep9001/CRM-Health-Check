import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import { cx } from '@/lib/format';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle';
type Size = 'sm' | 'md';

const base =
  'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150 disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98] whitespace-nowrap';

const variants: Record<Variant, string> = {
  primary: 'bg-brand text-white shadow-sm hover:brightness-110 hover:shadow-md',
  secondary: 'border border-line bg-surface text-ink hover:bg-muted hover:border-ink-subtle/40',
  ghost: 'text-ink-muted hover:bg-muted hover:text-ink',
  subtle: 'bg-brand-soft text-brand-ink hover:brightness-95 dark:hover:brightness-125',
  danger: 'border border-bad/30 bg-bad-soft text-bad hover:bg-bad hover:text-white',
};

const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-9 px-4 text-sm',
};

interface Common {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  iconRight?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & Common>(
  ({ variant = 'secondary', size = 'md', icon, iconRight, className, children, type = 'button', ...rest }, ref) => (
    <button ref={ref} type={type} className={cx(base, variants[variant], sizes[size], className)} {...rest}>
      {icon}
      {children}
      {iconRight}
    </button>
  ),
);
Button.displayName = 'Button';

export function LinkButton({
  variant = 'secondary',
  size = 'md',
  icon,
  iconRight,
  className,
  children,
  ...rest
}: LinkProps & Common) {
  return (
    <Link className={cx(base, variants[variant], sizes[size], className)} {...rest}>
      {icon}
      {children}
      {iconRight}
    </Link>
  );
}

export function IconButton({
  label,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        'relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-ink-muted transition hover:bg-muted hover:text-ink',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

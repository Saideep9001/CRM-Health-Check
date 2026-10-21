import { AnimatePresence, motion } from 'framer-motion';
import { ChevronDown, ChevronsLeft, ChevronsRight, Cloud, Server, X } from 'lucide-react';
import { useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { CATEGORIES } from '@/config/categories';
import { NAV_ITEMS } from '@/config/navigation';
import { useAdminOverview, useApiHealth, useConnection, useRole } from '@/api/queries';
import { CONNECTION_STATUS_LABEL } from '../ui/Badges';
import { cx } from '@/lib/format';
import { CategoryIcon } from '../ui/CategoryIcon';
import { BrandMark } from '../ui/Brand';
import { Tooltip } from '../ui/Tooltip';

export function Sidebar({
  collapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}: {
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  const { pathname } = useLocation();
  const health = useApiHealth();
  const conn = useConnection();
  const apiOk = !!health.data;
  const sfStatus = conn.data?.status ?? null;
  const sfOk = sfStatus === 'connected';
  const dot = (ok: boolean, loading: boolean) => cx('h-2 w-2 shrink-0 rounded-full', loading ? 'animate-pulse bg-ink-subtle' : ok ? 'bg-good' : 'bg-warn');
  const [catsOpen, setCatsOpen] = useState(true);
  const inAssessment = pathname.startsWith('/assessment');
  const { isAdmin } = useRole();
  const pendingRequests = useAdminOverview(isAdmin).data?.pendingRequests ?? 0;
  const navItems = NAV_ITEMS.filter((n) => !n.adminOnly || isAdmin);

  const content = (compact: boolean, mobile: boolean) => (
    <div className="flex h-full flex-col">
      <div className={cx('flex h-16 items-center border-b border-line', compact ? 'justify-center px-2' : 'justify-between px-4')}>
        <Link
          to="/"
          onClick={mobile ? onCloseMobile : undefined}
          className="rounded-lg transition-opacity hover:opacity-80"
          aria-label="Aquarient — go to the home page"
          title="Go to the home page"
        >
          <BrandMark compact={compact} />
        </Link>
        {mobile && (
          <button onClick={onCloseMobile} className="rounded-md p-1.5 text-ink-subtle hover:bg-muted" aria-label="Close navigation">
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      <nav className="scrollbar-thin flex-1 space-y-0.5 overflow-y-auto p-3" aria-label="Primary">
        {!compact && <p className="label px-2.5 pb-2 pt-1">Workspace</p>}
        {navItems.map((item) => {
          const Icon = item.icon;
          const isAssessment = item.to === '/assessment';
          const link = (
            <NavLink
              to={item.to}
              end={item.to === '/dashboard'}
              onClick={mobile ? onCloseMobile : undefined}
              className={({ isActive }) =>
                cx(
                  'group relative flex items-center gap-3 rounded-lg py-2 text-sm font-medium transition-colors',
                  compact ? 'justify-center px-2' : 'px-2.5',
                  isActive || (isAssessment && inAssessment)
                    ? 'text-brand-ink'
                    : 'text-ink-muted hover:bg-muted hover:text-ink',
                )
              }
            >
              {({ isActive }) => {
                const active = isActive || (isAssessment && inAssessment);
                return (
                  <>
                    {active && (
                      <motion.span
                        layoutId={mobile ? 'nav-active-m' : 'nav-active'}
                        className="absolute inset-0 rounded-lg bg-brand-soft"
                        transition={{ type: 'spring', stiffness: 450, damping: 36 }}
                      />
                    )}
                    {active && <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-brand" />}
                    <Icon className="relative h-[18px] w-[18px] shrink-0" />
                    {!compact && <span className="relative flex-1 truncate">{item.label}</span>}
                    {item.to === '/admin' && pendingRequests > 0 && (
                      <span
                        className={cx('relative grid min-w-[18px] place-items-center rounded-full bg-brand px-1 text-[10px] font-semibold leading-[18px] text-white', compact && 'absolute right-1 top-0.5')}
                        aria-label={`${pendingRequests} access requests waiting`}
                      >
                        {pendingRequests}
                      </span>
                    )}
                    {!compact && isAssessment && (
                      <span
                        role="button"
                        tabIndex={0}
                        aria-label={catsOpen ? 'Collapse categories' : 'Expand categories'}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setCatsOpen((o) => !o);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            setCatsOpen((o) => !o);
                          }
                        }}
                        className="relative rounded p-0.5 hover:bg-surface/60"
                      >
                        <ChevronDown className={cx('h-4 w-4 transition-transform', !catsOpen && '-rotate-90')} />
                      </span>
                    )}
                  </>
                );
              }}
            </NavLink>
          );

          return (
            <div key={item.to}>
              {compact ? (
                <Tooltip content={item.label} side="right" className="w-full">
                  <div className="w-full">{link}</div>
                </Tooltip>
              ) : (
                link
              )}
              {isAssessment && !compact && (
                <AnimatePresence initial={false}>
                  {catsOpen && (
                    <motion.ul
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="ml-[21px] overflow-hidden border-l border-line pl-2"
                    >
                      {CATEGORIES.map((c) => (
                        <li key={c.id}>
                          <NavLink
                            to={`/assessment/${c.id}`}
                            onClick={mobile ? onCloseMobile : undefined}
                            className={({ isActive }) =>
                              cx(
                                'flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] transition-colors',
                                isActive || pathname.startsWith(`/assessment/${c.id}/`)
                                  ? 'bg-muted font-medium text-ink'
                                  : 'text-ink-muted hover:bg-muted hover:text-ink',
                              )
                            }
                          >
                            <CategoryIcon id={c.id} className="h-3.5 w-3.5 shrink-0" />
                            <span className="flex-1 truncate">{c.shortName}</span>
                            {c.release === 'coming-soon' && (
                              <span className="rounded bg-warn-soft px-1 text-[9px] font-bold uppercase text-warn">Soon</span>
                            )}
                          </NavLink>
                        </li>
                      ))}
                    </motion.ul>
                  )}
                </AnimatePresence>
              )}
            </div>
          );
        })}
      </nav>

      <div className="border-t border-line p-3">
        {compact ? (
          <Tooltip content={`API: ${apiOk ? 'online' : 'unavailable'} · Salesforce: ${sfStatus ? CONNECTION_STATUS_LABEL[sfStatus] : 'unknown'}`} side="right" className="w-full justify-center">
            <span className="flex w-full flex-col items-center gap-1.5 rounded-lg bg-muted p-2">
              <span className={dot(apiOk, health.isLoading)} />
              <span className={dot(sfOk, conn.isLoading)} />
            </span>
          </Tooltip>
        ) : (
          <div className="space-y-2 rounded-lg border border-line bg-muted/60 p-3 text-xs">
            <div className="flex items-center gap-2">
              <Server className="h-3.5 w-3.5 text-ink-subtle" />
              <span className="flex-1 text-ink-muted">Platform</span>
              <span className={dot(apiOk, health.isLoading)} />
              <span className="font-medium">{health.isLoading ? 'Checking…' : apiOk ? 'Ready' : 'Offline'}</span>
            </div>
            <NavLink to="/connection" onClick={mobile ? onCloseMobile : undefined} className="flex items-center gap-2 hover:text-ink">
              <Cloud className="h-3.5 w-3.5 text-ink-subtle" />
              <span className="flex-1 text-ink-muted">Salesforce</span>
              <span className={dot(sfOk, conn.isLoading)} />
              <span className="font-medium">{conn.isLoading ? 'Checking…' : sfStatus ? CONNECTION_STATUS_LABEL[sfStatus] : 'Not set up'}</span>
            </NavLink>
          </div>
        )}
        {!mobile && (
          <button
            onClick={onToggleCollapse}
            className={cx(
              'mt-2 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-xs font-medium text-ink-subtle transition hover:bg-muted hover:text-ink',
              compact && 'justify-center',
            )}
            aria-label={compact ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {compact ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
            {!compact && 'Collapse'}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <>
      <motion.aside
        animate={{ width: collapsed ? 72 : 264 }}
        transition={{ type: 'spring', stiffness: 400, damping: 40 }}
        className="sticky top-0 hidden h-screen shrink-0 border-r border-line bg-surface lg:block"
      >
        {content(collapsed, false)}
      </motion.aside>

      <AnimatePresence>
        {mobileOpen && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <motion.div
              className="absolute inset-0 bg-slate-950/50"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={onCloseMobile}
            />
            <motion.aside
              initial={{ x: -290 }}
              animate={{ x: 0 }}
              exit={{ x: -290 }}
              transition={{ type: 'spring', stiffness: 380, damping: 36 }}
              className="absolute left-0 top-0 h-full w-[272px] border-r border-line bg-surface shadow-pop"
            >
              {content(false, true)}
            </motion.aside>
          </div>
        )}
      </AnimatePresence>
    </>
  );
}

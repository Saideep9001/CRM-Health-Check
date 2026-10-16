import { AnimatePresence, motion } from 'framer-motion';
import { Bell, BellOff, ChevronRight, HelpCircle, LogOut, Menu, Monitor, Moon, Settings, Sun, User } from 'lucide-react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { errorMessage } from '@/api/client';
import { useLogout, useMarkNotificationsRead, useMe, useNotifications } from '@/api/queries';
import { AUTH_REQUIRED } from '@/config/app';
import { resolveRoute } from '@/config/navigation';
import { useTheme } from '@/context/ThemeContext';
import { fmtDateTime } from '@/lib/format';
import { IconButton } from '../ui/Button';
import { Dropdown, MenuItem } from '../ui/Menu';
import { Segmented } from '../ui/Tabs';
import { GlobalSearch } from './GlobalSearch';

export function ThemeToggle() {
  const { resolved, toggle } = useTheme();
  return (
    <IconButton label={resolved === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} onClick={toggle}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={resolved}
          initial={{ rotate: -90, scale: 0.5, opacity: 0 }}
          animate={{ rotate: 0, scale: 1, opacity: 1 }}
          exit={{ rotate: 90, scale: 0.5, opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="flex"
        >
          {resolved === 'dark' ? <Moon className="h-[18px] w-[18px]" /> : <Sun className="h-[18px] w-[18px]" />}
        </motion.span>
      </AnimatePresence>
    </IconButton>
  );
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('');

export function Header({ onOpenMobileNav }: { onOpenMobileNav: () => void }) {
  const { pathname } = useLocation();
  const { title, crumbs } = resolveRoute(pathname);
  const navigate = useNavigate();
  const { pref, setPref } = useTheme();
  const me = useMe();
  const notifications = useNotifications();
  const markRead = useMarkNotificationsRead();
  const logout = useLogout();
  const items = notifications.data ?? [];
  const unread = items.filter((n) => !n.read);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-surface/85 backdrop-blur-md">
      <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
        <IconButton label="Open navigation" className="lg:hidden" onClick={onOpenMobileNav}>
          <Menu className="h-5 w-5" />
        </IconButton>

        <div className="min-w-0 flex-1">
          <nav aria-label="Breadcrumb" className="hidden items-center gap-1 text-xs text-ink-subtle sm:flex">
            {crumbs.map((c, i) => (
              <span key={i} className="flex min-w-0 items-center gap-1">
                {i > 0 && <ChevronRight className="h-3 w-3 shrink-0" />}
                {c.to ? (
                  <Link to={c.to} className="truncate hover:text-ink">
                    {c.label}
                  </Link>
                ) : (
                  <span className="truncate text-ink-muted">{c.label}</span>
                )}
              </span>
            ))}
          </nav>
          <p className="truncate text-[15px] font-semibold leading-tight">{title}</p>
        </div>

        <div className="hidden w-[300px] shrink-0 md:block lg:w-[380px]">
          <GlobalSearch />
        </div>

        <div className="flex items-center gap-1">
          <IconButton label="Help & guide" onClick={() => navigate('/help')}>
            <HelpCircle className="h-[18px] w-[18px]" />
          </IconButton>
          <ThemeToggle />

          <Dropdown
            width="w-80"
            trigger={({ toggle }) => (
              <IconButton label={`Notifications (${unread.length} unread)`} onClick={toggle}>
                <Bell className="h-[18px] w-[18px]" />
                {unread.length > 0 && (
                  <span className="absolute right-2 top-2 flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-bad opacity-60" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-bad" />
                  </span>
                )}
              </IconButton>
            )}
          >
            {(close) => (
              <div>
                <div className="flex items-center justify-between px-2.5 py-2">
                  <p className="text-sm font-semibold">Notifications</p>
                  <button
                    className="text-xs font-medium text-brand hover:underline disabled:text-ink-subtle disabled:no-underline"
                    disabled={unread.length === 0 || markRead.isPending}
                    onClick={() => markRead.mutate(unread.map((n) => n.id))}
                  >
                    Mark all read
                  </button>
                </div>
                {notifications.isLoading ? (
                  <p className="px-2.5 py-6 text-center text-sm text-ink-subtle">Loading…</p>
                ) : notifications.error ? (
                  <p className="px-2.5 py-6 text-center text-sm text-ink-subtle">{errorMessage(notifications.error)}</p>
                ) : items.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 px-2.5 py-8 text-center text-sm text-ink-subtle">
                    <BellOff className="h-5 w-5" />
                    You’re all caught up.
                  </div>
                ) : (
                  <div className="scrollbar-thin max-h-96 space-y-0.5 overflow-y-auto">
                    {items.map((n) => (
                      <button
                        key={n.id}
                        onClick={() => {
                          if (!n.read) markRead.mutate([n.id]);
                          if (n.link) navigate(n.link);
                          close();
                        }}
                        className="flex w-full gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-muted"
                      >
                        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.read ? 'bg-transparent' : n.kind === 'alert' ? 'bg-bad' : 'bg-brand'}`} />
                        <span className="min-w-0">
                          <span className={`block text-sm font-medium ${n.kind === 'alert' ? 'text-bad' : ''}`}>{n.title}</span>
                          <span className="block text-xs text-ink-muted">{n.body}</span>
                          <span className="mt-0.5 block text-[11px] text-ink-subtle">{fmtDateTime(n.createdAt)}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Dropdown>

          <Dropdown
            trigger={({ toggle }) => (
              <button onClick={toggle} className="ml-1 flex items-center gap-2 rounded-lg p-1 pr-2 transition hover:bg-muted" aria-label="User menu">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-brand to-accent text-xs font-semibold text-white">
                  {me.data ? initials(me.data.name) : <User className="h-4 w-4" />}
                </span>
                <span className="hidden max-w-[160px] text-left leading-tight sm:block">
                  <span className="block truncate text-sm font-medium">{me.data?.name ?? 'Account'}</span>
                  <span className="block truncate text-[11px] text-ink-subtle">{me.data?.role ?? (me.isLoading ? 'Loading…' : 'Profile unavailable')}</span>
                </span>
              </button>
            )}
          >
            {(close) => (
              <div>
                <div className="border-b border-line px-2.5 pb-2.5 pt-1.5">
                  <p className="truncate text-sm font-semibold">{me.data?.name ?? 'Account'}</p>
                  <p className="truncate text-xs text-ink-subtle">{me.data?.email ?? (me.error ? errorMessage(me.error) : 'Loading…')}</p>
                </div>
                <div className="py-1">
                  <MenuItem icon={<User className="h-4 w-4" />} onClick={() => { navigate('/settings?tab=profile'); close(); }}>
                    Profile
                  </MenuItem>
                  <MenuItem icon={<Settings className="h-4 w-4" />} onClick={() => { navigate('/settings'); close(); }}>
                    Settings
                  </MenuItem>
                </div>
                <div className="border-t border-line px-2.5 py-2.5">
                  <p className="label mb-2">Theme</p>
                  <Segmented
                    layoutId="theme-seg-header"
                    value={pref}
                    onChange={setPref}
                    options={[
                      { id: 'light', label: 'Light', icon: <Sun className="h-3.5 w-3.5" /> },
                      { id: 'dark', label: 'Dark', icon: <Moon className="h-3.5 w-3.5" /> },
                      { id: 'system', label: 'Auto', icon: <Monitor className="h-3.5 w-3.5" /> },
                    ]}
                  />
                </div>
                {AUTH_REQUIRED && (
                <div className="border-t border-line pt-1">
                    <MenuItem
                      icon={<LogOut className="h-4 w-4" />}
                      onClick={() => {
                        close();
                        // Navigate even if the request fails; the session cookie is cleared server-side when reachable.
                        logout.mutateAsync().finally(() => navigate('/login', { replace: true }));
                      }}
                    >
                      {logout.isPending ? 'Signing out…' : 'Sign out'}
                    </MenuItem>
                  </div>
                )}
              </div>
            )}
          </Dropdown>
        </div>
      </div>
      <div className="border-t border-line px-4 py-2 md:hidden">
        <GlobalSearch />
      </div>
    </header>
  );
}

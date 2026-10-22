import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { ChatWidget } from '../assistant/ChatWidget';
import { WelcomeTourProvider } from '../onboarding/WelcomeTour';
import { Header } from './Header';
import { SavedResultsBanner } from './SavedResultsBanner';
import { Sidebar } from './Sidebar';

const COLLAPSE_KEY = 'aq-sidebar-collapsed';

export function AppLayout() {
  const { pathname } = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch {
      // ignore
    }
  }, [collapsed]);

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);

  return (
    <WelcomeTourProvider>
    <div className="flex min-h-screen bg-bg">
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header onOpenMobileNav={() => setMobileOpen(true)} />
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
          >
            <SavedResultsBanner />
            <Outlet />
          </motion.div>
        </main>
        <footer className="border-t border-line px-6 py-4 text-center text-xs text-ink-subtle">
          Aquarient Technologies · CRM Health &amp; Data Quality Platform · v{__APP_VERSION__}
        </footer>
      </div>
      <ChatWidget />
    </div>
    </WelcomeTourProvider>
  );
}

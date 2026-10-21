import {
  Briefcase,
  ClipboardCheck,
  Cloud,
  Database,
  FileBarChart,
  HelpCircle,
  History,
  LayoutDashboard,
  ListChecks,
  Settings,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react';
import { getArea, getCategory } from './categories';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Only shown to admins (the server enforces it too). */
  adminOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard',  label: 'Overview',            icon: LayoutDashboard },
  { to: '/portfolio',  label: 'Client Portfolio',    icon: Briefcase },
  { to: '/connection', label: 'Connect Salesforce',  icon: Cloud },
  { to: '/data',       label: 'Your Data',           icon: Database },
  { to: '/assessment', label: 'What We Check',       icon: ClipboardCheck },
  { to: '/results',    label: 'My Results',          icon: ListChecks },
  { to: '/reports',    label: 'Reports',             icon: FileBarChart },
  { to: '/history',    label: 'Check History',       icon: History },
  { to: '/admin',     label: 'Admin Panel',         icon: ShieldCheck, adminOnly: true },
  { to: '/settings',  label: 'Settings',            icon: Settings },
  { to: '/help',      label: 'Help & guide',        icon: HelpCircle },
];

export interface Crumb {
  label: string;
  to?: string;
}

/** Derive page title + breadcrumbs from the current path. */
export function resolveRoute(pathname: string): { title: string; crumbs: Crumb[] } {
  const parts = pathname.split('/').filter(Boolean);
  const home: Crumb = { label: 'Overview', to: '/dashboard' };
  if (parts.length === 0 || parts[0] === 'dashboard') return { title: 'Overview', crumbs: [{ label: 'Overview' }] };

  const top = NAV_ITEMS.find((n) => n.to === `/${parts[0]}`);
  if (!top) return { title: 'Page not found', crumbs: [home, { label: 'Not found' }] };

  if (parts[0] === 'connection' && parts[1] === 'callback') {
    return { title: 'Completing connection', crumbs: [home, { label: top.label, to: top.to }, { label: 'Authorising…' }] };
  }
  if (parts[0] === 'assessment' && parts[1]) {
    const cat = getCategory(parts[1]);
    const crumbs: Crumb[] = [home, { label: top.label, to: top.to }];
    if (!cat) return { title: 'Topic not found', crumbs: [...crumbs, { label: 'Not found' }] };
    if (parts[2]) {
      const area = getArea(parts[2]);
      crumbs.push({ label: cat.name, to: `/assessment/${cat.id}` });
      crumbs.push({ label: area ? `Area ${area.number}` : 'Not found' });
      return { title: area ? area.name : 'Area not found', crumbs };
    }
    crumbs.push({ label: cat.name });
    return { title: cat.name, crumbs };
  }

  return { title: top.label, crumbs: [home, { label: top.label }] };
}

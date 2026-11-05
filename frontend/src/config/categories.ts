import type { Category, CategoryId, DiagnosticArea } from '@/types';

/**
 * Single source of truth for the six assessment categories and all
 * 21 diagnostic areas. Names and descriptions are fixed by the product
 * specification — do not rename, merge, or remove entries.
 */

export const DIAGNOSTIC_AREAS: DiagnosticArea[] = [
  // ---------------- Category 1: Data Quality & Optimization ----------------
  {
    id: 'area-1',
    number: 1,
    categoryId: 'data-quality',
    name: 'Record Data Quality',
    description:
      'For each object you choose, how good the records are: duplicates, missing key fields, invalid or inconsistent values, records with no recent activity, and each object’s own checks (e.g. Accounts without Contacts).',
    indicators: [
      'Duplicate Accounts',
      'Missing Key Fields (Accounts)',
      'Data Standardization Issues (Accounts)',
      'No Activity in 6 Months (Accounts)',
      'Accounts Without Open Opportunities',
      'Duplicate Contacts',
      'Missing Key Fields (Contacts)',
      'Data Standardization Issues (Contacts)',
      'No Activity in 6 Months (Contacts)',
      'Duplicate Leads',
      'Missing Key Fields (Leads)',
      'Data Standardization Issues (Leads)',
      'Campaign Association Gaps (Leads)',
      'Duplicate Opportunities',
      'Missing Key Fields (Opportunities)',
      'Data Standardization Issues (Opportunities)',
      'Opportunities Without Line Items',
    ],
  },
  {
    id: 'area-2',
    number: 2,
    categoryId: 'data-quality',
    name: 'Redundant Fields & Data Quality Scorecard',
    description:
      'For each object you choose: its fields, which are unused or low-completion, outdated or look-alike, and empty fields that reports and automation rely on — plus a score (%) per object.',
    indicators: [
      'All Fields (Accounts)',
      'Unused & Low-Completion Fields (Accounts)',
      'Outdated Fields (Accounts)',
      'Look-alike Fields (Accounts)',
      'Empty Fields Others Depend On (Accounts)',
      'All Fields (Contacts)',
      'Unused & Low-Completion Fields (Contacts)',
      'Outdated Fields (Contacts)',
      'Look-alike Fields (Contacts)',
      'Empty Fields Others Depend On (Contacts)',
      'All Fields (Leads)',
      'Unused & Low-Completion Fields (Leads)',
      'Outdated Fields (Leads)',
      'Look-alike Fields (Leads)',
      'Empty Fields Others Depend On (Leads)',
      'All Fields (Opportunities)',
      'Unused & Low-Completion Fields (Opportunities)',
      'Outdated Fields (Opportunities)',
      'Look-alike Fields (Opportunities)',
      'Empty Fields Others Depend On (Opportunities)',
      'Data Quality Scorecard',
    ],
  },

  // ---------------- Category 2: Workflows & Automation ----------------
  {
    id: 'area-3',
    number: 3,
    categoryId: 'workflows',
    name: 'Lead Queues & Assignment',
    description:
      'Find Leads waiting too long in queues, inactive Lead Assignment Rules that would match existing Leads, Leads that no active assignment rule entry matches, and Leads nobody is working.',
    indicators: [
      'Stuck Queue-Owned Leads',
      'Inactive Lead Assignment Rules',
      'Lead Assignment Criteria Mismatches',
      'No Activity in 6 Months (Leads)',
      'Stale Leads',
    ],
  },
  {
    id: 'area-4',
    number: 4,
    categoryId: 'workflows',
    name: 'Account Hierarchies & Contact Relationships',
    description:
      'Assess Account hierarchies and parent links, then Contact Roles on open Opportunities, Contacts with no Account, Contacts related to multiple Accounts, Contacts on several deals, and open deals past their Close Date.',
    indicators: [
      'Accounts Without Contacts',
      'Account Hierarchy Chains',
      'Child Accounts Under Inactive Parents',
      'Possible Missing Parent Accounts',
      'Opportunities Without Contact Roles',
      'Orphaned Contacts',
      'Contacts to Multiple Accounts',
      'Multi-Deal Contacts',
      'Opportunities with an Overdue Close Date',
    ],
  },
  {
    id: 'area-5',
    number: 5,
    categoryId: 'workflows',
    name: 'Sales Path, Playbooks & Feedback Loops',
    description:
      'Assess sales stage guidance, required sales fields, deal progression, deals nobody is working, and the capture of Closed Lost reasons.',
    indicators: [
      'Stuck Opportunities',
      'Missing Next Steps',
      'No Activity in 6 Months (Opportunities)',
      'Closed Lost Without a Reason (Opportunities)',
      'Sales stage guidance gaps',
    ],
  },
  {
    id: 'area-6',
    number: 6,
    categoryId: 'workflows',
    name: 'Activity Capture, Web-to-Lead & Email Templates',
    description:
      'Assess activity logging, Web-to-Lead processes, and the availability of reusable sales email templates.',
    indicators: [
      'Missing sales activities',
      'Web-to-Lead issues',
      'Email template availability',
      'Activity capture gaps',
    ],
  },
  {
    id: 'area-7',
    number: 7,
    categoryId: 'workflows',
    name: 'Layouts, Validation Rules & Required Fields',
    description:
      'Assess record layouts, field validation, required fields, and usability issues affecting data entry.',
    indicators: [
      'Missing validation rules',
      'Required field gaps',
      'Potential junk data',
      'Layout usability concerns',
      'Legacy automation to migrate',
      'Overlapping automation',
      'Stuck or failing automations',
    ],
  },

  // ---------------- Category 3: Reporting & Dashboards ----------------
  {
    id: 'area-8',
    number: 8,
    categoryId: 'reporting',
    name: 'Remove unused reports and develop key leadership insights',
    description:
      'Identify potentially unused reports and dashboards and highlight opportunities to improve leadership reporting.',
    indicators: [
      'Unused reports',
      'Unused dashboards',
      'Reporting organization issues',
      'Leadership reporting gaps',
      'Report trust issues',
    ],
  },
  {
    id: 'area-9',
    number: 9,
    categoryId: 'reporting',
    name: 'Track sales rep activity, marketing handoffs, and deal progress',
    description:
      'Assess sales activity visibility, Lead handoffs, and Opportunity progression monitoring.',
    indicators: [
      'Sales activity gaps',
      'Opportunities without open Tasks',
      'Marketing-to-sales handoff visibility',
      'Pipeline progression gaps',
    ],
  },
  {
    id: 'area-10',
    number: 10,
    categoryId: 'reporting',
    name: 'Identify top-performing regions, stuck deals, and lost opportunities',
    description:
      'Provide visibility into regional performance, stagnant Opportunities, and Closed Lost deals.',
    indicators: [
      'Stuck Opportunities',
      'Overdue deals',
      'Regional performance visibility',
      'Closed Lost trends',
      'Forecast setup issues',
    ],
  },
  {
    id: 'area-11',
    number: 11,
    categoryId: 'reporting',
    name: 'Analyze win-loss trends and upsell potential',
    description:
      'Assess win-loss analysis, competitor tracking, product visibility, and customer upsell opportunities.',
    indicators: [
      'Win-loss reporting gaps',
      'Competitor tracking gaps',
      'Product visibility issues',
      'Upsell opportunity visibility',
    ],
  },

  // ---------------- Category 4: User Adoption & Enablement ----------------
  {
    id: 'area-12',
    number: 12,
    categoryId: 'user-adoption',
    name: 'Monitor login activity and train low adopters',
    description: 'Identify inactive users and potential gaps in Salesforce adoption.',
    indicators: ['Inactive users', 'Login activity', 'Low adoption indicators', 'Training opportunities'],
  },
  {
    id: 'area-13',
    number: 13,
    categoryId: 'user-adoption',
    name: 'Align roles, permissions, and profiles',
    description:
      'Assess role hierarchy, sharing settings, profile complexity, and potentially excessive permissions.',
    indicators: [
      'Permission configuration concerns',
      'Profile complexity',
      'Role hierarchy issues',
      'Excessive permissions',
    ],
  },
  {
    id: 'area-14',
    number: 14,
    categoryId: 'user-adoption',
    name: 'Improve usability with field help text and intuitive dashboards',
    description:
      'Identify usability improvements involving field help text, home pages, dashboards, and frequently used list views.',
    indicators: [
      'Missing field help text',
      'Home page improvement opportunities',
      'List view usability',
      'Navigation improvement opportunities',
    ],
  },

  // ---------------- Category 5: Quoting & Opportunity Product Management ----------------
  {
    id: 'area-15',
    number: 15,
    categoryId: 'quoting',
    name: 'Product, Pricebook & Opportunity Product Management',
    description:
      'Assess product configuration, Pricebooks, and the association of products with Opportunities.',
    indicators: [
      'Opportunities without products',
      'Product configuration concerns',
      'Pricebook configuration',
      'Product reporting gaps',
    ],
  },
  {
    id: 'area-16',
    number: 16,
    categoryId: 'quoting',
    name: 'Quote Generation, Syncing, & Delivery',
    description:
      'Assess Quote configuration, Quote synchronization, and the visibility of the quoting process.',
    indicators: [
      'Quote synchronization concerns',
      'Quote configuration',
      'Missing Quote visibility',
      'Quote process gaps',
    ],
  },
  {
    id: 'area-17',
    number: 17,
    categoryId: 'quoting',
    name: 'Quote Approvals & Discount Management',
    description: 'Assess Quote approval workflows, discount controls, and approval delays.',
    indicators: [
      'Pending approvals',
      'Delayed approvals',
      'Discount approval configuration',
      'Approval workflow gaps',
    ],
  },

  // ---------------- Category 6: Integrations, API & Data Flow ----------------
  {
    id: 'area-18',
    number: 18,
    categoryId: 'integrations',
    name: 'Marketing Automation & Lead Flow',
    description:
      'Assess marketing platform integration, Lead synchronization, and marketing campaign visibility.',
    indicators: [
      'Marketing integration status',
      'Lead synchronization concerns',
      'Campaign visibility',
      'Integration configuration gaps',
    ],
  },
  {
    id: 'area-19',
    number: 19,
    categoryId: 'integrations',
    name: 'ERP/Finance Integration & Order Flow',
    description:
      'Assess the flow of information between Salesforce and ERP or financial systems.',
    indicators: [
      'Missing external identifiers',
      'Potential synchronization gaps',
      'Order integration visibility',
      'ERP integration concerns',
    ],
  },
  {
    id: 'area-20',
    number: 20,
    categoryId: 'integrations',
    name: 'API Governance & Health',
    description:
      'Assess API consumption, connected applications, and the visibility of integration failures.',
    indicators: [
      'API usage',
      'API limit monitoring',
      'Connected application visibility',
      'Integration health indicators',
      'Sync health score',
    ],
  },
  {
    id: 'area-21',
    number: 21,
    categoryId: 'integrations',
    name: 'Data Warehouse & BI/Analytics',
    description:
      'Assess Salesforce data extraction, analytics integrations, storage considerations, and consistency between CRM and BI reporting.',
    indicators: [
      'BI integration visibility',
      'Data extraction concerns',
      'Storage utilization indicators',
      'Reporting consistency concerns',
    ],
  },
];

export const CATEGORIES: Category[] = [
  {
    id: 'data-quality',
    order: 1,
    name: 'Data Quality & Optimization',
    shortName: 'Data Quality',
    purpose:
      'Identify data quality issues, duplicate records, missing information, inconsistent fields, and opportunities to improve CRM data.',
    release: 'mvp',
    areaIds: ['area-1', 'area-2'],
  },
  {
    id: 'workflows',
    order: 2,
    name: 'Workflows & Automation',
    shortName: 'Workflows',
    purpose:
      'Identify inefficient sales processes, missing automation, stale Leads, and problems in sales progression.',
    release: 'mvp',
    areaIds: ['area-3', 'area-4', 'area-5', 'area-6', 'area-7'],
  },
  {
    id: 'reporting',
    order: 3,
    name: 'Reporting & Dashboards',
    shortName: 'Reporting',
    purpose:
      'Improve reporting visibility, sales performance monitoring, pipeline analysis, and executive decision-making.',
    release: 'mvp',
    areaIds: ['area-8', 'area-9', 'area-10', 'area-11'],
  },
  {
    id: 'user-adoption',
    order: 4,
    name: 'User Adoption & Enablement',
    shortName: 'User Adoption',
    purpose: 'Assess Salesforce adoption, user activity, permissions, and usability.',
    release: 'mvp',
    areaIds: ['area-12', 'area-13', 'area-14'],
  },
  {
    id: 'quoting',
    order: 5,
    name: 'Quoting & Opportunity Product Management',
    shortName: 'Quoting',
    purpose: 'Assess product management, pricing, quoting, and approval processes.',
    release: 'mvp',
    areaIds: ['area-15', 'area-16', 'area-17'],
  },
  {
    id: 'integrations',
    order: 6,
    name: 'Integrations, API & Data Flow',
    shortName: 'Integrations',
    purpose:
      'Assess data exchange between Salesforce and other business systems, API governance, and downstream analytics.',
    release: 'mvp',
    areaIds: ['area-18', 'area-19', 'area-20', 'area-21'],
  },
];

// ---------- Lookup helpers ----------

const areaById = new Map(DIAGNOSTIC_AREAS.map((a) => [a.id, a]));
const categoryById = new Map(CATEGORIES.map((c) => [c.id, c]));

export const getCategory = (id: string) => categoryById.get(id as CategoryId);
export const getArea = (id: string) => areaById.get(id);
export const getAreasForCategory = (id: CategoryId) =>
  DIAGNOSTIC_AREAS.filter((a) => a.categoryId === id).sort((a, b) => a.number - b.number);

/** Areas inherit their release stage from the parent category. */
export const getAreaRelease = (area: DiagnosticArea) => getCategory(area.categoryId)?.release ?? 'coming-soon';

export const RELEASE_LABEL = { mvp: 'Available', 'coming-soon': 'Coming Soon' } as const;

/** Areas that may be selected in an assessment (MVP release only). */
export const MVP_AREA_IDS = DIAGNOSTIC_AREAS.filter((a) => getAreaRelease(a) === 'mvp').map((a) => a.id);

/** Consistent per-category chart colors (work on both themes). */
export const CATEGORY_COLORS: Record<CategoryId, string> = {
  'data-quality': '#3b82f6',
  workflows: '#14b8a6',
  reporting: '#8b5cf6',
  'user-adoption': '#f59e0b',
  quoting: '#ec4899',
  integrations: '#06b6d4',
};

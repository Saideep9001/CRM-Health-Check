/**
 * Plain-language vocabulary used across the app. Keep wording here so the
 * Help page, tooltips, and labels explain things the same way everywhere.
 *
 *   Internal term       → What users see
 *   assessment          → health check
 *   category            → topic
 *   diagnostic area     → area (numbered 1–21)
 *   finding             → problem
 *   severity            → urgency
 *   finding status      → progress
 */

export interface GlossaryEntry {
  term: string;
  plain: string;
  example?: string;
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    term: 'Health check',
    plain: 'A scan of your Salesforce that gives you a score and a list of problems to fix.',
    example: 'Many teams run one every few months.',
  },
  {
    term: 'Health score',
    plain: 'A number from 0 to 100. Higher is better.',
    example: '80+ is healthy, 65–79 is fair, below 65 needs attention.',
  },
  {
    term: 'Topic',
    plain: 'One of the six things we check, like Data Quality or Reporting.',
  },
  {
    term: 'Area',
    plain: 'A smaller part of a topic. There are 21 areas.',
    example: 'Area 1 looks for duplicate records.',
  },
  {
    term: 'Problem',
    plain: 'Something we found that should be fixed. Each one comes with a fix.',
    example: '“1,200 Contacts have no email address.”',
  },
  {
    term: 'Urgency',
    plain: 'How serious a problem is: Critical, High, Medium, or Low.',
  },
  {
    term: 'Records affected',
    plain: 'How many records have the problem.',
  },
  {
    term: 'Progress',
    plain: 'Where you are with a fix: Open, In Review, Resolved, or Accepted Risk (not fixing).',
  },
  {
    term: 'Salesforce org',
    plain: 'Your company’s Salesforce account.',
  },
  {
    term: 'Sandbox',
    plain: 'A test copy of your Salesforce.',
  },
  {
    term: 'Connect (OAuth)',
    plain: 'You sign in on Salesforce’s own page and click Allow. We never see your password.',
  },
  {
    term: 'Read-only',
    plain: 'We can look at your data, but never change it.',
  },
  {
    term: 'Coming Soon',
    plain: 'You can see it now, but can’t check it yet.',
  },
];

/** Short explanations for urgency levels, used in tooltips and legends. */
export const URGENCY_HELP = {
  critical: 'Fix now.',
  high: 'Fix soon.',
  medium: 'Plan a fix.',
  low: 'Nice to fix.',
} as const;

/** Score bands, matching scoreBand() in lib/format. */
export const SCORE_BANDS = [
  { min: 80, label: 'Healthy', text: '80–100', color: 'rgb(var(--good))' },
  { min: 65, label: 'Fair', text: '65–79', color: 'rgb(var(--warn))' },
  { min: 0, label: 'Needs attention', text: '0–64', color: 'rgb(var(--bad))' },
] as const;

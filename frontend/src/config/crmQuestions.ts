/**
 * Live Salesforce data questions the help assistant can answer without AI.
 * Each id maps to one fixed, read-only lookup on the server (dev-server/crmQueries.ts).
 * Order matters: more specific questions come before general ones.
 * Patterns run against lower-cased, punctuation-free text.
 */

const DEAL = String.raw`(deals?|opportunit\w*|opps?)`;

export interface CrmQuestion {
  id: string;
  /** Example wording, shown as a tap-to-ask chip. */
  question: string;
  group: 'Leads' | 'Deals' | 'Accounts' | 'Contacts';
  patterns: RegExp[];
}

export const CRM_QUESTIONS: CrmQuestion[] = [
  // ---- Leads ----
  { id: 'leads.unassigned', group: 'Leads', question: 'Which leads are unassigned?', patterns: [/\bunassigned leads?\b/, /\bleads?\b.*\b(unassigned|no owner|without (an )?owner|in (a |the )?queue|not assigned)\b/] },
  { id: 'leads.stale', group: 'Leads', question: 'Which leads have gone quiet?', patterns: [/\b(stale|quiet|inactive|untouched|forgotten|neglected|cold)\b.*\bleads?\b/, /\bleads?\b.*\b(stale|gone quiet|inactive|no activity|not (been )?(touched|updated))\b/] },
  { id: 'leads.bySource', group: 'Leads', question: 'Where do our leads come from?', patterns: [/\blead sources?\b/, /\bleads?\b.*\b(source|sources|come from|coming from|channel|channels)\b/] },
  { id: 'leads.new', group: 'Leads', question: 'How many new leads this month?', patterns: [/\bnew leads?\b/, /\bleads?\b.*\bthis month\b/] },
  { id: 'leads.open', group: 'Leads', question: 'How many open leads do we have?', patterns: [/\b(how many|number of|count|total)\b.*\bleads?\b/, /\bopen leads?\b/, /^leads?$/] },

  // ---- Deals ----
  { id: 'opps.overdue', group: 'Deals', question: 'Which deals are overdue?', patterns: [new RegExp(String.raw`\b(overdue|late|slipp\w*|past (their |the )?close)\b.*\b${DEAL}\b`), new RegExp(String.raw`\b${DEAL}\b.*\b(overdue|late|past (their |the )?close( date)?|slipp\w*)\b`)] },
  { id: 'opps.closingThisMonth', group: 'Deals', question: 'Which deals close this month?', patterns: [/\bclos\w* this month\b/, new RegExp(String.raw`\b${DEAL}\b.*\bthis month\b`)] },
  { id: 'opps.wonThisQuarter', group: 'Deals', question: 'What have we won this quarter?', patterns: [/\b(won|win|wins|closed won)\b.*\bquarter\b/, /\bwhat (have|did) we (won|win|close|closed)\b/, /\bsales this quarter\b/] },
  { id: 'opps.top', group: 'Deals', question: 'What are our biggest open deals?', patterns: [new RegExp(String.raw`\b(biggest|largest|top|best|highest)\b.*\b${DEAL}\b`)] },
  { id: 'opps.byStage', group: 'Deals', question: 'How many deals are in each stage?', patterns: [/\b(by|each|per|every) stage\b/, /\bstages?\b.*\b(deals?|opportunit\w*|pipeline)\b/, /\b(deals?|opportunit\w*|pipeline)\b.*\bstages?\b/, /\bfunnel\b/] },
  { id: 'opps.open', group: 'Deals', question: 'How big is our open pipeline?', patterns: [/\bpipeline\b/, new RegExp(String.raw`\bopen ${DEAL}\b`), new RegExp(String.raw`\b(how many|number of|count|total)\b.*\b${DEAL}\b`), new RegExp(String.raw`^${DEAL}$`)] },

  // ---- Accounts ----
  { id: 'accounts.noContacts', group: 'Accounts', question: 'Which accounts have no contacts?', patterns: [/\baccounts?\b.*\b(no|without|missing|zero|empty)\b.*\bcontacts?\b/] },
  { id: 'accounts.count', group: 'Accounts', question: 'How many accounts do we have?', patterns: [/\b(how many|number of|count|total)\b.*\b(accounts?|customers?|companies)\b/, /^accounts?$/] },

  // ---- Contacts ----
  { id: 'contacts.noEmail', group: 'Contacts', question: 'How many contacts have no email?', patterns: [/\bcontacts?\b.*\b(no|without|missing)\b.*\be ?mails?\b/, /\b(no|missing) e ?mails?\b/] },
  { id: 'contacts.noAccount', group: 'Contacts', question: 'Which contacts aren’t linked to an account?', patterns: [/\bcontacts?\b.*\b(no|without|not linked|not connected|missing|isn'?t linked|aren'?t linked)\b.*\b(account|company)\b/, /\borphan\w* contacts?\b/] },
];

export function matchCrmQuestion(normalized: string): CrmQuestion | null {
  return CRM_QUESTIONS.find((q) => q.patterns.some((p) => p.test(normalized))) ?? null;
}

/** A small, varied set of example data questions for suggestion chips. */
export const CRM_EXAMPLES = ['opps.open', 'leads.unassigned', 'opps.overdue', 'contacts.noEmail']
  .map((id) => CRM_QUESTIONS.find((q) => q.id === id)!.question);

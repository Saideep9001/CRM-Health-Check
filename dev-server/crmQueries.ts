/**
 * Fixed, read-only Salesforce lookups for the help assistant ("Ask Aqua").
 *
 * The browser sends only a question id; the SOQL lives here on the server and is never
 * built from user text. Queries run with the connected user's token, so Salesforce's
 * own sharing rules and field permissions apply.
 */
import type { CrmAnswer, CrmRow } from '../src/types';

export interface SoqlResult {
  totalSize: number;
  done: boolean;
  records: Record<string, unknown>[];
}

type Soql = (query: string) => Promise<SoqlResult>;
type Runner = (soql: Soql, instanceUrl: string) => Promise<Omit<CrmAnswer, 'id' | 'asOf'>>;

const LIST_LIMIT = 10;
const n = (v: unknown) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(Number(v ?? 0));
const d = (v: unknown) => (v ? new Date(`${String(v).slice(0, 10)}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—');
const str = (v: unknown, fallback = '—') => (v === null || v === undefined || v === '' ? fallback : String(v));
const recordUrl = (base: string, obj: string, id: unknown) => `${base}/lightning/r/${obj}/${String(id)}/view`;
const listUrl = (base: string, obj: string) => `${base}/lightning/o/${obj}/list`;
const plural = (count: number, one: string, many = `${one}s`) => `${n(count)} ${count === 1 ? one : many}`;

/** Count + first rows for a WHERE clause. */
async function countAndList(
  soql: Soql,
  base: string,
  obj: 'Lead' | 'Opportunity' | 'Account' | 'Contact',
  fields: string,
  where: string,
  order: string,
  row: (r: Record<string, unknown>) => Omit<CrmRow, 'url'>,
) {
  const [count, list] = await Promise.all([
    soql(`SELECT COUNT() FROM ${obj} WHERE ${where}`),
    soql(`SELECT Id, ${fields} FROM ${obj} WHERE ${where} ORDER BY ${order} LIMIT ${LIST_LIMIT}`),
  ]);
  return {
    total: count.totalSize,
    rows: list.records.map((r) => ({ ...row(r), url: recordUrl(base, obj, r.Id) })),
    salesforceUrl: listUrl(base, obj),
  };
}

const RUNNERS: Record<string, Runner> = {
  'leads.open': async (soql, base) => {
    const r = await soql('SELECT COUNT() FROM Lead WHERE IsConverted = false');
    return { title: 'Open leads', summary: `You have **${plural(r.totalSize, 'open lead')}** (not yet converted).`, total: r.totalSize, rows: [], salesforceUrl: listUrl(base, 'Lead') };
  },

  'leads.new': async (soql, base) => {
    const x = await countAndList(soql, base, 'Lead', 'Name, Company, LeadSource, CreatedDate', 'CreatedDate = THIS_MONTH', 'CreatedDate DESC', (r) => ({
      label: str(r.Name),
      detail: `${str(r.Company, 'No company')} · ${str(r.LeadSource, 'No source')} · ${d(r.CreatedDate)}`,
    }));
    return { title: 'New leads this month', summary: `**${plural(x.total, 'new lead')}** so far this month.`, ...x };
  },

  'leads.unassigned': async (soql, base) => {
    const x = await countAndList(soql, base, 'Lead', 'Name, Company, Owner.Name, CreatedDate', "IsConverted = false AND Owner.Type = 'Queue'", 'CreatedDate ASC', (r) => ({
      label: str(r.Name),
      detail: `${str(r.Company, 'No company')} · waiting in ${str((r.Owner as { Name?: string } | null)?.Name, 'a queue')} since ${d(r.CreatedDate)}`,
    }));
    return {
      title: 'Unassigned leads',
      summary: x.total ? `**${plural(x.total, 'lead')}** ${x.total === 1 ? 'is' : 'are'} sitting in a queue with no salesperson. Oldest first:` : 'Every open lead has a salesperson. Nice!',
      ...x,
    };
  },

  'leads.stale': async (soql, base) => {
    const x = await countAndList(soql, base, 'Lead', 'Name, Company, Owner.Name, LastModifiedDate', 'IsConverted = false AND LastModifiedDate < LAST_N_DAYS:30', 'LastModifiedDate ASC', (r) => ({
      label: str(r.Name),
      detail: `${str(r.Company, 'No company')} · ${str((r.Owner as { Name?: string } | null)?.Name, 'No owner')} · last updated ${d(r.LastModifiedDate)}`,
    }));
    return { title: 'Quiet leads (30+ days)', summary: x.total ? `**${plural(x.total, 'open lead')}** haven’t been updated in over 30 days. Oldest first:` : 'No open leads have gone quiet. Great!', ...x };
  },

  'leads.bySource': async (soql, base) => {
    const r = await soql('SELECT LeadSource, COUNT(Id) total FROM Lead WHERE CreatedDate = LAST_N_DAYS:90 GROUP BY LeadSource ORDER BY COUNT(Id) DESC LIMIT 10');
    const sum = r.records.reduce((a, x) => a + Number(x.total ?? 0), 0);
    return {
      title: 'Where leads came from (last 90 days)',
      summary: sum ? `**${plural(sum, 'lead')}** in the last 90 days:` : 'No leads were created in the last 90 days.',
      total: sum,
      rows: r.records.map((x) => ({ label: str(x.LeadSource, 'No source recorded'), detail: `${n(x.total)} (${Math.round((Number(x.total) / sum) * 100)}%)` })),
      salesforceUrl: listUrl(base, 'Lead'),
    };
  },

  'opps.open': async (soql, base) => {
    const r = await soql('SELECT COUNT(Id) deals, SUM(Amount) amount FROM Opportunity WHERE IsClosed = false');
    const row = r.records[0] ?? {};
    const deals = Number(row.deals ?? 0);
    return {
      title: 'Open pipeline',
      summary: `You have **${plural(deals, 'open deal')}** worth **${n(row.amount)}** in total.`,
      total: deals,
      rows: [],
      salesforceUrl: listUrl(base, 'Opportunity'),
    };
  },

  'opps.closingThisMonth': async (soql, base) => {
    const x = await countAndList(soql, base, 'Opportunity', 'Name, Amount, StageName, CloseDate, Owner.Name', 'IsClosed = false AND CloseDate = THIS_MONTH', 'CloseDate ASC', (r) => ({
      label: str(r.Name),
      detail: `${n(r.Amount)} · ${str(r.StageName)} · closes ${d(r.CloseDate)} · ${str((r.Owner as { Name?: string } | null)?.Name, 'No owner')}`,
    }));
    return { title: 'Deals closing this month', summary: x.total ? `**${plural(x.total, 'open deal')}** ${x.total === 1 ? 'is' : 'are'} due to close this month:` : 'No open deals are due to close this month.', ...x };
  },

  'opps.overdue': async (soql, base) => {
    const x = await countAndList(soql, base, 'Opportunity', 'Name, Amount, StageName, CloseDate, Owner.Name', 'IsClosed = false AND CloseDate < TODAY', 'CloseDate ASC', (r) => ({
      label: str(r.Name),
      detail: `${n(r.Amount)} · ${str(r.StageName)} · was due ${d(r.CloseDate)} · ${str((r.Owner as { Name?: string } | null)?.Name, 'No owner')}`,
    }));
    return {
      title: 'Overdue deals',
      summary: x.total ? `**${plural(x.total, 'deal')}** ${x.total === 1 ? 'is' : 'are'} still open past ${x.total === 1 ? 'its' : 'their'} close date. Most overdue first:` : 'No overdue deals. Your close dates are up to date!',
      ...x,
    };
  },

  'opps.byStage': async (soql, base) => {
    const r = await soql('SELECT StageName, COUNT(Id) deals, SUM(Amount) amount FROM Opportunity WHERE IsClosed = false GROUP BY StageName ORDER BY COUNT(Id) DESC');
    const total = r.records.reduce((a, x) => a + Number(x.deals ?? 0), 0);
    return {
      title: 'Open deals by stage',
      summary: total ? `**${plural(total, 'open deal')}** across ${plural(r.records.length, 'stage')}:` : 'There are no open deals.',
      total,
      rows: r.records.map((x) => ({ label: str(x.StageName), detail: `${plural(Number(x.deals), 'deal')} · ${n(x.amount)}` })),
      salesforceUrl: listUrl(base, 'Opportunity'),
    };
  },

  'opps.top': async (soql, base) => {
    const r = await soql('SELECT Id, Name, Amount, StageName, CloseDate, Account.Name FROM Opportunity WHERE IsClosed = false AND Amount != null ORDER BY Amount DESC LIMIT 5');
    return {
      title: 'Biggest open deals',
      summary: r.records.length ? `Your ${r.records.length === 1 ? 'largest open deal' : `${r.records.length} largest open deals`}:` : 'No open deals have an amount yet.',
      total: r.records.length,
      rows: r.records.map((x) => ({
        label: str(x.Name),
        detail: `${n(x.Amount)} · ${str((x.Account as { Name?: string } | null)?.Name, 'No account')} · ${str(x.StageName)} · closes ${d(x.CloseDate)}`,
        url: recordUrl(base, 'Opportunity', x.Id),
      })),
      salesforceUrl: listUrl(base, 'Opportunity'),
    };
  },

  'opps.wonThisQuarter': async (soql, base) => {
    const r = await soql('SELECT COUNT(Id) deals, SUM(Amount) amount FROM Opportunity WHERE IsWon = true AND CloseDate = THIS_QUARTER');
    const row = r.records[0] ?? {};
    const deals = Number(row.deals ?? 0);
    return {
      title: 'Won this quarter',
      summary: deals ? `You’ve won **${plural(deals, 'deal')}** worth **${n(row.amount)}** this quarter.` : 'No deals have been won yet this quarter.',
      total: deals,
      rows: [],
      salesforceUrl: listUrl(base, 'Opportunity'),
    };
  },

  'accounts.count': async (soql, base) => {
    const r = await soql('SELECT COUNT() FROM Account');
    return { title: 'Accounts', summary: `You have **${plural(r.totalSize, 'account')}** in Salesforce.`, total: r.totalSize, rows: [], salesforceUrl: listUrl(base, 'Account') };
  },

  'accounts.noContacts': async (soql, base) => {
    const x = await countAndList(soql, base, 'Account', 'Name, Owner.Name, CreatedDate', 'Id NOT IN (SELECT AccountId FROM Contact WHERE AccountId != null)', 'CreatedDate DESC', (r) => ({
      label: str(r.Name),
      detail: `${str((r.Owner as { Name?: string } | null)?.Name, 'No owner')} · added ${d(r.CreatedDate)}`,
    }));
    return { title: 'Accounts with no contacts', summary: x.total ? `**${plural(x.total, 'account')}** ${x.total === 1 ? 'has' : 'have'} no contacts. Newest first:` : 'Every account has at least one contact.', ...x };
  },

  'contacts.noEmail': async (soql, base) => {
    const x = await countAndList(soql, base, 'Contact', 'Name, Account.Name, Phone', 'Email = null', 'LastModifiedDate DESC', (r) => ({
      label: str(r.Name),
      detail: `${str((r.Account as { Name?: string } | null)?.Name, 'No account')} · ${r.Phone ? 'has a phone number' : 'no phone either'}`,
    }));
    return { title: 'Contacts with no email', summary: x.total ? `**${plural(x.total, 'contact')}** ${x.total === 1 ? 'has' : 'have'} no email address:` : 'Every contact has an email address.', ...x };
  },

  'contacts.noAccount': async (soql, base) => {
    const x = await countAndList(soql, base, 'Contact', 'Name, Email, Owner.Name', 'AccountId = null', 'LastModifiedDate DESC', (r) => ({
      label: str(r.Name),
      detail: `${str(r.Email, 'No email')} · ${str((r.Owner as { Name?: string } | null)?.Name, 'No owner')}`,
    }));
    return {
      title: 'Contacts not linked to an account',
      summary: x.total ? `**${plural(x.total, 'contact')}** ${x.total === 1 ? 'isn’t' : 'aren’t'} linked to any account, so only their owner can see them:` : 'Every contact is linked to an account.',
      ...x,
    };
  },
};

export const CRM_QUERY_IDS = Object.keys(RUNNERS);

export async function runCrmQuery(id: string, soql: Soql, instanceUrl: string): Promise<CrmAnswer> {
  const runner = RUNNERS[id];
  if (!runner) throw Object.assign(new Error('Unknown question.'), { status: 422 });
  const result = await runner(soql, instanceUrl.replace(/\/$/, ''));
  return { id, asOf: new Date().toISOString(), ...result };
}

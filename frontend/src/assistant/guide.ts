/**
 * Built-in guide: a deterministic, offline answer engine for the help assistant.
 * Answers come only from the app's own configuration (topics, areas, glossary)
 * and the user's live data passed in `ctx` — nothing is invented.
 */
import { CATEGORIES, DIAGNOSTIC_AREAS, getAreasForCategory, getCategory } from '@/config/categories';
import { CRM_EXAMPLES, CRM_QUESTIONS, matchCrmQuestion } from '@/config/crmQuestions';
import { GLOSSARY, SCORE_BANDS, URGENCY_HELP } from '@/config/glossary';
import { scoreBand } from '@/lib/format';
import { countBySeverity, SEVERITY_RANK } from '@/lib/health';
import type { Assessment, AssessmentResults, Finding, SalesforceConnection } from '@/types';

export interface GuideContext {
  pathname: string;
  connection: SalesforceConnection | null;
  latest: Assessment | null;
  findings: Finding[];
  /** Scores of the latest check (topics, areas, fixed problems). */
  results?: AssessmentResults | null;
  running: boolean;
}

export interface GuideAnswer {
  /** Markdown-lite: paragraphs, "- " bullets, **bold**, [label](/path). */
  text: string;
  suggestions?: string[];
  /** Set when the question is a live Salesforce data question; the widget runs the lookup. */
  crm?: string;
  /** No rule matched; the widget may try the org's data instead. */
  fallback?: boolean;
}

const DEFAULT_SUGGESTIONS = ['How do I get started?', 'What should I fix first?', 'What can I ask about my data?', 'Is my data safe?'];
const DATA_SUGGESTIONS = ['How many open deals do we have?', 'Open deals by stage', 'Biggest open deals', 'Leads by source'];

const norm = (s: string) => s.toLowerCase().replace(/[’']/g, "'").replace(/[^a-z0-9#' ]+/g, ' ').replace(/\s+/g, ' ').trim();
const has = (q: string, ...words: (string | RegExp)[]) => words.some((w) => (typeof w === 'string' ? q.includes(w) : w.test(q)));

function connected(ctx: GuideContext) {
  return ctx.connection?.status === 'connected';
}

function nextStep(ctx: GuideContext): string {
  if (!connected(ctx)) return 'Your next step is to **connect your Salesforce** — [Connect Salesforce](/connection).';
  if (ctx.running) return 'A health check is **running right now** — [see its progress](/history).';
  if (!ctx.latest) return 'Your Salesforce is connected, so the next step is to [run your first health check](/assessment).';
  return `Your latest check is **${ctx.latest.name}**. [See its results](/results?assessment=${encodeURIComponent(ctx.latest.id)}).`;
}

// ---------------------------------------------------------------------------
// Intent handlers. Each returns an answer or null if it doesn't apply.
// ---------------------------------------------------------------------------

type Handler = (q: string, ctx: GuideContext) => GuideAnswer | null;

const greeting: Handler = (q, ctx) =>
  /^(hi|hello|hey|good (morning|afternoon|evening)|hiya|yo)\b/.test(q) && q.split(' ').length <= 4
    ? {
        text: `Hi! I’m Aqua, your health check guide. I can explain what anything means, tell you how to do things, and point you to the right page.\n\n${nextStep(ctx)}`,
        suggestions: DEFAULT_SUGGESTIONS,
      }
    : null;

const thanks: Handler = (q) =>
  /^(thanks|thank you|thx|cheers|great|perfect|ok|okay|cool)\b/.test(q) && q.split(' ').length <= 4
    ? { text: 'You’re welcome! Ask me anything else whenever you need.', suggestions: DEFAULT_SUGGESTIONS }
    : null;

const getStarted: Handler = (q, ctx) =>
  has(q, 'get started', 'getting started', 'start', 'begin', 'first time', 'new here', 'how does this work', 'how does it work', 'what do i do', 'what should i do', 'how to use', 'what is this', 'what does this do')
    && !has(q, 'fix')
    ? {
        text: [
          'Using the platform takes three steps:',
          '- **Connect Salesforce** — sign in on Salesforce’s secure page (about a minute).',
          '- **Run a health check** — keep the default choices and press Start.',
          '- **Fix what matters** — open My Results and work from Critical problems down.',
          '',
          nextStep(ctx),
        ].join('\n'),
        suggestions: ['How do I connect Salesforce?', 'How do I run a health check?', 'Is my data safe?'],
      }
    : null;

const connectionStatus: Handler = (q, ctx) => {
  if (!has(q, /\b(am i|is (it|my salesforce|salesforce)|are we)\b.*connected/, 'connection status', 'connected?')) return null;
  const c = ctx.connection;
  if (!c) return { text: 'I couldn’t check the connection just now. Open [Connect Salesforce](/connection) to see the current status.' };
  if (c.status === 'connected') return { text: `Yes — you’re connected to **${c.organizationName ?? 'your Salesforce'}**. ${nextStep(ctx)}` };
  if (c.status === 'expired') return { text: 'Your Salesforce connection has **timed out**. Go to [Connect Salesforce](/connection) and click **Reconnect**.' };
  if (c.status === 'error') return { text: `There’s a problem with the connection${c.errorMessage ? `: ${c.errorMessage}` : '.'} Try **Check connection** on the [Connect Salesforce](/connection) page.` };
  return { text: 'Not yet — your Salesforce isn’t connected. [Connect Salesforce](/connection) to get started.' };
};

const browseData: Handler = (q, ctx) =>
  has(q, 'your data page', 'see my data', 'see all my data', 'view my data', 'browse', 'all records', 'all objects', 'which objects', 'what objects', 'list of fields', 'what fields', 'data view', 'explore')
    ? {
        text: [
          'Open [Your Data](/data) to browse your Salesforce:',
          '- Pick any **object** (Accounts, Leads, custom objects…) on the left.',
          '- **Records** lists its records — search by name, sort, and choose columns.',
          '- **Fields** lists every field, its type, and whether it’s required.',
          '- Click a record to see all its details, or open it in Salesforce.',
          '',
          connected(ctx) ? 'It’s read-only — nothing can be changed there.' : 'Connect Salesforce first — [Connect Salesforce](/connection).',
        ].join('\n'),
      }
    : null;

const howConnect: Handler = (q) =>
  has(q, 'connect', 'link salesforce', 'log in to salesforce', 'login to salesforce', 'sign in to salesforce', 'oauth', 'sandbox', 'my domain')
    ? {
        text: [
          'To connect your Salesforce:',
          '- Go to [Connect Salesforce](/connection) and click **Connect Salesforce**.',
          '- Choose **My live Salesforce** (most people) or **A test copy (sandbox)**.',
          '- Salesforce opens its own sign-in page — log in and click **Allow**.',
          '- You’re brought back here, connected.',
          '',
          'We only ever **read** your data, and we never see your Salesforce password.',
        ].join('\n'),
        suggestions: ['Is my data safe?', 'What is a sandbox?', 'How do I run a health check?'],
      }
    : null;

const howRun: Handler = (q, ctx) =>
  has(q, 'run', 'start a', 'start the', 'new check', 'new health check', 'scan', 'how do i check', 'kick off', 'launch')
    ? {
        text: [
          'To run a health check:',
          '- Open [What We Check](/assessment) to check everything that’s ready, or open a topic (like [Data Quality](/assessment/data-quality)) to check just that.',
          '- Press **Check** — progress shows right on the page. It takes about a minute.',
          '- You can leave the page; it keeps running.',
          '',
          connected(ctx) ? 'You’re connected, so you’re ready to go.' : 'You’ll need to [connect Salesforce](/connection) first.',
        ].join('\n'),
        suggestions: ['How long does a check take?', 'What does Coming Soon mean?'],
      }
    : null;

const howLong: Handler = (q) =>
  has(q, 'how long', 'take long', 'how much time', 'duration')
    ? { text: 'It depends on how big your Salesforce is — small ones finish in minutes, larger ones take longer. You can leave the page; [Check History](/history) shows progress and results appear when it’s done.' }
    : null;

const myScore: Handler = (q, ctx) => {
  if (!has(q, 'my score', 'our score', 'how am i doing', 'how are we doing', 'how healthy', 'overall score', 'health score', 'what is my health', 'overall health')) return null;
  if (!ctx.latest) return { text: `You don’t have a score yet — scores appear after your first health check. ${nextStep(ctx)}` };
  const s = ctx.latest.overallScore;
  if (s === null) return { text: `Your latest check (**${ctx.latest.name}**) didn’t produce an overall score. [See its results](/results?assessment=${encodeURIComponent(ctx.latest.id)}).` };
  const band = scoreBand(s);
  return {
    text: `Your latest overall score is **${s} out of 100** — that’s **${band.label}**.\n\n${
      s >= 80 ? 'Your Salesforce is in good shape. Keep an eye on any remaining problems.' : s >= 65 ? 'Things are working, but there are gaps worth fixing.' : 'There are problems that are likely affecting your sales team — start with the Critical ones.'
    }\n\n[See the overview](/dashboard) · [See problems](/results?assessment=${encodeURIComponent(ctx.latest.id)})`,
    suggestions: ['What should I fix first?', 'What does my score mean?'],
  };
};

const fixFirst: Handler = (q, ctx) => {
  if (!has(q, 'fix first', 'start with', 'priorit', 'most important', 'top problem', 'biggest problem', 'worst', 'critical', 'what should i fix', 'where do i start', 'urgent')) return null;
  if (!ctx.latest) return { text: `Once you’ve run a health check I can tell you exactly what to fix first. ${nextStep(ctx)}` };
  const open = ctx.findings.filter((f) => f.status === 'open' || f.status === 'in-review');
  if (!open.length) return { text: 'Great news — there are no open problems in your latest health check.' };
  const top = [...open].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || a.priority.localeCompare(b.priority) || b.affectedRecords - a.affectedRecords).slice(0, 3);
  const sev = countBySeverity(open);
  return {
    text: [
      `You have **${open.length} open problems** (${sev.critical} critical, ${sev.high} high). Start with these:`,
      ...top.map((f) => `- **${f.name}** (${f.severity}) — ${f.recommendedAction}`),
      '',
      `[See all critical problems](/results?assessment=${encodeURIComponent(ctx.latest.id)}&severity=critical)`,
    ].join('\n'),
    suggestions: ['What does urgency mean?', 'How do I mark a problem as fixed?'],
  };
};

const scoreMeaning: Handler = (q) =>
  has(q, 'score mean', 'scores mean', 'what is a score', 'what does the score', 'colour', 'color', 'healthy', 'fair', 'needs attention', '0 to 100', 'out of 100')
    ? {
        text: ['Scores run from **0 to 100** — higher is healthier:', ...SCORE_BANDS.map((b) => `- **${b.label}**: ${b.text}`), '', 'Each topic and area has its own score, plus one overall score for your whole Salesforce.'].join('\n'),
      }
    : null;

const urgencyMeaning: Handler = (q) =>
  has(q, 'urgency', 'severity', 'critical mean', 'high mean', 'medium mean', 'low mean', 'how serious')
    ? { text: ['Every problem has an urgency level:', ...Object.entries(URGENCY_HELP).map(([k, v]) => `- **${k[0].toUpperCase() + k.slice(1)}**: ${v}`)].join('\n') }
    : null;

const markFixed: Handler = (q) =>
  has(q, 'mark', 'resolved', 'fixed', 'done', 'track', 'progress', 'assign', 'notes', 'accepted risk')
    ? {
        text: [
          'To track a fix:',
          '- Open [My Results](/results) and click the problem.',
          '- In the panel, use **Where are you with this?** — choose In Review, Resolved, or Accepted Risk (decided not to fix).',
          '- Add a note (for example who’s fixing it) and click **Save changes**.',
        ].join('\n'),
      }
    : null;

const reports: Handler = (q) =>
  has(q, 'report', 'export', 'download', 'pdf', 'csv', 'spreadsheet', 'excel', 'share', 'print', 'manager', 'leadership', 'boss')
    ? {
        text: [
          'Reports are ready-made summaries you can share:',
          '- Open [Reports](/reports) and pick a report (the **Leadership summary** is best for managers).',
          '- Use **Print**, **Download spreadsheet (CSV)**, or **Download PDF**.',
        ].join('\n'),
      }
    : null;

const safety: Handler = (q) =>
  has(q, 'safe', 'secure', 'security', 'password', 'privacy', 'change my data', 'delete', 'modify', 'read only', 'read-only', 'access to')
    ? {
        text: [
          'Your data is safe:',
          '- The platform has **read-only** access — it can look, but never change or delete anything.',
          '- You sign in on **Salesforce’s own page**; we never see your Salesforce password.',
          '- Access keys are stored on our server, never in your browser.',
          '- You can [disconnect](/connection) at any time.',
        ].join('\n'),
      }
    : null;

const comingSoon: Handler = (q) =>
  has(q, 'coming soon', 'not available', 'greyed', 'grayed', 'disabled', 'not ready', 'engine', /\b(can'?t|cannot|unable to)( \w+){0,2} (select|choose|tick|pick|check|run)\b/)
    ? {
        text: `**Coming Soon** topics are shown so you can see everything that will be covered, but they can’t be checked yet. Right now that’s ${CATEGORIES.filter((c) => c.release === 'coming-soon')
          .map((c) => `**${c.name}**`)
          .join(' and ')}. An area marked “Not ready yet” in the health check form means the checking engine doesn’t support it yet.`,
      }
    : null;

const history: Handler = (q) =>
  has(q, 'history', 'previous', 'past check', 'compare', 'improv', 'over time', 'trend', 'how often')
    ? { text: '[Check History](/history) lists every health check you’ve run. The Overview’s **Health score over time** chart shows how your score changes. Running a check once a quarter works well for most teams.' }
    : null;

const appSettings: Handler = (q) =>
  has(q, 'dark mode', 'light mode', 'theme', 'notification', 'email me', 'settings', 'profile', 'animation', 'motion')
    ? { text: 'You can change the theme (light or dark), notifications, and your profile in [Settings](/settings). The sun/moon button in the top bar switches the theme instantly.' }
    : null;

const tour: Handler = (q) =>
  has(q, 'tour', 'tutorial', 'guide me', 'show me around', 'help page', 'glossary', 'faq')
    ? { text: 'The [Help & guide](/help) page has a 3-step overview, what scores and urgency mean, a glossary, and common questions. You can replay the quick tour from there too.' }
    : null;

const topicsList: Handler = (q) =>
  has(q, 'what do you check', 'what is checked', 'what gets checked', 'which topics', 'all topics', 'list topics', 'what topics', 'what areas', 'six topics', '21 areas')
    ? {
        text: [`A health check covers **${CATEGORIES.length} topics** with **${DIAGNOSTIC_AREAS.length} areas** in total:`, ...CATEGORIES.map((c) => `- [${c.name}](/assessment/${c.id}) — ${c.areaIds.length} areas${c.release === 'coming-soon' ? ' (Coming Soon)' : ''}`)].join('\n'),
      }
    : null;

const STOP = new Set(['what', 'with', 'from', 'that', 'this', 'have', 'does', 'mean', 'about', 'your', 'there', 'where', 'which', 'when', 'tell', 'show', 'they', 'them', 'into', 'more', 'some', 'many', 'much', 'should', 'would', 'could']);

function describeArea(area: (typeof DIAGNOSTIC_AREAS)[number]): GuideAnswer {
  const cat = getCategory(area.categoryId)!;
  return {
    text: [
      `**Area ${area.number}: ${area.name}** (part of ${cat.name}${cat.release === 'coming-soon' ? ', Coming Soon' : ''})`,
      area.description,
      '',
      'It looks at:',
      ...area.indicators.map((i) => `- ${i}`),
      '',
      `[Open this area](/assessment/${area.categoryId}/${area.id})`,
    ].join('\n'),
  };
}

/** "Area 5", "check 12", "#3". */
const areaNumber: Handler = (q) => {
  const num = q.match(/\b(?:area|check|#)\s*#?(\d{1,2})\b/);
  const area = num ? DIAGNOSTIC_AREAS.find((a) => a.number === Number(num[1])) : undefined;
  return area ? describeArea(area) : null;
};

/** Last resort: the question mentions things an area measures (e.g. "duplicate contacts"). */
const areaKeywords: Handler = (q) => {
  const words = q.split(' ').filter((w) => w.length > 3 && !STOP.has(w));
  let best = 0;
  let area: (typeof DIAGNOSTIC_AREAS)[number] | undefined;
  for (const a of DIAGNOSTIC_AREAS) {
    const hay = norm(`${a.name} ${a.indicators.join(' ')}`).split(' ');
    const score = words.filter((w) => hay.some((h) => h === w || h === `${w}s` || `${h}s` === w)).length;
    if (score > best && score >= 2) {
      best = score;
      area = a;
    }
  }
  return area ? describeArea(area) : null;
};

const topicLookup: Handler = (q) => {
  const cat = CATEGORIES.find((c) => q.includes(norm(c.name)) || q.includes(norm(c.shortName)));
  if (!cat) return null;
  const areas = getAreasForCategory(cat.id);
  return {
    text: [
      `**${cat.name}**${cat.release === 'coming-soon' ? ' (Coming Soon)' : ''}`,
      cat.purpose,
      '',
      `It has ${areas.length} areas:`,
      ...areas.map((a) => `- [Area ${a.number}: ${a.name}](/assessment/${cat.id}/${a.id})`),
    ].join('\n'),
  };
};

const glossaryLookup: Handler = (q) => {
  const g = GLOSSARY.find((e) => {
    const t = norm(e.term.replace(/\(.*?\)/g, ''));
    return q.includes(t) || (t.endsWith('s') ? false : q.includes(`${t}s`));
  });
  if (!g) return null;
  // Only definition-style questions ("what is a sandbox", "what does progress mean") or the bare term itself.
  const definitional = /^(what (is|are|'s|s|does)|whats|define|meaning of|explain|tell me what)\b/.test(q) || / mean\b/.test(q);
  if (!definitional && q !== norm(g.term.replace(/\(.*?\)/g, ''))) return null;
  return { text: `**${g.term}** — ${g.plain}${g.example ? `\n\nFor example: ${g.example}` : ''}` };
};

const pageHelp: Handler = (q, ctx) => {
  if (!has(q, 'this page', 'where am i', 'what is here', "what's here", 'what am i looking at')) return null;
  const p = ctx.pathname;
  const map: [RegExp, string][] = [
    [/^\/dashboard/, 'This is the **Overview** — your overall score, problems by urgency, and how each topic scored.'],
    [/^\/connection/, 'This is **Connect Salesforce** — where you link (or disconnect) your Salesforce.'],
    [/^\/assessment\/new/, 'This is the **health check form** — choose what to check, then press Start.'],
    [/^\/assessment\/[^/]+\/[^/]+/, 'This is an **area page** — what this area checks, its measurements, problems found, and how to fix them.'],
    [/^\/assessment\/[^/]+/, 'This is a **topic page** — its score and the areas inside it.'],
    [/^\/assessment/, 'This is **What We Check** — all six topics and 21 areas.'],
    [/^\/results/, 'This is **My Results** — every problem found, with filters. Click a problem to see how to fix it.'],
    [/^\/reports/, 'This is **Reports** — ready-made summaries to print or download.'],
    [/^\/history/, 'This is **Check History** — every health check you’ve run.'],
    [/^\/settings/, 'This is **Settings** — theme, notifications, and profile.'],
    [/^\/help/, 'This is **Help & guide** — explanations, a glossary, and common questions.'],
  ];
  const hit = map.find(([re]) => re.test(p));
  return { text: hit ? hit[1] : 'Use the menu on the left to move between pages. [Help & guide](/help) explains each one.' };
};

/** "What can I ask about my data?" — lists every live data question. */
const dataCatalog: Handler = (q, ctx) => {
  if (!has(q, 'my data', 'our data', 'salesforce data', 'crm data', 'what can i ask', 'what can you tell me', 'what do you know', 'questions can i ask', 'data questions')) return null;
  const groups = [...new Set(CRM_QUESTIONS.map((c) => c.group))];
  return {
    text: [
      connected(ctx)
        ? `I can look these up live in **${ctx.connection?.organizationName ?? 'your Salesforce'}** (read-only):`
        : 'Once Salesforce is connected, I can look these up for you (read-only):',
      ...groups.map((g) => `- **${g}:** ${CRM_QUESTIONS.filter((c) => c.group === g).map((c) => c.question.replace(/\?$/, '')).join(' · ')}`),
      '',
      '',
      'You can also ask in your own words, for example:',
      '- “How many open deals over 50k close this month?” · “Total pipeline” · “Average won deal this year”',
      '- “Open deals by stage” · “Leads by source” · “Cases by priority” · “Opportunities by owner”',
      '- “Who is Emily Davis?” · “Find Acme” · “What edition is our org?” · “Overdue tasks”',
      '',
      'I can also explain anything about the platform — scores, problems, topics, and how-tos.',
      connected(ctx) ? '' : '[Connect Salesforce](/connection)',
    ].join('\n'),
    suggestions: CRM_EXAMPLES,
  };
};

/** Live Salesforce data questions — answered by a fixed read-only lookup, not by guessing. */
const crmData: Handler = (q, ctx) => {
  const match = matchCrmQuestion(q);
  if (!match) return null;
  if (!connected(ctx)) {
    return {
      text: `I can answer “${match.question}” straight from your Salesforce once it’s connected. [Connect Salesforce](/connection)`,
      suggestions: ['How do I connect Salesforce?', 'Is my data safe?'],
    };
  }
  return { text: '', crm: match.id };
};

// ---------------------------------------------------------------------------
// Results of the latest health check: topic/area scores, problem counts, changes, and any named problem.
// ---------------------------------------------------------------------------

const PLATFORM_WORDS = /\b(score|scores|problem|problems|issue|issues|finding|findings|health check|check|checks|topic|topics|area|areas|report|reports|platform|portfolio|schedule|alert|alerts|proposal|sow|branding|team|role|roles|password|sign|login|log in|benchmark|fix plan|priority|urgency|severity|critical|resolved|fixed)\b/;
const DATA_WORDS = /\b(accounts?|contacts?|leads?|deals?|opportunit\w*|opps?|cases?|tasks?|events?|meetings?|pipeline|quotes?|products?|campaigns?|orders?|contracts?|users?|reps?|revenue|customers?|compan(?:y|ies)|tickets?|activities|records?|owners?|edition|org id|instance|api calls|storage|licen[cs]es?)\b/;
const LOOKUP_START = /^(who is|who's|whos|find|look up|lookup|search for|tell me about|details (of|for|on)|info (on|about))\b/;

/** True when a question is about the org's Salesforce data (records, counts, totals), not about the platform. */
export function isDataQuestion(raw: string, ctx?: GuideContext): boolean {
  const q = norm(raw);
  // "How do I add a user?" is a how-to, not a data question.
  if (/^(how (do|can|should|to)|where|can i|could i|what can|what does|what is a|what are)\b/.test(q)) return false;
  // A problem from the latest check ("duplicate accounts") is answered from the results.
  if (ctx && findingLookup(q, ctx)) return false;
  if (LOOKUP_START.test(q) && !PLATFORM_WORDS.test(q)) return true;
  if (!DATA_WORDS.test(q)) return false;
  // "duplicate accounts problem", "score for accounts" are about results, not raw data.
  return !/\b(score|problem|problems|issue|issues|finding|findings|fix|check)\b/.test(q);
}

function resultsLink(ctx: GuideContext, extra = '') {
  return ctx.latest ? `/results?assessment=${encodeURIComponent(ctx.latest.id)}${extra}` : '/results';
}

const openFindings = (ctx: GuideContext) => ctx.findings.filter((f) => f.status === 'open' || f.status === 'in-review');

/** "How is Data Quality doing?", "Workflows score", "area 5 score", "which topic is worst?" */
const topicScores: Handler = (q, ctx) => {
  const asksScore = has(q, 'score', 'doing', 'how is', 'how are', 'healthy', 'health of', 'rating', 'worst', 'best', 'weakest', 'strongest');
  if (!asksScore) return null;
  const areaNum = q.match(/\barea\s*#?(\d{1,2})\b/);
  const cat = CATEGORIES.find((c) => q.includes(norm(c.name)) || q.includes(norm(c.shortName)));
  const ranking = has(q, 'worst', 'best', 'weakest', 'strongest', 'lowest', 'highest', 'all topics', 'each topic', 'every topic', 'by topic');
  if (!areaNum && !cat && !ranking) return null;
  if (!ctx.results) return { text: `There are no results yet — scores appear after a health check. ${nextStep(ctx)}` };
  const r = ctx.results;
  if (areaNum) {
    const area = DIAGNOSTIC_AREAS.find((a) => a.number === Number(areaNum[1]));
    const res = r.areas.find((a) => a.areaId === area?.id);
    if (!area) return null;
    if (!res || res.score === null) return { text: `**Area ${area.number}: ${area.name}** hasn’t been scored yet. [Open it](/assessment/${area.categoryId}/${area.id}) to run it.` };
    return {
      text: [
        `**Area ${area.number}: ${area.name}** scored **${res.score}/100** (${scoreBand(res.score).label}).`,
        ...res.indicators.slice(0, 6).map((i) => `- ${i.label}: **${Math.round(i.value)}${i.unit === '%' ? '%' : ''}**`),
        '',
        `[Open this area](/assessment/${area.categoryId}/${area.id})`,
      ].join('\n'),
    };
  }
  if (cat && !ranking) {
    const s = r.categories.find((c) => c.categoryId === cat.id)?.score ?? null;
    const areas = getAreasForCategory(cat.id).map((a) => ({ a, res: r.areas.find((x) => x.areaId === a.id) }));
    return {
      text: [
        s === null ? `**${cat.name}** hasn’t been scored yet.` : `**${cat.name}** scored **${s}/100** (${scoreBand(s).label}).`,
        ...areas.map(({ a, res }) => `- Area ${a.number}: ${a.name} — **${res?.score ?? '—'}**`),
        '',
        `[Open ${cat.shortName}](/assessment/${cat.id})`,
      ].join('\n'),
    };
  }
  const ranked = r.categories.filter((c) => c.score !== null).sort((a, b) => (a.score ?? 0) - (b.score ?? 0));
  return {
    text: [
      'Topic scores, weakest first:',
      ...ranked.map((c) => `- [${getCategory(c.categoryId)?.name ?? c.categoryId}](/assessment/${c.categoryId}) — **${c.score}** (${scoreBand(c.score).label})`),
    ].join('\n'),
  };
};

/** "How many critical problems?", "problems in reporting", "value at risk", "how many records affected". */
const problemCounts: Handler = (q, ctx) => {
  if (!has(q, 'how many problem', 'how many issue', 'number of problem', 'problems in', 'problems for', 'issues in', 'how many critical', 'how many high', 'how many medium', 'how many low', 'value at risk', 'money at risk', 'at risk', 'records affected', 'affected records', 'open problems', 'list problems', 'all problems')) return null;
  if (!ctx.latest) return { text: `No health check yet, so there are no problems to count. ${nextStep(ctx)}` };
  let open = openFindings(ctx);
  const cat = CATEGORIES.find((c) => q.includes(norm(c.name)) || q.includes(norm(c.shortName)));
  if (cat) open = open.filter((f) => f.categoryId === cat.id);
  const sev = countBySeverity(open);
  const scope = cat ? ` in **${cat.name}**` : '';
  if (has(q, 'at risk')) {
    const withValue = open.filter((f) => f.valueAtRisk).sort((a, b) => (b.valueAtRisk ?? 0) - (a.valueAtRisk ?? 0)).slice(0, 5);
    if (!withValue.length) return { text: `None of the open problems${scope} has a money value attached.` };
    return {
      text: [
        `Problems with the most value at risk${scope} (they can overlap, so don’t add them up):`,
        ...withValue.map((f) => `- **${f.name}** — ${Math.round(f.valueAtRisk ?? 0).toLocaleString('en-US')}`),
        '',
        `[See them in My Results](${resultsLink(ctx)})`,
      ].join('\n'),
    };
  }
  const records = open.reduce((a, f) => a + f.affectedRecords, 0);
  return {
    text: [
      `There are **${open.length} open problems**${scope}: ${sev.critical} critical, ${sev.high} high, ${sev.medium} medium and ${sev.low} low, touching **${records.toLocaleString('en-US')}** records.`,
      ...[...open].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords).slice(0, 5).map((f) => `- **${f.name}** (${f.severity}) — ${f.affectedRecords.toLocaleString('en-US')} records`),
      '',
      `[See all${cat ? ` ${cat.shortName}` : ''} problems](${resultsLink(ctx, cat ? `&category=${cat.id}` : '')})`,
    ].join('\n'),
  };
};

/** "What changed since the last check?", "new problems", "what got worse / better / fixed". */
const changes: Handler = (q, ctx) => {
  if (!has(q, 'what changed', 'changes since', 'since last', 'since the last', 'new problem', 'got worse', 'getting worse', 'got better', 'improved', 'what improved', 'fixed since', 'what was fixed', 'resolved since')) return null;
  if (!ctx.latest) return { text: `No health check yet. ${nextStep(ctx)}` };
  const open = openFindings(ctx);
  const by = (c: string) => open.filter((f) => f.change === c);
  const resolved = ctx.results?.resolved ?? [];
  const list = (fs: Finding[]) => fs.slice(0, 4).map((f) => `- ${f.name}${f.previousAffected != null ? ` (${f.previousAffected.toLocaleString('en-US')} → ${f.affectedRecords.toLocaleString('en-US')})` : ''}`);
  const parts = [
    `Since the previous check: **${by('new').length} new**, **${by('worse').length} worse**, **${by('better').length} better** and **${resolved.length} fixed**.`,
  ];
  if (by('worse').length) parts.push('', 'Got worse:', ...list(by('worse')));
  if (by('new').length) parts.push('', 'New:', ...list(by('new')));
  if (resolved.length) parts.push('', 'Fixed:', ...resolved.slice(0, 4).map((r) => `- ${r.name}`));
  parts.push('', `[See My Results](${resultsLink(ctx)})`);
  return { text: parts.join('\n') };
};

/** "Tell me about duplicate accounts", "stuck deals problem", "why are deals out of sync with quotes". */
const findingLookup: Handler = (q, ctx) => {
  if (!ctx.findings.length) return null;
  const words = q.split(' ').filter((w) => w.length > 2 && !STOP.has(w) && !['problem', 'problems', 'issue', 'the', 'and', 'our', 'fix', 'how'].includes(w));
  if (!words.length) return null;
  let best: { f: Finding; score: number } | null = null;
  for (const f of ctx.findings) {
    const name = norm(f.name);
    const hay = name.split(' ');
    const hit = words.filter((w) => hay.some((h) => h === w || h === `${w}s` || `${h}s` === w || (w.length > 5 && h.startsWith(w.slice(0, 5))))).length;
    const score = q.includes(name) ? 99 : hit / Math.max(hay.length, 2);
    if (hit >= 2 && score >= 0.5 && (!best || score > best.score)) best = { f, score };
  }
  if (!best) return null;
  const f = best.f;
  const area = DIAGNOSTIC_AREAS.find((a) => a.id === f.areaId);
  return {
    text: [
      `**${f.name}** — ${f.severity}${area ? ` · Area ${area.number}: ${area.name}` : ''}`,
      f.description,
      `**Why it matters:** ${f.whyItMatters}`,
      `**How to fix it:** ${f.recommendedAction}`,
      f.valueAtRisk ? `**Value at risk:** ${Math.round(f.valueAtRisk).toLocaleString('en-US')}` : '',
      '',
      `[Open this problem](${resultsLink(ctx, `&finding=${encodeURIComponent(f.id)}`)})${f.fixUrl ? ` · [Fix it in Salesforce](${f.fixUrl})` : ''}`,
    ].filter(Boolean).join('\n'),
    suggestions: ['What should I fix first?', 'What changed since the last check?'],
  };
};

// ---------------------------------------------------------------------------
// Platform features: one entry per feature — the words people use, and the answer.
// ---------------------------------------------------------------------------

const FEATURES: { when: (string | RegExp)[]; text: string; suggestions?: string[] }[] = [
  {
    when: ['portfolio', 'all my clients', 'all clients', 'other clients', 'switch org', 'switch client', 'change org', 'another org', 'second org', 'multiple orgs', 'more than one org', 'add an org', 'add org', 'add client'],
    text: 'The [Client Portfolio](/portfolio) shows every Salesforce org you look after — health, trend, topic scores, top problems and schedules.\n- **Connect another org** adds a client (you sign in on Salesforce’s page).\n- **Switch & open** makes an org your active one; Your Data, new checks and results then show that org.\n- Each person has their own active org.',
    suggestions: ['How do I schedule automatic checks?', 'How do I add a team member?'],
  },
  {
    when: ['schedule', 'automatic check', 'automatically', 'every week', 'weekly check', 'monthly check', 'recurring', 'auto check'],
    text: 'To run checks automatically, open the [Client Portfolio](/portfolio) and click **Schedule automatic checks and alerts** on the client’s card. Choose daily, weekly or monthly. Each scheduled run checks all 21 areas and alerts you if things get worse.',
    suggestions: ['How do alerts work?'],
  },
  {
    when: ['alert', 'notify me', 'notification', 'bell', 'email alert', 'score drop'],
    text: 'Alerts appear under the **bell** at the top. You get one when a check finishes, when the score drops by your chosen number of points, or when new critical problems appear. In a client’s schedule you can also add an email address (email needs SMTP set up on the server). Choose which events notify you in [Settings → Notification Preferences](/settings?tab=notifications).',
  },
  {
    when: ['proposal', 'sow', 'statement of work', 'quote the client', 'estimate', 'how many hours', 'cost to fix', 'pricing for the fix'],
    text: 'Open [Reports → Proposal (SOW)](/reports). It turns open problems into a three-phase plan (Stabilise, Fix, Optimise) with estimated hours, cost at your rate, and a timeline. You can edit hours, leave items out, then print, save as PDF or download a spreadsheet. Set your default rate and currency in [Settings → Report Branding](/settings?tab=branding).',
  },
  {
    when: ['branding', 'white label', 'white-label', 'logo', 'our company name', 'accent colour', 'accent color', 'footer'],
    text: 'In [Settings → Report Branding](/settings?tab=branding) an admin can add your logo, company name, accent colour, “prepared by” and a footer, and hide “Prepared with Aquarient”. Every report and proposal uses it.',
  },
  {
    when: ['team', 'add a user', 'add user', 'add a person', 'invite', 'new user', 'team member', 'colleague', 'give access', 'remove access', 'deactivate', 'admin panel', 'approve', 'reject', 'access request', 'request access', 'more access', 'activity log', 'audit'],
    text: 'Admins use the [Admin Panel](/admin):\n- **People & permissions** — add people (they choose their own password at first sign-in), change roles and org access, reset passwords, unlock, sign out or deactivate.\n- **Access requests** — approve or reject requests for another client org or a different role.\n- **Activity log** — every sign-in and access change.\n\nNot an admin? Ask for more access in [Settings → Team & Access](/settings?tab=team).',
    suggestions: ['What can each role do?'],
  },
  {
    when: ['role', 'roles', 'permission', 'admin', 'consultant', 'viewer', 'read only user', 'what can i do'],
    text: 'There are three roles:\n- **Admin** — everything: all orgs, the team, Salesforce app keys, disconnecting orgs, report branding.\n- **Consultant** — connects orgs, runs checks, tracks fixes and schedules, for the orgs they’re given.\n- **Viewer** — read-only: results, reports and data for their orgs.',
  },
  {
    when: ['change my password', 'change password', 'new password', 'reset my password', 'forgot', 'locked out', 'locked'],
    text: 'To change your password, open [Settings → Profile Information](/settings?tab=profile) and use **Change password**. Forgot it, or locked out after 5 wrong tries? Ask an admin to reset or unlock it in the **Admin Panel** — the lock also clears by itself after 15 minutes.',
  },
  {
    when: ['sign out', 'log out', 'logout', 'signout'],
    text: 'Click your name at the top right and choose **Sign out**.',
  },
  {
    when: ['benchmark', 'compare with other', 'compare to other', 'how do we compare', 'percentile', 'industry average'],
    text: 'Benchmarks on the [Reports](/reports) dashboard compare an org with the latest check of your other client orgs. They appear once at least 3 other orgs have been checked, and no data leaves your workspace.',
  },
  {
    when: ['fix plan', 'step by step', 'steps to fix', 'how to fix', 'playbook'],
    text: 'Open any problem in [My Results](/results) and click **Get a step-by-step fix plan** — you’ll get the steps, a rough effort estimate and the risks to watch. “Fix it in Salesforce” opens the right setup page.',
  },
  {
    when: ['find a record', 'search records', 'search my data', 'find or ask', 'ask a question about', 'plain english', 'filter records'],
    text: 'At the top of [Your Data](/data) the **Find or ask** box finds any record by name, email or phone across all objects, or answers questions like “open deals over 50k closing this month” with the matching records. Press **/** to jump to it. You can ask me the same questions here.',
  },
  {
    when: ['related', 'related records', 'contacts of an account', 'account contacts'],
    text: 'In [Your Data](/data), click a record and open the **Related** tab to see its related lists — for an Account, its Contacts, Opportunities, Cases and more. Click a related record to open it on its own page.',
  },
  {
    when: ['export records', 'download records', 'affected records', 'which records', 'list of records', 'csv of'],
    text: 'Open a problem in [My Results](/results): **Affected records** lists the exact records with links into Salesforce, and **Download CSV** exports up to 10,000 of them.',
  },
  {
    when: ['what is new', 'what does new mean', 'worse mean', 'better mean', 'no change mean', 'change badge'],
    text: 'Each problem is compared with the previous check of the same org: **New** (wasn’t there before), **Worse** (more records), **Better** (fewer records) or **No change**. Problems that disappeared show under **Fixed since last check**.',
  },
  {
    when: ['disconnect', 'remove salesforce', 'remove the org', 'reconnect', 'expired', 'timed out', 'session expired'],
    text: 'If Salesforce shows as expired, open [Connect Salesforce](/connection) and click **Reconnect** — your past checks are kept. Admins can disconnect an org from the connection page or the [Client Portfolio](/portfolio). Disconnecting deletes everything saved about that org (its checks, problems, notes, schedule and alerts): nothing is kept once an org is disconnected. To only take an org off your own list, use **Remove from my list** instead.',
  },
];

const featureLookup: Handler = (q) => {
  let best: { f: (typeof FEATURES)[number]; n: number } | null = null;
  for (const f of FEATURES) {
    const n = f.when.filter((w) => (typeof w === 'string' ? q.includes(w) : w.test(q))).length;
    if (n && (!best || n > best.n)) best = { f, n };
  }
  return best ? { text: best.f.text, suggestions: best.f.suggestions } : null;
};

const HANDLERS: Handler[] = [
  greeting,
  thanks,
  browseData,
  dataCatalog,
  findingLookup,
  crmData,
  pageHelp,
  connectionStatus,
  changes,
  problemCounts,
  topicScores,
  myScore,
  fixFirst,
  featureLookup,
  scoreMeaning,
  urgencyMeaning,
  areaNumber,
  comingSoon,
  topicLookup,
  glossaryLookup,
  safety,
  howLong,
  howConnect,
  markFixed,
  reports,
  history,
  appSettings,
  tour,
  topicsList,
  howRun,
  getStarted,
  areaKeywords,
];

/** Follow-up questions that fit where the user is in the journey. */
function followUps(ctx: GuideContext): string[] {
  if (!connected(ctx)) return ['How do I connect Salesforce?', 'Is my data safe?', 'What do you check?', 'How does this work?'];
  if (!ctx.latest) return ['How do I run a health check?', ...DATA_SUGGESTIONS.slice(0, 2)];
  return ['What should I fix first?', 'What changed since the last check?', 'Which topic is weakest?', DATA_SUGGESTIONS[0]];
}

export function answer(question: string, ctx: GuideContext): GuideAnswer {
  const q = norm(question);
  if (!q) return { text: 'Ask me anything about the platform — for example “How do I connect Salesforce?”', suggestions: DEFAULT_SUGGESTIONS };
  for (const h of HANDLERS) {
    const a = h(q, ctx);
    // Always offer a few follow-ups, skipping the question just asked.
    if (a) return { ...a, suggestions: a.suggestions ?? followUps(ctx).filter((s) => norm(s) !== q).slice(0, 3) };
  }
  return {
    text: [
      'I’m not sure about that one. I can answer:',
      '- **The platform** — connecting, running checks, reports, proposals, schedules, team and roles.',
      '- **Your results** — scores by topic or area, problem counts, what changed, and any problem by name.',
      '- **Your Salesforce data** — counts, totals, “by owner/stage” breakdowns, and finding any record by name.',
      '',
      'You can also browse [Help & guide](/help).',
    ].join('\n'),
    suggestions: DEFAULT_SUGGESTIONS,
    fallback: true,
  };
}

export function welcomeMessage(ctx: GuideContext): GuideAnswer {
  return {
    text: `Hi, I’m **Aqua** 👋 — ask me anything about the platform, your health check results${
      connected(ctx) ? `, or the data in **${ctx.connection?.organizationName ?? 'your Salesforce'}**` : ''
    }, in your own words.\n\n${nextStep(ctx)}`,
    suggestions: connected(ctx) ? [DEFAULT_SUGGESTIONS[1], DATA_SUGGESTIONS[0], DATA_SUGGESTIONS[1], 'What changed since the last check?'] : DEFAULT_SUGGESTIONS,
  };
}

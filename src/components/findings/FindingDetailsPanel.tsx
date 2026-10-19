import { CircleDollarSign, ExternalLink, Flag, Lightbulb, Save, Target, TrendingDown, Users, Wrench } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRole, useUpdateFinding } from '@/api/queries';
import { getArea, getCategory } from '@/config/categories';
import { useToast } from '@/context/ToastContext';
import { fmtDateTime, fmtNumber } from '@/lib/format';
import type { Finding, FindingStatus } from '@/types';
import { FINDING_STATUS_LABEL, FindingStatusBadge, SeverityBadge } from '../ui/Badges';
import { Button } from '../ui/Button';
import { Field, Select } from '../ui/Form';
import { Drawer } from '../ui/Overlay';
import { InlineError } from '../ui/States';
import { AffectedRecords, ChangeBadge } from './AffectedRecords';
import { FixPlanPanel } from './FixPlanPanel';

const money = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

const PRIORITY_TEXT: Record<Finding['priority'], string> = {
  P1: 'Fix now',
  P2: 'Fix within a month',
  P3: 'Fix within 3 months',
  P4: 'Fix when you can',
};

function Section({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="mb-5">
      <h3 className="mb-1.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">
        {icon}
        {title}
      </h3>
      <div className="text-sm leading-relaxed text-ink">{children}</div>
    </section>
  );
}

export function FindingDetailsPanel({ finding, onClose }: { finding: Finding | null; onClose: () => void }) {
  const navigate = useNavigate();
  const { canEdit } = useRole();
  const { notify } = useToast();
  const update = useUpdateFinding(finding?.assessmentId ?? '');
  const [status, setStatus] = useState<FindingStatus>('open');
  const [notes, setNotes] = useState('');

  useEffect(() => {
    if (finding) {
      setStatus(finding.status);
      setNotes(finding.notes ?? '');
      update.reset();
    }
    // Reset the form only when a different finding is opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finding?.id]);

  const cat = finding ? getCategory(finding.categoryId) : undefined;
  const area = finding ? getArea(finding.areaId) : undefined;
  const dirty = !!finding && (status !== finding.status || notes !== (finding.notes ?? ''));

  const save = () => {
    if (!finding) return;
    update.mutate(
      { id: finding.id, body: { status, notes } },
      { onSuccess: () => notify('Saved', `${finding.id} is now ${FINDING_STATUS_LABEL[status]}.`, 'success') },
    );
  };

  return (
    <Drawer
      open={!!finding}
      onClose={onClose}
      title={finding?.name}
      subtitle={
        finding && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-ink-subtle">{finding.id}</span>
            <SeverityBadge severity={finding.severity} />
            <FindingStatusBadge status={finding.status} />
            <ChangeBadge finding={finding} />
          </div>
        )
      }
      footer={
        finding && (
          <Button
            onClick={() => {
              onClose();
              navigate(`/assessment/${finding.categoryId}/${finding.areaId}`);
            }}
          >
            Learn about this area
          </Button>
        )
      }
    >
      {finding && (
        <div>
          <div className="mb-5 grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-line bg-muted/60 p-3">
              <p className="flex items-center gap-1.5 text-xs text-ink-subtle">
                <Users className="h-3.5 w-3.5" /> Affected records
              </p>
              <p className="mt-1 text-xl font-semibold tabular-nums">{fmtNumber(finding.affectedRecords)}</p>
              {finding.previousAffected != null && (
                <p className="mt-0.5 text-[11px] text-ink-subtle">{fmtNumber(finding.previousAffected)} last check</p>
              )}
            </div>
            {finding.valueAtRisk ? (
              <div className="rounded-lg border border-line bg-muted/60 p-3">
                <p className="flex items-center gap-1.5 text-xs text-ink-subtle">
                  <CircleDollarSign className="h-3.5 w-3.5" /> Value at risk
                </p>
                <p className="mt-1 text-xl font-semibold tabular-nums">{money.format(finding.valueAtRisk)}</p>
                <p className="mt-0.5 text-[11px] text-ink-subtle">Total Amount involved</p>
              </div>
            ) : (
              <div className="rounded-lg border border-line bg-muted/60 p-3">
                <p className="flex items-center gap-1.5 text-xs text-ink-subtle">
                  <Flag className="h-3.5 w-3.5" /> Suggested priority
                </p>
                <p className="mt-1 text-xl font-semibold">{finding.priority}</p>
              </div>
            )}
          </div>

          <dl className="mb-5 space-y-1.5 rounded-lg border border-line p-3 text-sm">
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-ink-subtle">Topic</dt>
              <dd>{cat?.name ?? finding.categoryId}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-ink-subtle">Area</dt>
              <dd>{area ? `Area ${area.number}: ${area.name}` : finding.areaId}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-ink-subtle">Detected</dt>
              <dd>{fmtDateTime(finding.detectedAt)}</dd>
            </div>
          </dl>

          <Section icon={<Target className="h-3.5 w-3.5" />} title="What we found">
            {finding.description}
          </Section>
          {finding.recordsAvailable && <AffectedRecords finding={finding} />}
          <Section icon={<Lightbulb className="h-3.5 w-3.5" />} title="Why it matters">
            {finding.whyItMatters}
          </Section>
          <Section icon={<TrendingDown className="h-3.5 w-3.5" />} title="Business impact">
            {finding.businessImpact}
          </Section>
          <Section icon={<Flag className="h-3.5 w-3.5" />} title="How to fix it">
            <div className="rounded-lg border border-brand/20 bg-brand-soft p-3 text-brand-ink">{finding.recommendedAction}</div>
            {finding.fixUrl && (
              <a
                href={finding.fixUrl}
                target="_blank"
                rel="noreferrer noopener"
                className="mt-2 inline-flex h-9 items-center gap-2 rounded-lg bg-brand px-4 text-sm font-medium text-white shadow-sm transition hover:brightness-110"
              >
                <Wrench className="h-4 w-4" /> Fix it in Salesforce <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            <FixPlanPanel findingId={finding.id} />
          </Section>
          <Section icon={<Flag className="h-3.5 w-3.5" />} title="When to fix it">
            <span className="font-semibold">{finding.priority}</span> — {PRIORITY_TEXT[finding.priority]}
          </Section>

          {finding.sampleRecordsUrl && !finding.recordsAvailable && (
            <a
              href={finding.sampleRecordsUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="mb-5 inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:underline"
            >
              See the affected records in Salesforce <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}

          {canEdit && (
          <section className="rounded-xl border border-line p-4">
            <h3 className="mb-3 text-sm font-semibold">Track the fix</h3>
            <div className="space-y-3">
              <Field label="Where are you with this?">
                <Select<FindingStatus>
                  label="Problem progress"
                  value={status}
                  onChange={setStatus}
                  options={(Object.keys(FINDING_STATUS_LABEL) as FindingStatus[]).map((s) => ({ value: s, label: FINDING_STATUS_LABEL[s] }))}
                />
              </Field>
              <Field label="Notes" hint="Your team can see these notes.">
                <textarea
                  className="input h-24 resize-y py-2"
                  value={notes}
                  maxLength={2000}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="e.g. Priya is fixing this"
                />
              </Field>
              <InlineError error={update.error} />
              <Button variant="primary" icon={<Save className="h-4 w-4" />} disabled={!dirty || update.isPending} onClick={save}>
                {update.isPending ? 'Saving…' : 'Save changes'}
              </Button>
            </div>
          </section>
          )}
        </div>
      )}
    </Drawer>
  );
}

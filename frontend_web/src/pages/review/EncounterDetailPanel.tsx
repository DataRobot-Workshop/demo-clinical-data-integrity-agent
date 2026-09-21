import { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { useApproveCorrection, useEncounterDetail, useFlagEncounter } from '@/api/integrity/hooks';
import type { WriteBackResult } from '@/api/integrity/types';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { ConfidenceLabel, FlagReasonBadge, StatusBadge } from './status';
import { EncounterChatPanel } from './EncounterChatPanel';

function AuditReceipt({ result }: { result: WriteBackResult }) {
  const e = result.audit_log_entry;
  return (
    <Alert className="border-emerald-600/40 bg-emerald-50 dark:bg-emerald-950/30">
      <ShieldCheck className="h-4 w-4 text-emerald-600" />
      <AlertTitle className="text-emerald-700 dark:text-emerald-400">
        Written back to the system of record — audit entry created
      </AlertTitle>
      <AlertDescription>
        <p className="mb-2 text-sm">
          This is the governance record: exactly what was written, and who approved it. Backend:{' '}
          <span className="font-mono">{result.backend}</span>.
        </p>
        <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Encounter</dt>
          <dd className="font-mono">{e.encounter_id}</dd>
          <dt className="text-muted-foreground">Action</dt>
          <dd>{e.action}</dd>
          <dt className="text-muted-foreground">Approved code</dt>
          <dd className="font-mono">{e.approved_code}</dd>
          <dt className="text-muted-foreground">Actor</dt>
          <dd>{e.actor}</dd>
          <dt className="text-muted-foreground">Approved at</dt>
          <dd>{e.approved_at}</dd>
          <dt className="text-muted-foreground">New status</dt>
          <dd>{e.encounter_status}</dd>
          <dt className="text-muted-foreground">Detail</dt>
          <dd>{e.detail}</dd>
        </dl>
      </AlertDescription>
    </Alert>
  );
}

export function EncounterDetailPanel({
  encounterId,
  onResolved,
}: {
  encounterId: string | undefined;
  // Called after a decision is recorded so the list can advance to the next
  // flagged encounter. Returns true if it moved on to a different encounter.
  onResolved?: (resolvedId: string) => boolean;
}) {
  const { data, isLoading, isError, error } = useEncounterDetail(encounterId);
  const approve = useApproveCorrection();
  const flag = useFlagEncounter();

  const [approver, setApprover] = useState('');
  const [overrideCode, setOverrideCode] = useState('');
  const [flagReason, setFlagReason] = useState('');
  const [receipt, setReceipt] = useState<WriteBackResult | null>(null);

  // Reset the form + receipt whenever the selected encounter changes.
  useEffect(() => {
    setReceipt(null);
    setOverrideCode('');
    setFlagReason('');
  }, [encounterId]);

  if (!encounterId) {
    return (
      <div className="flex h-full min-h-64 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
        Select a flagged encounter on the left to review it.
      </div>
    );
  }

  // After a decision, the encounter leaves the flagged list, so a re-fetch of it
  // will 404. Keep showing the audit receipt instead of a scary error.
  if (receipt) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">Decision recorded</h2>
        </div>
        <AuditReceipt result={receipt} />
        <p className="text-sm text-muted-foreground">
          This encounter has left the flagged queue. Select the next one on the left to continue.
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Could not load encounter</AlertTitle>
        <AlertDescription>{(error as Error)?.message ?? 'Not found'}</AlertDescription>
      </Alert>
    );
  }

  const s = data.suggestion;
  const isSettled = ['corrected', 'needs_review'].includes((data.status ?? '').toLowerCase());

  const onApprove = (override: boolean) => {
    if (!encounterId) return;
    approve.mutate(
      {
        encounterId,
        payload: {
          approver: approver || undefined,
          override_code: override ? overrideCode || undefined : undefined,
        },
      },
      {
        onSuccess: r => {
          toast.success(
            override ? 'Override written back and logged' : 'Correction approved and logged'
          );
          // Advance to the next flagged encounter. If there is no next one, pin
          // the audit receipt so the user still sees what was written.
          const movedOn = encounterId ? onResolved?.(encounterId) : false;
          if (!movedOn) setReceipt(r);
        },
        onError: (err: unknown) => toast.error((err as Error)?.message ?? 'Write-back failed'),
      }
    );
  };

  const onFlag = () => {
    if (!encounterId) return;
    flag.mutate(
      {
        encounterId,
        payload: { approver: approver || undefined, reason: flagReason || undefined },
      },
      {
        onSuccess: r => {
          toast.success('Flagged for further review and logged');
          const movedOn = encounterId ? onResolved?.(encounterId) : false;
          if (!movedOn) setReceipt(r);
        },
        onError: (err: unknown) => toast.error((err as Error)?.message ?? 'Failed'),
      }
    );
  };

  const busy = approve.isPending || flag.isPending;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">Encounter {data.encounter_id}</h2>
        <StatusBadge status={data.status} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">On file today</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-1">
            <span className="text-muted-foreground">Patient</span>
            <span>{data.patient_id}</span>
            <span className="text-muted-foreground">Date</span>
            <span>{data.encounter_date}</span>
            <span className="text-muted-foreground">Diagnosis code</span>
            <span className="font-mono">{data.diagnosis_code}</span>
            <span className="text-muted-foreground">Description</span>
            <span>{data.diagnosis_description}</span>
            <span className="text-muted-foreground">Flag reason</span>
            <span>
              <FlagReasonBadge reason={data.flag_reason} />
            </span>
          </div>
          <Separator />
          <div>
            <div className="mb-1 text-muted-foreground">Clinical note excerpt</div>
            <blockquote className="border-l-2 pl-3 italic">{data.clinical_note_excerpt}</blockquote>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            <span>Agent recommendation</span>
            {s.action && (
              <Badge variant="secondary">
                {s.action === 'replace' ? 'Replace code' : 'Add secondary code'}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {s.match ? (
            <>
              <div className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-1">
                <span className="text-muted-foreground">Suggested code</span>
                <span className="font-mono font-semibold">{s.suggested_code}</span>
                <span className="text-muted-foreground">Description</span>
                <span>{s.suggested_description}</span>
                <span className="text-muted-foreground">Confidence</span>
                <span>
                  <ConfidenceLabel confidence={s.confidence} />
                </span>
              </div>
              <Separator />
              <div>
                <div className="mb-1 text-muted-foreground">Why the mismatch</div>
                <p>{s.rationale}</p>
              </div>
            </>
          ) : (
            <p className="text-muted-foreground">{s.rationale}</p>
          )}
          <p className="text-xs text-muted-foreground">{s.source}</p>
        </CardContent>
      </Card>

      {receipt ? (
        <AuditReceipt result={receipt} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Coder decision</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {isSettled && (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  This encounter is already <StatusBadge status={data.status} />. You can still
                  record another decision below.
                </AlertDescription>
              </Alert>
            )}
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label htmlFor="approver" className="mb-1 block text-sm text-muted-foreground">
                  Your name / ID (approver)
                </label>
                <Input
                  id="approver"
                  placeholder="e.g. j.rivera"
                  value={approver}
                  onChange={e => setApprover(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="override-code" className="mb-1 block text-sm text-muted-foreground">
                  Override code (optional)
                </label>
                <Input
                  id="override-code"
                  placeholder="Leave blank to accept the suggestion"
                  value={overrideCode}
                  onChange={e => setOverrideCode(e.target.value)}
                  className="font-mono"
                />
              </div>
            </div>
            <div>
              <label htmlFor="flag-reason" className="mb-1 block text-sm text-muted-foreground">
                Reason (for “flag for review”)
              </label>
              <Textarea
                id="flag-reason"
                placeholder="Why does this need further review?"
                value={flagReason}
                onChange={e => setFlagReason(e.target.value)}
                rows={2}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={busy || !s.match}
                onClick={() => onApprove(false)}
                title={!s.match ? 'No suggestion to approve — use override or flag' : undefined}
              >
                Approve suggestion
              </Button>
              <Button
                variant="secondary"
                disabled={busy || !overrideCode}
                onClick={() => onApprove(true)}
              >
                Override with manual code
              </Button>
              <Button variant="outline" disabled={busy} onClick={onFlag}>
                Flag for further review
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Nothing is written to the system of record until you choose one of these actions.
              Every action records an immutable audit entry.
            </p>
          </CardContent>
        </Card>
      )}

      {receipt && (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setReceipt(null)}>
            <CheckCircle2 className="mr-1 h-4 w-4" />
            Record another decision
          </Button>
        </div>
      )}

      <EncounterChatPanel encounterId={encounterId} />
    </div>
  );
}

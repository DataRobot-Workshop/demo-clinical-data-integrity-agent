import { Badge } from '@/components/ui/badge';

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = (status ?? '').toLowerCase();
  if (s === 'flagged') {
    return <Badge variant="destructive">Flagged</Badge>;
  }
  if (s === 'corrected') {
    return <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">Corrected</Badge>;
  }
  if (s === 'needs_review') {
    return <Badge variant="secondary">Needs review</Badge>;
  }
  return <Badge variant="outline">{status ?? 'unknown'}</Badge>;
}

export function FlagReasonBadge({ reason }: { reason: string | null | undefined }) {
  const r = (reason ?? '').toLowerCase();
  if (r === 'semantic_llm_mismatch') {
    return <Badge variant="outline">Semantic mismatch (LLM)</Badge>;
  }
  if (r === 'statistical_outlier') {
    return <Badge variant="outline">Statistical outlier</Badge>;
  }
  return reason ? <Badge variant="outline">{reason}</Badge> : null;
}

export function ConfidenceLabel({ confidence }: { confidence: number | null | undefined }) {
  if (confidence == null) {
    return <span className="text-muted-foreground">—</span>;
  }
  const pct = Math.round(confidence * 100);
  const tone = pct >= 85 ? 'text-emerald-600' : pct >= 60 ? 'text-amber-600' : 'text-red-600';
  return <span className={tone}>{pct}% confidence</span>;
}

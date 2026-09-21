import { AlertCircle } from 'lucide-react';
import { useAuditTrail } from '@/api/integrity/hooks';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

export function AuditTrailPage() {
  const { data, isLoading, isError, error } = useAuditTrail();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Audit Trail</h1>
        <p className="text-sm text-muted-foreground">
          Every approved correction and flag, with who approved it, when, and why. This is the
          governance record written back alongside each change.
        </p>
      </div>

      {isError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Could not load audit trail</AlertTitle>
          <AlertDescription>{(error as Error)?.message ?? 'Unknown error'}</AlertDescription>
        </Alert>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Created at</TableHead>
                <TableHead>Encounter</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.audit_log ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    No audit entries yet. Approve a correction to create one.
                  </TableCell>
                </TableRow>
              ) : (
                (data?.audit_log ?? []).map((entry, i) => (
                  <TableRow key={String(entry.id ?? i)}>
                    <TableCell className="whitespace-nowrap">{entry.created_at}</TableCell>
                    <TableCell className="font-mono">{entry.encounter_id}</TableCell>
                    <TableCell>{entry.action}</TableCell>
                    <TableCell>{entry.actor}</TableCell>
                    <TableCell className="max-w-md">{entry.detail}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

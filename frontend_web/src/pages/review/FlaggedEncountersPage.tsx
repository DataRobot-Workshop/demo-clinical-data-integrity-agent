import { useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AlertCircle } from 'lucide-react';
import { useFlaggedEncounters } from '@/api/integrity/hooks';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { EncounterDetailPanel } from './EncounterDetailPanel';
import { FlagReasonBadge, StatusBadge } from './status';

export function FlaggedEncountersPage() {
  const { data, isLoading, isError, error, refetch } = useFlaggedEncounters();
  const [searchParams, setSearchParams] = useSearchParams();

  const filter = searchParams.get('q') ?? '';
  const selectedId = searchParams.get('selected') ?? undefined;

  const setFilter = (q: string) => {
    const next = new URLSearchParams(searchParams);
    if (q) next.set('q', q);
    else next.delete('q');
    setSearchParams(next, { replace: true });
  };

  const selectEncounter = (encounterId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('selected', encounterId);
    setSearchParams(next, { replace: true });
  };

  // After a decision, advance to the next flagged encounter in the current list
  // order (skipping the one just resolved). Returns true if it moved to a
  // different encounter; false if that was the last one.
  const advanceFromResolved = (resolvedId: string): boolean => {
    const ids = (rows.map(r => r.encounter_id).filter(Boolean) as string[]).filter(
      id => id !== resolvedId
    );
    if (ids.length === 0) return false;
    const currentIndex = rows.findIndex(r => r.encounter_id === resolvedId);
    // Prefer the next row after the resolved one; wrap to the first remaining.
    const after = rows
      .slice(currentIndex + 1)
      .map(r => r.encounter_id)
      .filter(Boolean) as string[];
    const nextId = (after[0] ?? ids[0]) as string;
    const next = new URLSearchParams(searchParams);
    next.set('selected', nextId);
    setSearchParams(next, { replace: true });
    return true;
  };

  const rows = useMemo(() => {
    const list = data ?? [];
    const needle = filter.trim().toLowerCase();
    if (!needle) return list;
    return list.filter(e =>
      [
        e.encounter_id,
        e.patient_id,
        e.diagnosis_code,
        e.diagnosis_description,
        e.flag_reason,
        e.status,
      ]
        .filter(Boolean)
        .some(v => String(v).toLowerCase().includes(needle))
    );
  }, [data, filter]);

  // Keep the selection valid:
  // - if nothing is selected, select the first flagged encounter;
  // - if the selected encounter is no longer flagged (e.g. it was just approved
  //   and dropped out of the list), auto-advance to the next available one;
  // - if the list is now empty, clear the selection.
  useEffect(() => {
    if (isLoading) return;
    const ids = rows.map(r => r.encounter_id).filter(Boolean) as string[];
    const stillPresent = selectedId && ids.includes(selectedId);
    if (stillPresent) return;

    const next = new URLSearchParams(searchParams);
    if (ids.length > 0) {
      next.set('selected', ids[0]);
    } else {
      next.delete('selected');
    }
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, selectedId, isLoading]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Flagged Encounters</h1>
        <p className="text-sm text-muted-foreground">
          Encounters where Snowflake flagged the diagnosis code as not matching the clinical
          documentation. Select one to review the agent’s recommendation and act on it.
        </p>
      </div>

      {isError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Could not load flagged encounters</AlertTitle>
          <AlertDescription>
            {(error as Error)?.message ?? 'Unknown error'}
            <div className="mt-2">
              <Button size="sm" variant="outline" onClick={() => refetch()}>
                Retry
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
        {/* Left: encounter list */}
        <div className="flex flex-col gap-3">
          <Input placeholder="Filter…" value={filter} onChange={e => setFilter(e.target.value)} />
          <div className="rounded-md border">
            {isLoading ? (
              <div className="space-y-2 p-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : rows.length === 0 ? (
              <div className="p-4 text-center text-sm text-muted-foreground">
                No flagged encounters.
              </div>
            ) : (
              <ScrollArea className="h-[calc(100svh-16rem)]">
                <ul className="divide-y">
                  {rows.map(e => {
                    const isSelected = e.encounter_id === selectedId;
                    return (
                      <li key={e.encounter_id ?? Math.random()}>
                        <button
                          type="button"
                          onClick={() => e.encounter_id && selectEncounter(e.encounter_id)}
                          className={cn(
                            'w-full px-3 py-3 text-left transition-colors',
                            isSelected ? 'bg-muted' : 'hover:bg-muted/60'
                          )}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">{e.encounter_id}</span>
                            <StatusBadge status={e.status} />
                          </div>
                          <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                            <span className="font-mono">{e.diagnosis_code}</span>
                            <span>{e.patient_id}</span>
                          </div>
                          <div className="mt-1">
                            <FlagReasonBadge reason={e.flag_reason} />
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </ScrollArea>
            )}
          </div>
        </div>

        {/* Right: detail panel */}
        <div>
          <EncounterDetailPanel encounterId={selectedId} onResolved={advanceFromResolved} />
        </div>
      </div>
    </div>
  );
}

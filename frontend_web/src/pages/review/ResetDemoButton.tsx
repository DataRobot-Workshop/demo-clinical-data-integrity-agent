import { useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { useResetDemo } from '@/api/integrity/hooks';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

/**
 * Discreet demo reset. Restores the pristine baseline: all encounters back to
 * their original flagged/clean status, approvals cleared, audit trail emptied.
 * Deliberately low-key (muted icon in the header corner) and confirm-gated so it
 * isn't triggered by accident on stage.
 */
export function ResetDemoButton() {
  const [open, setOpen] = useState(false);
  const reset = useResetDemo();

  const onConfirm = () => {
    reset.mutate(undefined, {
      onSuccess: r => {
        toast.success(`Demo reset — ${r.flagged_encounters} flagged encounters restored.`);
        setOpen(false);
      },
      onError: (err: unknown) => toast.error((err as Error)?.message ?? 'Reset failed'),
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Reset demo"
          title="Reset demo"
          className="h-7 w-7 text-muted-foreground/40 hover:text-muted-foreground"
        >
          <RotateCcw className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset the demo?</DialogTitle>
          <DialogDescription>
            This restores the pristine demo state: all encounters return to their original
            flagged/clean status, every approval and override is cleared, and the audit trail is
            emptied. Use this between demo runs.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={reset.isPending}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={reset.isPending}>
            {reset.isPending ? 'Resetting…' : 'Reset demo'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

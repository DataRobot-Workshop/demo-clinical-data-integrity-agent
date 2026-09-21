import { Link, NavLink, Outlet } from 'react-router-dom';
import { ClipboardList, ShieldCheck } from 'lucide-react';
import { PATHS } from '@/constants/path';
import { cn } from '@/lib/utils';
import { Toaster } from '@/components/ui/sonner';
import { ResetDemoButton } from './ResetDemoButton';

function NavItem({
  to,
  icon,
  label,
  end,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
          isActive
            ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'
        )
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}

export function ReviewLayout() {
  return (
    <div className="flex h-svh w-full flex-col bg-background">
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-4">
          <Link to={PATHS.REVIEW.LIST} className="flex flex-col">
            <span className="text-lg font-semibold">Clinical Data Integrity</span>
            <span className="text-xs text-muted-foreground">
              Review flagged diagnosis codes · approve corrections · full audit trail
            </span>
          </Link>
          <nav className="flex items-center gap-2">
            <NavItem
              to={PATHS.REVIEW.LIST}
              end
              icon={<ClipboardList className="h-4 w-4" />}
              label="Flagged Encounters"
            />
            <NavItem
              to={PATHS.REVIEW.AUDIT}
              icon={<ShieldCheck className="h-4 w-4" />}
              label="Audit Trail"
            />
            <ResetDemoButton />
          </nav>
        </div>
      </header>
      <main className="flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-6xl px-6 py-6">
          <Outlet />
        </div>
      </main>
      <Toaster />
    </div>
  );
}

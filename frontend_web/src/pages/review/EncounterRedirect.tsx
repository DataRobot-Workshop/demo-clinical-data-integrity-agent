import { Navigate, useParams } from 'react-router-dom';
import { PATHS } from '@/constants/path';

// Backwards-compatible redirect: the old /review/encounters/:encounterId route
// now resolves into the master-detail list with that encounter selected.
export function EncounterRedirect() {
  const { encounterId } = useParams<{ encounterId: string }>();
  const to = encounterId
    ? `${PATHS.REVIEW.LIST}?selected=${encodeURIComponent(encounterId)}`
    : PATHS.REVIEW.LIST;
  return <Navigate to={to} replace />;
}

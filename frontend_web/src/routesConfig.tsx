import { PATHS } from '@/constants/path.ts';
import { lazy } from 'react';
import { Navigate } from 'react-router-dom';
import { SettingsLayout } from './pages/SettingsLayout';
import { ChatPage } from './pages/ChatPage';
import { EmptyStatePage } from './pages/EmptyState.tsx';
import { MainLayout } from './pages/MainLayoutWithChatList';
import { ReviewLayout } from './pages/review/ReviewLayout';
import { FlaggedEncountersPage } from './pages/review/FlaggedEncountersPage';
import { EncounterRedirect } from './pages/review/EncounterRedirect';
import { AuditTrailPage } from './pages/review/AuditTrailPage';

const OAuthCallback = lazy(() => import('./pages/OAuthCallback'));

export const appRoutes = [
  { path: PATHS.OAUTH_CB, element: <OAuthCallback /> },
  {
    element: <ReviewLayout />,
    children: [
      { path: PATHS.REVIEW.LIST, element: <FlaggedEncountersPage /> },
      { path: PATHS.REVIEW.DETAIL, element: <EncounterRedirect /> },
      { path: PATHS.REVIEW.AUDIT, element: <AuditTrailPage /> },
    ],
  },
  {
    element: <MainLayout />,
    children: [
      { path: PATHS.CHAT_EMPTY, element: <EmptyStatePage /> },
      { path: PATHS.CHAT, element: <ChatPage /> },
      {
        path: PATHS.SETTINGS.ROOT,
        element: <SettingsLayout />,
        children: [{ path: 'sources', element: <Navigate to={PATHS.SETTINGS.ROOT} replace /> }],
      },
      { path: '*', element: <Navigate to={PATHS.REVIEW.LIST} replace /> },
    ],
  },
];

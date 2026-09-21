export const PATHS = {
  CHAT_EMPTY: '/chat',
  CHAT: '/chat/:chatId',
  OAUTH_CB: '/oauth/callback',
  SETTINGS: {
    ROOT: '/settings',
  },
  REVIEW: {
    ROOT: '/review',
    LIST: '/review',
    DETAIL: '/review/encounters/:encounterId',
    AUDIT: '/review/audit',
  },
} as const;

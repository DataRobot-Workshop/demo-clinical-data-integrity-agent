export const integrityKeys = {
  all: ['integrity'] as const,
  encounters: ['integrity', 'encounters'] as const,
  encounter: (encounterId: string) => ['integrity', 'encounters', encounterId] as const,
  audit: ['integrity', 'audit'] as const,
};

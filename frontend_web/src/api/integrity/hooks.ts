import { useMutation, useQuery } from '@tanstack/react-query';
import { queryClient } from '../query-client';
import {
  approveCorrection,
  askAboutEncounter,
  flagEncounter,
  getAuditTrail,
  getEncounterDetail,
  getFlaggedEncounters,
  resetDemo,
} from './api-requests';
import { integrityKeys } from './keys';
import type { ApprovePayload, EncounterChatPayload, FlagPayload } from './types';

const staleTime = 30 * 1000;

export function useFlaggedEncounters() {
  return useQuery({
    queryKey: integrityKeys.encounters,
    queryFn: ({ signal }) => getFlaggedEncounters({ signal }),
    staleTime,
  });
}

export function useEncounterDetail(encounterId: string | undefined) {
  return useQuery({
    queryKey: integrityKeys.encounter(encounterId ?? ''),
    queryFn: ({ signal }) => getEncounterDetail({ encounterId: encounterId!, signal }),
    enabled: !!encounterId,
    staleTime,
  });
}

export function useAuditTrail() {
  return useQuery({
    queryKey: integrityKeys.audit,
    queryFn: ({ signal }) => getAuditTrail({ signal }),
    staleTime,
  });
}

function invalidateIntegrity() {
  queryClient.invalidateQueries({ queryKey: integrityKeys.encounters });
  queryClient.invalidateQueries({ queryKey: integrityKeys.audit });
}

export function useApproveCorrection() {
  return useMutation({
    mutationFn: ({ encounterId, payload }: { encounterId: string; payload: ApprovePayload }) =>
      approveCorrection({ encounterId, payload }),
    onSuccess: (_data, variables) => {
      invalidateIntegrity();
      queryClient.invalidateQueries({
        queryKey: integrityKeys.encounter(variables.encounterId),
      });
    },
  });
}

export function useFlagEncounter() {
  return useMutation({
    mutationFn: ({ encounterId, payload }: { encounterId: string; payload: FlagPayload }) =>
      flagEncounter({ encounterId, payload }),
    onSuccess: (_data, variables) => {
      invalidateIntegrity();
      queryClient.invalidateQueries({
        queryKey: integrityKeys.encounter(variables.encounterId),
      });
    },
  });
}

export function useAskAboutEncounter() {
  return useMutation({
    mutationFn: ({
      encounterId,
      payload,
    }: {
      encounterId: string;
      payload: EncounterChatPayload;
    }) => askAboutEncounter({ encounterId, payload }),
  });
}

export function useResetDemo() {
  return useMutation({
    mutationFn: () => resetDemo(),
    onSuccess: () => {
      invalidateIntegrity();
      queryClient.invalidateQueries({ queryKey: integrityKeys.all });
    },
  });
}

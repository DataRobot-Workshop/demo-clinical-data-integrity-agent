import apiClient from '@/api/apiClient';
import type {
  ApprovePayload,
  AuditTrailResponse,
  EncounterChatPayload,
  EncounterChatResponse,
  EncounterDetail,
  EncounterSummary,
  FlagPayload,
  WriteBackResult,
} from './types';

// apiClient.baseURL already includes `/api`, so paths start at `/v1`.

export async function getFlaggedEncounters({
  signal,
}: {
  signal?: AbortSignal;
} = {}): Promise<EncounterSummary[]> {
  const { data } = await apiClient.get<EncounterSummary[]>('/v1/integrity/encounters', {
    signal,
  });
  return data;
}

export async function getEncounterDetail({
  encounterId,
  signal,
}: {
  encounterId: string;
  signal?: AbortSignal;
}): Promise<EncounterDetail> {
  const { data } = await apiClient.get<EncounterDetail>(`/v1/integrity/encounters/${encounterId}`, {
    signal,
  });
  return data;
}

export async function approveCorrection({
  encounterId,
  payload,
}: {
  encounterId: string;
  payload: ApprovePayload;
}): Promise<WriteBackResult> {
  const { data } = await apiClient.post<WriteBackResult>(
    `/v1/integrity/encounters/${encounterId}/approve`,
    payload
  );
  return data;
}

export async function flagEncounter({
  encounterId,
  payload,
}: {
  encounterId: string;
  payload: FlagPayload;
}): Promise<WriteBackResult> {
  const { data } = await apiClient.post<WriteBackResult>(
    `/v1/integrity/encounters/${encounterId}/flag`,
    payload
  );
  return data;
}

export async function getAuditTrail({
  signal,
}: {
  signal?: AbortSignal;
} = {}): Promise<AuditTrailResponse> {
  const { data } = await apiClient.get<AuditTrailResponse>('/v1/integrity/audit', {
    signal,
  });
  return data;
}

export async function askAboutEncounter({
  encounterId,
  payload,
}: {
  encounterId: string;
  payload: EncounterChatPayload;
}): Promise<EncounterChatResponse> {
  const { data } = await apiClient.post<EncounterChatResponse>(
    `/v1/integrity/encounters/${encounterId}/chat`,
    payload
  );
  return data;
}

export async function resetDemo(): Promise<{
  status: string;
  backend: string;
  flagged_encounters: number;
}> {
  const { data } = await apiClient.post('/v1/integrity/reset');
  return data;
}

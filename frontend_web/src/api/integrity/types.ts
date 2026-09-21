export interface EncounterSummary {
  patient_id: string | null;
  encounter_id: string | null;
  encounter_date: string | null;
  diagnosis_code: string | null;
  diagnosis_description: string | null;
  clinical_note_excerpt: string | null;
  flag_reason: string | null;
  status: string | null;
}

export interface Suggestion {
  match: boolean;
  action: 'replace' | 'add_secondary' | null;
  suggested_code: string | null;
  suggested_description: string | null;
  rationale: string | null;
  confidence: number | null;
  source: string;
}

export interface EncounterDetail extends EncounterSummary {
  suggestion: Suggestion;
}

export interface AuditLogEntry {
  // audit_log system-of-record schema (lowercased by the backend):
  // id, encounter_id, action, actor, detail, created_at
  id?: number | string;
  encounter_id?: string;
  action?: string;
  actor?: string;
  detail?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface WriteBackAuditEntry {
  encounter_id?: string;
  action?: string;
  actor?: string;
  detail?: string;
  approved_code?: string;
  approved_at?: string;
  encounter_status?: string;
}

export interface WriteBackResult {
  status: string;
  backend: string;
  action?: string;
  audit_log_entry: WriteBackAuditEntry;
}

export interface AuditTrailResponse {
  audit_log: AuditLogEntry[];
  count: number;
}

export interface ApprovePayload {
  approver?: string;
  rationale?: string;
  override_code?: string;
}

export interface FlagPayload {
  approver?: string;
  reason?: string;
}

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface EncounterChatPayload {
  question: string;
  history: ChatTurn[];
}

export interface EncounterChatResponse {
  answer: string;
}

// Shapes returned by the OpsCore API (the fields the demo uses).

export type Severity = "info" | "low" | "medium" | "high" | "critical";

export interface Page<T> {
  items: T[];
  total: number;
}

export interface Site {
  id: string;
  code: string;
  name: string;
  kind: string | null;
}
export interface Asset {
  id: string;
  site_id: string | null;
  code: string;
  name: string;
  asset_type: string;
  criticality: number;
}
export interface Contact {
  id: string;
  name: string;
  role_label: string | null;
  email: string | null;
  phone: string | null;
  whatsapp: string | null;
  is_active: boolean;
}
export interface EventType {
  id: string;
  key: string;
  name: string;
  category: string;
}
export interface Rule {
  id: string;
  name: string;
  description: string | null;
  event_type_id: string | null;
  conditions: { field: string; op: string; value: unknown }[];
  match: "all" | "any";
  actions: { type: string; channels?: string[]; contact_roles?: string[]; title?: string; priority?: string; due_in_hours?: number }[];
  severity_override: Severity | null;
  is_active: boolean;
}
export interface OpsEvent {
  id: string;
  event_type_id: string;
  site_id: string | null;
  asset_id: string | null;
  severity: Severity;
  occurred_at: string;
  received_at: string;
  attributes: Record<string, unknown>;
  description: string | null;
  source_type: string;
}
export interface Alert {
  id: string;
  rule_id: string | null;
  first_event_id: string;
  site_id: string | null;
  asset_id: string | null;
  title: string;
  severity: Severity;
  status: "open" | "acknowledged" | "resolved";
  occurrence_count: number;
  first_seen_at: string;
  last_seen_at: string;
  acknowledged_at: string | null;
  acknowledged_by_user_id: string | null;
  resolved_at: string | null;
  resolved_by_user_id: string | null;
  resolution_note: string | null;
  created_at: string;
}
export interface Notification {
  id: string;
  alert_id: string | null;
  contact_id: string | null;
  channel: "email" | "sms" | "whatsapp";
  recipient: string | null;
  subject: string;
  status: string;
  sent_at: string | null;
  created_at: string;
}
export interface WorkOrder {
  id: string;
  alert_id: string | null;
  site_id: string | null;
  asset_id: string | null;
  title: string;
  priority: "low" | "normal" | "high" | "urgent";
  status: "open" | "in_progress" | "done" | "cancelled";
  due_at: string | null;
  completed_at: string | null;
  completion_note: string | null;
  created_at: string;
}
export interface AuditEntry {
  id: string;
  seq: number;
  created_at: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  changes: Record<string, unknown>;
  hash: string;
}
export interface AlertDetail extends Alert {
  events: OpsEvent[];
}
export interface Member {
  id: string;
  user_id: string;
  full_name: string;
  role: string;
}
export interface AuditVerify {
  valid: boolean;
  entries_checked: number;
  first_invalid_seq: number | null;
  reason: string | null;
}
export interface Conversation {
  id: string;
  channel: string;
  external_ref: string;
  display_name: string | null;
  locale: string | null;
  status: "bot" | "escalated" | "closed";
  escalation_reason: string | null;
  last_message_at: string;
  created_at: string;
}
export interface Message {
  id: string;
  created_at: string;
  direction: "inbound" | "outbound";
  author: "customer" | "bot" | "agent" | "system" | string;
  body: string;
  answered_by: string | null;
}
export interface ConversationDetail extends Conversation {
  messages: Message[];
}
export interface Organization {
  id: string;
  name: string;
  timezone: string;
  default_locale: string;
}

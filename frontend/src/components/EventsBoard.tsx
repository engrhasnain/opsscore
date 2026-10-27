"use client";
import Link from "next/link";
import { ShieldCheck, ShieldAlert, Wrench } from "lucide-react";
import { useState } from "react";
import { ops, usePoll, type Lookups } from "@/lib/api";
import type { ClientKey } from "@/lib/clients";
import type { Alert, AuditEntry, AuditVerify, Notification, OpsEvent, Page, WorkOrder } from "@/lib/types";
import { CHANNEL_LABEL, ChannelIcon, clock, roleLabel, SEV_COLOR, SeverityBadge, StatusPill, took, zoneName } from "./ui";

// OSHA framing for the US oil & gas demo (research: OSHA Oil and Gas Extraction hazards).
const OSHA: Record<string, string> = {
  flare_flashback: "Fire & explosion · OSHA hazard alert, Sept 2026",
  struck_by_hazard: "Struck-by / caught-in · leading on-site cause",
  vehicle_incident: "Highway vehicle · leading cause of death",
  gas_detection: "Hazardous atmosphere (H2S)",
  spill: "Environmental release",
};

// Action names as written by the OpsCore backend (app/services, app/assistant).
export const ACTION_LABEL: Record<string, string> = {
  "alert.raised": "Alert raised",
  "alert.escalated": "Alert escalated",
  "alert.acknowledged": "Alert acknowledged",
  "alert.resolved": "Alert resolved",
  "alert.reopened": "Alert reopened",
  "alert.no_recipients": "No one to notify (check contacts)",
  "work_order.created": "Work order opened",
  "work_order.status_changed": "Work order status changed",
  "work_order.updated": "Work order updated",
  "conversation.escalated": "Conversation handed to a person",
  "conversation.agent_replied": "Team replied",
  "conversation.handed_back": "Handed back to the assistant",
  "conversation.closed": "Conversation closed",
  "api_key.created": "Device key issued",
  "api_key.revoked": "Device key revoked",
  "organization.created": "Organization created",
  "organization.updated": "Organization updated",
  "organization.starter_pack_applied": "Starter pack applied",
  "org.settings": "Settings changed",
  "member.removed": "Member removed",
  "site.created": "Site added",
  "site.updated": "Site updated",
  "site.imported": "Sites imported",
  "asset.created": "Asset added",
  "asset.updated": "Asset updated",
  "asset.imported": "Assets imported",
  "contact.created": "Contact added",
  "contact.updated": "Contact updated",
  "event_type.created": "Event type added",
  "event_type.updated": "Event type updated",
  "rule.created": "Rule added",
  "rule.updated": "Rule updated",
  "knowledge.created": "Approved answer added",
  "knowledge.updated": "Approved answer updated",
  "knowledge.deleted": "Approved answer removed",
};

export const actorLabel = (t: string) => (t === "api_key" ? "Device" : t === "user" ? "Person" : t === "system" ? "OpsCore" : t);

type Data = {
  alerts: Page<Alert>;
  events: Page<OpsEvent>;
  notifications: Page<Notification>;
  workOrders: Page<WorkOrder>;
  audit: Page<AuditEntry>;
};

export function EventsBoard({ client, since, lookups, osha }: { client: ClientKey; since: string; lookups: Lookups | null; osha?: boolean }) {
  const s = encodeURIComponent(since);
  const { data, error } = usePoll<Data>(client, {
    alerts: `/alerts?since=${s}&limit=50`,
    events: `/events?since=${s}&limit=100`,
    notifications: "/notifications?limit=200",
    workOrders: "/work-orders?limit=100",
    audit: "/audit?limit=80",
  });
  const [verify, setVerify] = useState<AuditVerify | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const alerts = data.alerts?.items ?? [];
  const events = new Map((data.events?.items ?? []).map((e) => [e.id, e]));
  const after = <T extends { created_at: string }>(xs: T[] | undefined) => (xs ?? []).filter((x) => x.created_at >= since);
  const notes = after(data.notifications?.items);
  const wos = after(data.workOrders?.items);
  const audit = after(data.audit?.items);

  const site = (id: string | null) => (id && lookups?.sites.get(id)?.name) || "";
  const asset = (id: string | null) => (id && lookups?.assets.get(id)?.name) || "";
  const typeKey = (a: Alert) => {
    const ev = events.get(a.first_event_id);
    return ev ? lookups?.eventTypes.get(ev.event_type_id)?.key : undefined;
  };

  return (
    <div className="space-y-4">
      {error && <div className="panel border-sev-critical p-3 text-sm text-sev-critical">{error}</div>}

      <Panel title="Alerts" hint={`What happened, how serious, and where it stands. Site time (${zoneName()}).`} count={alerts.length}>
        {alerts.length === 0 ? (
          <Empty>Run the first step. Each event appears here the moment OpsCore receives it.</Empty>
        ) : (
          <ul className="divide-y divide-line">
            {alerts.map((a) => {
              const key = typeKey(a);
              const ev = events.get(a.first_event_id);
              const rule = a.rule_id ? lookups?.rules.get(a.rule_id) : undefined;
              return (
                <li key={a.id} className="arrive relative py-3 pl-4 pr-1">
                  <span className="absolute inset-y-3 left-0 w-1 rounded" style={{ background: SEV_COLOR[a.severity] }} />
                  <div className="flex flex-wrap items-center gap-2">
                    <SeverityBadge severity={a.severity} />
                    <span className="font-medium">{a.title}</span>
                    {a.occurrence_count > 1 && <span className="font-mono text-[11px] text-mute">×{a.occurrence_count}</span>}
                    <span className="ml-auto">
                      <StatusPill status={a.status} />
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[12px] text-mute">
                    <span>{[site(a.site_id), asset(a.asset_id)].filter(Boolean).join(" · ")}</span>
                    {rule && <span>Rule: {rule.name}</span>}
                    <span className="font-mono">{clock(a.first_seen_at)}</span>
                    {a.acknowledged_at && <span>Acknowledged after {took(a.first_seen_at, a.acknowledged_at)}</span>}
                    {a.resolved_at && <span>Resolved {clock(a.resolved_at)}</span>}
                  </div>
                  {ev?.description && <div className="mt-1 text-[12.5px]">{ev.description}</div>}
                  {osha && key && OSHA[key] && <div className="mt-1 text-[12px] text-mute">OSHA category: {OSHA[key]}</div>}
                  {a.resolution_note && <div className="mt-1.5 text-[12px] text-ok">Close-out: {a.resolution_note}</div>}
                  <Link href={`/record/${client}/${a.id}`} target="_blank" className="mt-1.5 inline-block text-[12px] text-mute underline decoration-line underline-offset-4 hover:text-ink">
                    Incident record
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Who was told" hint="Chosen by rule and role, not by whoever picks up" count={notes.length}>
          {notes.length === 0 ? (
            <Empty>Messages to people appear here.</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {notes.map((n) => {
                const c = n.contact_id ? lookups?.contacts.get(n.contact_id) : undefined;
                return (
                  <li key={n.id} className="arrive flex items-start gap-3 py-2.5">
                    <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-paper text-ink">
                      <ChannelIcon channel={n.channel} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px]">
                        <span className="font-medium">{c?.name ?? n.recipient}</span>
                        {c?.role_label && <span className="text-mute"> · {roleLabel(c.role_label)}</span>}
                      </div>
                      <div className="truncate text-[12px] text-mute">
                        {n.recipient ? `${CHANNEL_LABEL[n.channel]} to ${n.recipient}` : `${CHANNEL_LABEL[n.channel]}: no ${CHANNEL_LABEL[n.channel]} number on file`} · {n.subject}
                      </div>
                    </div>
                    <div className="text-right">
                      <StatusPill status={n.status} />
                      <div className="mt-0.5 font-mono text-[10.5px] text-faint">{n.sent_at ? clock(n.sent_at) : ""}</div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel title="Work orders" hint="Opened automatically, closed by a person" count={wos.length}>
          {wos.length === 0 ? (
            <Empty>Follow-up work appears here.</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {wos.map((w) => (
                <li key={w.id} className="arrive py-2.5">
                  <div className="flex items-start gap-2">
                    <Wrench size={14} className="mt-0.5 shrink-0 text-mute" />
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium leading-snug">{w.title}</div>
                      <div className="mt-0.5 text-[12px] text-mute">
                        <span className={w.priority === "urgent" ? "font-semibold text-sev-critical" : ""}>{w.priority}</span>
                        {w.due_at && <> · due {clock(w.due_at)}</>}
                      </div>
                      {w.completion_note && <div className="mt-1 text-[12px] text-ok">{w.completion_note}</div>}
                    </div>
                    <StatusPill status={w.status} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel
        title="The record"
        hint="Every step, who did it and when, chained by hash"
        count={audit.length}
        action={
          <button
            className="btn-line !py-1 text-xs"
            disabled={verifying}
            onClick={async () => {
              setVerifying(true);
              setVerifyError(null);
              try {
                setVerify(await ops<AuditVerify>(client, "/audit/verify"));
              } catch (e) {
                setVerifyError((e as Error).message);
              } finally {
                setVerifying(false);
              }
            }}
          >
            <ShieldCheck size={13} /> Check nothing was edited
          </button>
        }
      >
        {verifyError && <div className="mb-3 text-[13px] text-sev-critical">{verifyError}</div>}
        {verify && (
          <div className={`mb-3 flex items-center gap-2 rounded px-3 py-2 text-[13px] ${verify.valid ? "bg-[#ebfbee] text-ok" : "bg-[#fff5f5] text-sev-critical"}`}>
            {verify.valid ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}
            {verify.valid ? `Record intact: all ${verify.entries_checked} entries verified, nothing edited after the fact.` : `Chain broken at entry ${verify.first_invalid_seq}: ${verify.reason}`}
          </div>
        )}
        {audit.length === 0 ? (
          <Empty>The audit trail fills in as events are handled.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-[12.5px]">
              <thead>
                <tr className="text-left text-faint">
                  <th className="pb-1.5 pr-3 font-mono font-normal">#</th>
                  <th className="pb-1.5 pr-3 font-mono font-normal">Time</th>
                  <th className="pb-1.5 pr-3 font-mono font-normal">By</th>
                  <th className="pb-1.5 pr-3 font-mono font-normal">What</th>
                  <th className="pb-1.5 font-mono font-normal">Hash</th>
                </tr>
              </thead>
              <tbody>
                {audit.slice(0, 30).map((e) => (
                  <tr key={e.id} className="arrive border-t border-line">
                    <td className="py-1.5 pr-3 font-mono text-faint">{e.seq}</td>
                    <td className="py-1.5 pr-3 font-mono">{clock(e.created_at)}</td>
                    <td className="py-1.5 pr-3 text-mute">{actorLabel(e.actor_type)}</td>
                    <td className="py-1.5 pr-3">{ACTION_LABEL[e.action] ?? e.action}</td>
                    <td className="py-1.5 font-mono text-faint">{e.hash.slice(0, 12)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

export function Panel({ title, hint, count, action, children }: { title: string; hint?: string; count?: number; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5">
        <h2 className="text-sm font-semibold">{title}</h2>
        {count !== undefined && <span className="font-mono text-[11px] text-faint">{count}</span>}
        {hint && <span className="text-[12px] text-mute">{hint}</span>}
        {action && <span className="ml-auto">{action}</span>}
      </div>
      <div className="px-4 py-2">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-6 text-center text-[13px] text-faint">{children}</div>;
}

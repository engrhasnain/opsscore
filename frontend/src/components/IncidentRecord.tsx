"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, Printer, ShieldAlert, ShieldCheck } from "lucide-react";
import { ops, useLookups } from "@/lib/api";
import { CLIENTS, type ClientKey } from "@/lib/clients";
import type { AlertDetail, AuditEntry, AuditVerify, Member, Notification, Page, WorkOrder } from "@/lib/types";
import { ACTION_LABEL } from "./EventsBoard";
import { CHANNEL_LABEL, fullTime, roleLabel, SeverityBadge, StatusPill, took, TopBar, useDisplayZone, zoneName } from "./ui";

interface RecordData {
  alert: AlertDetail;
  notifications: Notification[];
  workOrders: WorkOrder[];
  audit: AuditEntry[];
  members: Map<string, Member>;
  verify: AuditVerify;
  printedAt: string;
}

/** One incident on one page: what happened, who was told, what was done, and proof the record is intact. */
export function IncidentRecord({ client, alertId }: { client: ClientKey; alertId: string }) {
  const c = CLIENTS[client];
  useDisplayZone(c.timeZone);
  const lookups = useLookups(client);
  const [data, setData] = useState<RecordData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const alert = await ops<AlertDetail>(client, `/alerts/${alertId}`);
      const [notes, wos, members, alertAudit] = await Promise.all([
        ops<Page<Notification>>(client, `/notifications?alert_id=${alertId}&limit=200`),
        ops<Page<WorkOrder>>(client, `/work-orders?alert_id=${alertId}&limit=50`),
        ops<Page<Member>>(client, "/members?limit=200"),
        ops<Page<AuditEntry>>(client, `/audit?entity_type=alert&entity_id=${alertId}&limit=200`),
      ]);
      const woAudit = await Promise.all(wos.items.map((w) => ops<Page<AuditEntry>>(client, `/audit?entity_type=work_order&entity_id=${w.id}&limit=200`)));
      const verify = await ops<AuditVerify>(client, "/audit/verify");
      if (!alive) return;
      setData({
        alert,
        notifications: [...notes.items].sort((a, b) => a.created_at.localeCompare(b.created_at)),
        workOrders: wos.items,
        audit: [...alertAudit.items, ...woAudit.flatMap((p) => p.items)].sort((a, b) => a.seq - b.seq),
        members: new Map(members.items.map((m) => [m.user_id, m])),
        verify,
        printedAt: new Date().toISOString(),
      });
    })().catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [client, alertId]);

  const person = (userId: string | null | undefined) => (userId && data?.members.get(userId)?.full_name) || "a signed-in user";
  const actor = (e: AuditEntry) => (e.actor_type === "user" ? person(e.actor_id) : e.actor_type === "api_key" ? "Device" : "OpsCore");

  if (error) return <Shell client={client}>{<p className="text-[14px] text-sev-critical">{error}</p>}</Shell>;
  if (!data) return <Shell client={client}>{<p className="text-[14px] text-mute">Loading the record…</p>}</Shell>;
  const { alert } = data;
  const site = alert.site_id ? lookups?.sites.get(alert.site_id) : undefined;
  const asset = alert.asset_id ? lookups?.assets.get(alert.asset_id) : undefined;
  const rule = alert.rule_id ? lookups?.rules.get(alert.rule_id) : undefined;

  return (
    <Shell client={client}>
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-ink pb-4">
        <div>
          <div className="text-[12px] text-mute">
            Incident record · {c.name} · reference {alert.id.slice(0, 8)}
          </div>
          <h1 className="mt-1 text-[22px] font-semibold leading-snug">{alert.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[13px]">
            <SeverityBadge severity={alert.severity} />
            <StatusPill status={alert.status} />
            {site && <span className="text-mute">{site.name}</span>}
            {asset && <span className="text-mute">{asset.name}</span>}
          </div>
        </div>
        <button onClick={() => window.print()} className="btn-line print:hidden">
          <Printer size={14} /> Print or save as PDF
        </button>
      </header>

      <Section title="Summary">
        <dl className="grid gap-x-8 gap-y-2 text-[13.5px] sm:grid-cols-[180px_1fr]">
          <Row label="Rule">{rule?.name ?? "–"}</Row>
          <Row label="First reported">{fullTime(alert.first_seen_at)}</Row>
          {alert.occurrence_count > 1 && (
            <Row label="Reported again">
              {alert.occurrence_count - 1} more time{alert.occurrence_count > 2 ? "s" : ""}, last at {fullTime(alert.last_seen_at)}
            </Row>
          )}
          <Row label="Acknowledged">
            {alert.acknowledged_at ? `${fullTime(alert.acknowledged_at)} by ${person(alert.acknowledged_by_user_id)}, ${took(alert.first_seen_at, alert.acknowledged_at)} after the first report` : "Not yet"}
          </Row>
          <Row label="Resolved">{alert.resolved_at ? `${fullTime(alert.resolved_at)} by ${person(alert.resolved_by_user_id)}` : "Not yet"}</Row>
          {alert.resolution_note && <Row label="Close-out">{alert.resolution_note}</Row>}
        </dl>
      </Section>

      <Section title={`What was reported (${alert.events.length})`}>
        <Table head={["Time", "Reported by", "What", "Details"]}>
          {alert.events.map((e) => (
            <tr key={e.id} className="border-b border-line align-top">
              <Td mono>{fullTime(e.occurred_at)}</Td>
              <Td>{e.source_type === "api_key" ? "Device" : e.source_type === "user" ? "Person" : "OpsCore assistant"}</Td>
              <Td>
                <div className="font-medium">{lookups?.eventTypes.get(e.event_type_id)?.name ?? "Event"}</div>
                {e.description && <div className="text-mute">{e.description}</div>}
              </Td>
              <Td>
                {Object.entries(e.attributes)
                  .filter(([k]) => !["conversation_id", "excerpt"].includes(k))
                  .map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v)}`)
                  .join("; ")}
              </Td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title={`Who was told (${data.notifications.length})`}>
        {data.notifications.length === 0 ? (
          <p className="text-[13.5px] text-mute">Nobody: this rule does not notify anyone.</p>
        ) : (
          <Table head={["Queued", "Person", "Channel", "Message", "Delivery"]}>
            {data.notifications.map((n) => {
              const ct = n.contact_id ? lookups?.contacts.get(n.contact_id) : undefined;
              return (
                <tr key={n.id} className="border-b border-line align-top">
                  <Td mono>{fullTime(n.created_at)}</Td>
                  <Td>
                    <div className="font-medium">{ct?.name ?? "–"}</div>
                    <div className="text-mute">{roleLabel(ct?.role_label)}</div>
                  </Td>
                  <Td>
                    {CHANNEL_LABEL[n.channel]}
                    <div className="text-mute">{n.recipient ?? "no address on file"}</div>
                  </Td>
                  <Td>{n.subject}</Td>
                  <Td>
                    <StatusPill status={n.status} />
                    {n.sent_at && <div className="text-mute">{fullTime(n.sent_at)}</div>}
                  </Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Section>

      <Section title={`Work orders (${data.workOrders.length})`}>
        {data.workOrders.length === 0 ? (
          <p className="text-[13.5px] text-mute">None opened for this incident.</p>
        ) : (
          <Table head={["Work order", "Priority", "Due", "Status", "Completion"]}>
            {data.workOrders.map((w) => (
              <tr key={w.id} className="border-b border-line align-top">
                <Td>
                  <span className="font-medium">{w.title}</span>
                </Td>
                <Td>{w.priority}</Td>
                <Td mono>{w.due_at ? fullTime(w.due_at) : "–"}</Td>
                <Td>
                  <StatusPill status={w.status} />
                </Td>
                <Td>
                  {w.completed_at && <div className="font-mono text-[12.5px]">{fullTime(w.completed_at)}</div>}
                  {w.completion_note}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Section>

      <Section title={`Timeline (${data.audit.length} entries)`}>
        <Table head={["#", "Time", "By", "Action", "Details", "Hash"]}>
          {data.audit.map((e) => (
            <tr key={e.id} className="border-b border-line align-top">
              <Td mono>{e.seq}</Td>
              <Td mono>{fullTime(e.created_at)}</Td>
              <Td>{actor(e)}</Td>
              <Td>{ACTION_LABEL[e.action] ?? e.action}</Td>
              <Td>
                {Object.entries(e.changes ?? {})
                  .filter(([k, v]) => !k.endsWith("_id") && v !== null && v !== "")
                  .map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                  .join("; ")}
              </Td>
              <Td mono>{e.hash.slice(0, 12)}</Td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="Integrity">
        <div className={`flex items-start gap-2 text-[13.5px] ${data.verify.valid ? "text-ok" : "text-sev-critical"}`}>
          {data.verify.valid ? <ShieldCheck size={16} className="mt-0.5 shrink-0" /> : <ShieldAlert size={16} className="mt-0.5 shrink-0" />}
          <p>
            {data.verify.valid
              ? `Every entry in ${c.name}'s audit trail (${data.verify.entries_checked} entries) was checked when this record was produced. Each entry carries the hash of the one before it, so changing or deleting any past entry would break the chain.`
              : `The audit chain is broken at entry ${data.verify.first_invalid_seq}: ${data.verify.reason}`}
          </p>
        </div>
        <p className="mt-3 text-[12px] text-mute">
          Produced {fullTime(data.printedAt)}. Times are {c.place} time ({zoneName()}).
        </p>
      </Section>
    </Shell>
  );
}

function Shell({ client, children }: { client: ClientKey; children: React.ReactNode }) {
  return (
    <>
      <div className="print:hidden">
        <TopBar />
      </div>
      <main className="mx-auto max-w-[1100px] bg-panel px-8 py-7 print:max-w-none print:px-0 print:py-0">
        <Link href={`/console/${client}`} className="mb-4 inline-flex items-center gap-1 text-[12px] text-mute hover:text-ink print:hidden">
          <ArrowLeft size={13} /> Back to the console
        </Link>
        {children}
      </main>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 break-inside-avoid">
      <h2 className="mb-2 text-[14px] font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-mute">{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-[13px]">
        <thead>
          <tr className="border-b border-ink text-left text-[12px] text-mute">
            {head.map((h) => (
              <th key={h} className="py-1.5 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Td({ children, mono }: { children: React.ReactNode; mono?: boolean }) {
  return <td className={`py-2 pr-4 ${mono ? "whitespace-nowrap font-mono text-[12.5px]" : ""}`}>{children}</td>;
}

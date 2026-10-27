"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Bot, ShieldAlert, ShieldCheck, UserRound } from "lucide-react";
import { ops, useLookups, usePoll, type Lookups } from "@/lib/api";
import { CLIENT_KEYS, CLIENTS, type ClientKey } from "@/lib/clients";
import type { Alert, AuditEntry, AuditVerify, Conversation, ConversationDetail, Page, WorkOrder } from "@/lib/types";
import { ACTION_LABEL, actorLabel, Empty } from "./EventsBoard";
import { clock, roleLabel, SEV_COLOR, SeverityBadge, stamp, StatusPill, TopBar, useDisplayZone, zoneName } from "./ui";

type Tab = "alerts" | "work" | "conversations" | "audit" | "setup";
const SHORT: Record<ClientKey, string> = { permian: "Permian", andes: "Andes", bayou: "Bayou", atlantico: "Atlântico" };
const OP: Record<string, string> = { eq: "=", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤", in: "in", contains: "contains" };

const TABS: [Tab, string][] = [
  ["alerts", "Alerts"],
  ["work", "Work orders"],
  ["conversations", "Conversations"],
  ["audit", "Audit trail"],
  ["setup", "Setup"],
];

export function Console({ client }: { client: ClientKey }) {
  const [tab, setTab] = useState<Tab>("alerts");
  const lookups = useLookups(client);
  const c = CLIENTS[client];
  useDisplayZone(c.timeZone);
  return (
    <>
      <TopBar />
      <div className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-end gap-x-6 gap-y-3 px-5 pt-4">
          <div className="pb-3">
            <div className="eyebrow">
              {c.marketLabel} · operations console · times in {c.place} time ({zoneName()})
            </div>
            <h1 className="text-xl font-semibold">{c.name}</h1>
          </div>
          <div className="ml-auto flex flex-wrap gap-1 pb-3">
            {CLIENT_KEYS.map((k) => (
              <Link key={k} href={`/console/${k}`} className={`rounded px-2.5 py-1 text-xs ${k === client ? "bg-ink text-white" : "border border-line text-mute hover:border-ink"}`}>
                {SHORT[k]}
              </Link>
            ))}
          </div>
          <nav className="flex w-full gap-5 text-sm" role="tablist" aria-label="Console sections">
            {TABS.map(([t, label]) => (
              <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`-mb-px border-b-2 pb-2.5 ${tab === t ? "border-signal font-semibold text-ink" : "border-transparent text-mute hover:text-ink"}`}>
                {label}
              </button>
            ))}
          </nav>
        </div>
      </div>
      <main className="mx-auto max-w-[1400px] px-5 py-6">
        {tab === "alerts" && <AlertsTab client={client} lookups={lookups} />}
        {tab === "work" && <WorkTab client={client} lookups={lookups} />}
        {tab === "conversations" && <ConversationsTab client={client} />}
        {tab === "audit" && <AuditTab client={client} />}
        {tab === "setup" && <SetupTab client={client} lookups={lookups} />}
      </main>
    </>
  );
}

function isAssistantAlert(a: Alert, lookups: Lookups | null) {
  const rule = a.rule_id ? lookups?.rules.get(a.rule_id) : undefined;
  const type = rule?.event_type_id ? lookups?.eventTypes.get(rule.event_type_id) : undefined;
  return !!type?.key.startsWith("assistant");
}

function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async (id: string, fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(id);
    setError(null);
    try {
      await fn();
      after?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return { busy, error, run };
}

function AlertsTab({ client, lookups }: { client: ClientKey; lookups: Lookups | null }) {
  const [status, setStatus] = useState<"" | "open" | "acknowledged" | "resolved">("");
  const { data, refresh } = usePoll<{ alerts: Page<Alert> }>(client, { alerts: `/alerts?limit=100${status ? `&status=${status}` : ""}` }, 3000);
  const { busy, error, run } = useAction();
  const alerts = data.alerts?.items ?? [];
  return (
    <section className="panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
        <h2 className="text-sm font-semibold">Alerts</h2>
        <span className="font-mono text-[11px] text-faint">{data.alerts?.total ?? 0}</span>
        <div className="ml-auto flex gap-1">
          {(["", "open", "acknowledged", "resolved"] as const).map((s) => (
            <button key={s || "all"} onClick={() => setStatus(s)} className={`rounded px-2 py-0.5 text-xs ${status === s ? "bg-ink text-white" : "text-mute hover:text-ink"}`}>
              {s || "All"}
            </button>
          ))}
        </div>
      </div>
      {error && <div className="px-4 py-2 text-sm text-sev-critical">{error}</div>}
      {alerts.length === 0 ? (
        <Empty>No alerts. Run a scenario or send an event to see them here.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-[13px]">
            <thead>
              <tr className="border-b border-line text-left text-[11.5px] text-mute">
                <th className="px-4 py-2 font-medium">Severity</th>
                <th className="py-2 pr-3 font-medium">Alert</th>
                <th className="py-2 pr-3 font-medium">Where</th>
                <th className="py-2 pr-3 font-medium">Seen</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-4 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id} className="border-b border-line align-top" style={{ boxShadow: `inset 3px 0 0 ${SEV_COLOR[a.severity]}` }}>
                  <td className="px-4 py-2.5">
                    <SeverityBadge severity={a.severity} />
                  </td>
                  <td className="py-2.5 pr-3">
                    <div className="font-medium">{a.title}</div>
                    {a.rule_id && <div className="text-[12px] text-mute">Rule: {lookups?.rules.get(a.rule_id)?.name}</div>}
                    {a.resolution_note && <div className="text-[12px] text-ok">{a.resolution_note}</div>}
                  </td>
                  <td className="py-2.5 pr-3 text-mute">{[a.site_id && lookups?.sites.get(a.site_id)?.name, a.asset_id && lookups?.assets.get(a.asset_id)?.name].filter(Boolean).join(" · ") || (isAssistantAlert(a, lookups) ? "Driver conversation" : "–")}</td>
                  <td className="py-2.5 pr-3 font-mono text-[12px] text-mute">
                    {stamp(a.first_seen_at)}
                    {a.occurrence_count > 1 && <div>×{a.occurrence_count}, last {stamp(a.last_seen_at)}</div>}
                  </td>
                  <td className="py-2.5 pr-3">
                    <StatusPill status={a.status} />
                  </td>
                  <td className="py-2.5 pr-4 text-right">
                    <div className="inline-flex items-center gap-1">
                      <Link href={`/record/${client}/${a.id}`} target="_blank" className="mr-2 text-[12px] text-mute underline decoration-line underline-offset-4 hover:text-ink">
                        Record
                      </Link>
                      {a.status === "open" && (
                        <button className="btn-line !py-1 text-xs" disabled={!!busy} onClick={() => run(a.id, () => ops(client, `/alerts/${a.id}/acknowledge`, { method: "POST" }), refresh)}>
                          Acknowledge
                        </button>
                      )}
                      {a.status !== "resolved" && (
                        <button className="btn-dark !py-1 text-xs" disabled={!!busy} onClick={() => run(a.id, () => ops(client, `/alerts/${a.id}/resolve`, { method: "POST", body: { note: "Resolved from the console." } }), refresh)}>
                          Resolve
                        </button>
                      )}
                      {a.status === "resolved" && (
                        <button className="btn-line !py-1 text-xs" disabled={!!busy} onClick={() => run(a.id, () => ops(client, `/alerts/${a.id}/reopen`, { method: "POST" }), refresh)}>
                          Reopen
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function WorkTab({ client, lookups }: { client: ClientKey; lookups: Lookups | null }) {
  const { data, refresh } = usePoll<{ work: Page<WorkOrder> }>(client, { work: "/work-orders?limit=100" }, 3000);
  const { busy, error, run } = useAction();
  const items = data.work?.items ?? [];
  const move = (w: WorkOrder, status: WorkOrder["status"]) => run(w.id, () => ops(client, `/work-orders/${w.id}/transition`, { method: "POST", body: { status, note: status === "done" ? "Completed from the console." : undefined } }), refresh);
  return (
    <section className="panel">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <h2 className="text-sm font-semibold">Work orders</h2>
        <span className="font-mono text-[11px] text-faint">{data.work?.total ?? 0}</span>
      </div>
      {error && <div className="px-4 py-2 text-sm text-sev-critical">{error}</div>}
      {items.length === 0 ? (
        <Empty>Rules open work orders automatically when something needs doing.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((w) => (
            <li key={w.id} className="flex flex-wrap items-start gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">{w.title}</div>
                <div className="text-[12px] text-mute">
                  <span className={w.priority === "urgent" ? "font-semibold text-sev-critical" : ""}>{w.priority}</span>
                  {w.site_id && <> · {lookups?.sites.get(w.site_id)?.name}</>}
                  {w.due_at && <> · due {stamp(w.due_at)}</>}
                </div>
                {w.completion_note && <div className="text-[12px] text-ok">{w.completion_note}</div>}
              </div>
              <StatusPill status={w.status} />
              <div className="flex gap-1">
                {w.status === "open" && (
                  <button className="btn-line !py-1 text-xs" disabled={!!busy} onClick={() => move(w, "in_progress")}>
                    Start
                  </button>
                )}
                {(w.status === "open" || w.status === "in_progress") && (
                  <>
                    <button className="btn-dark !py-1 text-xs" disabled={!!busy} onClick={() => move(w, "done")}>
                      Done
                    </button>
                    <button className="btn-line !py-1 text-xs" disabled={!!busy} onClick={() => window.confirm(`Cancel "${w.title}"? It stays on the record as cancelled.`) && move(w, "cancelled")}>
                      Cancel
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ConversationsTab({ client }: { client: ClientKey }) {
  const { data, refresh } = usePoll<{ convs: Page<Conversation> }>(client, { convs: "/assistant/conversations?limit=100" }, 2500);
  const convs = data.convs?.items ?? [];
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [text, setText] = useState("");
  const { busy, error, run } = useAction();
  const selected = convs.find((c) => c.id === openId);

  const [loadError, setLoadError] = useState<string | null>(null);
  useEffect(() => {
    if (!openId) return;
    let alive = true;
    // Clear the old thread straight away, so a reply can never go to the previous person.
    setDetail(null);
    setLoadError(null);
    const load = () =>
      ops<ConversationDetail>(client, `/assistant/conversations/${openId}`)
        .then((d) => alive && d.id === openId && (setDetail(d), setLoadError(null)))
        .catch((e: Error) => alive && setLoadError(e.message));
    load();
    const t = setInterval(load, 2500);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [client, openId, selected?.last_message_at]);

  const after = () => {
    refresh();
    if (openId) ops<ConversationDetail>(client, `/assistant/conversations/${openId}`).then(setDetail);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
      <section className="panel max-h-[75vh] overflow-y-auto">
        <div className="sticky top-0 border-b border-line bg-panel px-4 py-2.5 text-sm font-semibold">Conversations</div>
        {convs.length === 0 ? (
          <Empty>Messages from drivers and truckers appear here.</Empty>
        ) : (
          <ul className="divide-y divide-line">
            {convs.map((c) => (
              <li key={c.id}>
                <button onClick={() => setOpenId(c.id)} className={`w-full px-4 py-2.5 text-left ${openId === c.id ? "bg-paper" : "hover:bg-paper/60"}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] font-medium">{c.display_name ?? c.external_ref}</span>
                    <StatusPill status={c.status} />
                  </div>
                  <div className="font-mono text-[11px] text-faint">
                    {c.channel} · {c.locale?.toUpperCase()} · {stamp(c.last_message_at)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel flex min-h-[420px] flex-col">
        {!selected || !detail || detail.id !== openId ? (
          <Empty>{!openId ? "Pick a conversation to read it and reply as a person." : (loadError ?? "Loading the conversation…")}</Empty>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
              <span className="text-sm font-semibold">{detail.display_name ?? detail.external_ref}</span>
              <span className="font-mono text-[11px] text-faint">{detail.external_ref}</span>
              <StatusPill status={detail.status} />
              <div className="ml-auto flex gap-1">
                {detail.status === "escalated" && (
                  <button className="btn-line !py-1 text-xs" disabled={!!busy} onClick={() => run("hb", () => ops(client, `/assistant/conversations/${detail.id}/hand-back`, { method: "POST" }), after)}>
                    Hand back to assistant
                  </button>
                )}
                {detail.status !== "closed" && (
                  <button className="btn-line !py-1 text-xs" disabled={!!busy} onClick={() => run("cl", () => ops(client, `/assistant/conversations/${detail.id}/close`, { method: "POST" }), after)}>
                    Close
                  </button>
                )}
              </div>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto px-4 py-3">
              {detail.messages.map((m) => {
                const mine = m.direction === "outbound";
                return (
                  <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[75%] rounded-lg px-3 py-2 text-[13.5px] ${mine ? (m.author === "agent" ? "bg-[#d3f9d8]" : "bg-[#e7f5ff]") : "bg-paper"}`}>
                      <div className="mb-0.5 flex items-center gap-1 font-mono text-[10px] uppercase tracking-wide text-mute">
                        {mine ? m.author === "agent" ? <UserRound size={10} /> : <Bot size={10} /> : null}
                        {mine ? (m.author === "agent" ? "Team" : `Assistant${m.answered_by ? ` · ${m.answered_by}` : ""}`) : "Sender"} · {clock(m.created_at)}
                      </div>
                      {m.body}
                    </div>
                  </div>
                );
              })}
            </div>
            {error && <div className="px-4 text-sm text-sev-critical">{error}</div>}
            <form
              className="flex gap-2 border-t border-line p-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (!text.trim()) return;
                run("reply", () => ops(client, `/assistant/conversations/${detail.id}/reply`, { method: "POST", body: { body: text } }), () => {
                  setText("");
                  after();
                });
              }}
            >
              <input aria-label="Reply as a person" value={text} onChange={(e) => setText(e.target.value)} placeholder="Reply as a person (the assistant stays quiet)…" className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 text-sm outline-none focus:border-ink" />
              <button className="btn-dark" disabled={!!busy || !text.trim()}>
                Send
              </button>
            </form>
          </>
        )}
      </section>
    </div>
  );
}

function AuditTab({ client }: { client: ClientKey }) {
  const { data } = usePoll<{ audit: Page<AuditEntry> }>(client, { audit: "/audit?limit=200" }, 5000);
  const [verify, setVerify] = useState<AuditVerify | null>(null);
  const { busy, error, run } = useAction();
  const items = data.audit?.items ?? [];
  return (
    <section className="panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
        <h2 className="text-sm font-semibold">Audit trail</h2>
        <span className="font-mono text-[11px] text-faint">{data.audit?.total ?? 0} entries</span>
        <button className="btn-dark ml-auto !py-1 text-xs" disabled={!!busy} onClick={() => run("verify", async () => setVerify(await ops<AuditVerify>(client, "/audit/verify")))}>
          <ShieldCheck size={13} /> Verify the whole chain
        </button>
      </div>
      {error && <div className="mx-4 mt-3 text-sm text-sev-critical">{error}</div>}
      {verify && (
        <div className={`mx-4 mt-3 flex items-center gap-2 rounded px-3 py-2 text-[13px] ${verify.valid ? "bg-[#ebfbee] text-ok" : "bg-[#fff5f5] text-sev-critical"}`}>
          {verify.valid ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}
          {verify.valid ? `Intact: ${verify.entries_checked} entries verified. Any edit to a past entry would break the chain.` : `Broken at entry ${verify.first_invalid_seq}: ${verify.reason}`}
        </div>
      )}
      <div className="overflow-x-auto px-4 py-2">
        <table className="w-full min-w-[820px] text-[12.5px]">
          <thead>
            <tr className="text-left text-faint">
              <th className="py-1.5 pr-3 font-mono font-normal">#</th>
              <th className="py-1.5 pr-3 font-mono font-normal">When</th>
              <th className="py-1.5 pr-3 font-mono font-normal">By</th>
              <th className="py-1.5 pr-3 font-mono font-normal">Action</th>
              <th className="py-1.5 pr-3 font-mono font-normal">Details</th>
              <th className="py-1.5 font-mono font-normal">Hash</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id} className="border-t border-line align-top">
                <td className="py-1.5 pr-3 font-mono text-faint">{e.seq}</td>
                <td className="py-1.5 pr-3 font-mono">{stamp(e.created_at)}</td>
                <td className="py-1.5 pr-3 text-mute">{actorLabel(e.actor_type)}</td>
                <td className="py-1.5 pr-3">{ACTION_LABEL[e.action] ?? e.action}</td>
                <td className="max-w-[360px] truncate py-1.5 pr-3 text-mute" title={JSON.stringify(e.changes)}>
                  {Object.entries(e.changes ?? {})
                    .filter(([k, v]) => !k.endsWith("_id") && v !== null && v !== "")
                    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
                    .join(" · ")}
                </td>
                <td className="py-1.5 font-mono text-faint">{e.hash.slice(0, 10)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

interface Knowledge {
  id: string;
  title: string;
  content: string;
  locale: string;
  site_id: string | null;
}

function SetupTab({ client, lookups }: { client: ClientKey; lookups: Lookups | null }) {
  const { data } = usePoll<{ answers: Page<Knowledge> }>(client, { answers: "/assistant/knowledge?limit=100" }, 10000);
  const answers = data.answers?.items ?? [];
  if (!lookups) return <Empty>Loading setup…</Empty>;
  const sites = [...lookups.sites.values()];
  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-[13px] text-mute">Everything here is configured per client without code: sites and assets (form or CSV), contacts and their roles, event types, rules, and the approved answers the assistant is allowed to send.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <SetupCard title="Sites and assets" count={sites.length}>
          {sites.map((s) => (
            <div key={s.id} className="py-2">
              <div className="text-[13px]">
                <span className="font-mono text-[11.5px] text-mute">{s.code}</span> {s.name}
              </div>
              <div className="text-[12px] text-mute">
                {[...lookups.assets.values()]
                  .filter((a) => a.site_id === s.id)
                  .map((a) => `${a.name} (criticality ${a.criticality})`)
                  .join(" · ") || "No assets"}
              </div>
            </div>
          ))}
        </SetupCard>
        <SetupCard title="People and roles" count={lookups.contacts.size}>
          {[...lookups.contacts.values()].map((c) => (
            <div key={c.id} className="flex justify-between gap-3 py-2 text-[13px]">
              <span className="font-medium">
                {c.name}
                {!c.is_active && <span className="ml-2 text-[11px] font-normal text-mute">(inactive)</span>}
              </span>
              <span className="text-mute">{roleLabel(c.role_label)}</span>
            </div>
          ))}
        </SetupCard>
        <SetupCard title="Rules" count={lookups.rules.size}>
          {[...lookups.rules.values()].map((r) => {
            const et = r.event_type_id ? lookups.eventTypes.get(r.event_type_id) : undefined;
            const notify = r.actions.filter((a) => a.type === "notify").flatMap((a) => a.contact_roles ?? []);
            const wo = r.actions.find((a) => a.type === "create_work_order");
            return (
              <div key={r.id} className="py-2 text-[13px]">
                <div className="font-medium">
                  {r.name}
                  {!r.is_active && <span className="ml-2 text-[11px] font-normal text-mute">(switched off)</span>}
                </div>
                <div className="text-[12px] text-mute">
                  When <span className="font-mono">{et?.key ?? "any event"}</span>
                  {r.conditions.length > 0 && (r.match === "any" ? " and any of: " : " and ")}
                  {r.conditions.map((c) => `${c.field.replace("attributes.", "")} ${OP[c.op] ?? c.op} ${Array.isArray(c.value) ? c.value.join("/") : String(c.value ?? "")}`).join(r.match === "any" ? ", " : " and ")}
                  {notify.length > 0 && ` → tell ${notify.map(roleLabel).join(", ")}`}
                  {wo && ` → ${wo.priority} work order`}
                  {r.severity_override && ` · ${r.severity_override}`}
                </div>
              </div>
            );
          })}
        </SetupCard>
        <SetupCard title="Approved assistant answers" count={answers.length}>
          {answers.map((a) => (
            <div key={a.id} className="py-2 text-[13px]">
              <div className="flex items-center gap-2">
                <span className="rounded bg-paper px-1 font-mono text-[10px] uppercase text-mute">{a.locale}</span>
                <span className="font-medium">{a.title}</span>
                {a.site_id && <span className="text-[11.5px] text-faint">{lookups.sites.get(a.site_id)?.code}</span>}
              </div>
              <div className="text-[12px] text-mute">{a.content}</div>
            </div>
          ))}
        </SetupCard>
      </div>
    </div>
  );
}

function SetupCard({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="font-mono text-[11px] text-faint">{count}</span>
      </div>
      <div className="max-h-[420px] divide-y divide-line overflow-y-auto px-4 py-1">{children}</div>
    </section>
  );
}

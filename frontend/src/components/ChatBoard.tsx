"use client";
import { useEffect, useRef, useState } from "react";
import { Bot, UserRound } from "lucide-react";
import { ops, usePoll, type Lookups } from "@/lib/api";
import type { ClientKey } from "@/lib/clients";
import type { Alert, Conversation, ConversationDetail, Notification, Page } from "@/lib/types";
import { Empty, Panel } from "./EventsBoard";
import { CHANNEL_LABEL, ChannelIcon, clock, roleLabel, SeverityBadge, StatusPill } from "./ui";

const REASON: Record<string, string> = {
  emergency: "Danger reported",
  human_requested: "Asked for a person",
  no_answer: "No approved answer",
};

type Data = { conversations: Page<Conversation>; alerts: Page<Alert>; notifications: Page<Notification> };

export function ChatBoard({ client, since, lookups }: { client: ClientKey; since: string; lookups: Lookups | null }) {
  const s = encodeURIComponent(since);
  const { data, error, tick } = usePoll<Data>(client, {
    conversations: "/assistant/conversations?limit=100",
    alerts: `/alerts?since=${s}&limit=50`,
    notifications: "/notifications?limit=200",
  });
  const convs = (data.conversations?.items ?? []).filter((c) => c.created_at >= since).sort((a, b) => a.created_at.localeCompare(b.created_at));
  const alerts = data.alerts?.items ?? [];
  const notes = (data.notifications?.items ?? []).filter((n) => n.created_at >= since);

  // Fetch each conversation's messages when it changes.
  const [details, setDetails] = useState<Record<string, ConversationDetail>>({});
  const seen = useRef<Record<string, string>>({});
  const convKey = convs.map((c) => c.id + c.last_message_at + c.status).join("|");
  useEffect(() => {
    const stale = convs.filter((c) => seen.current[c.id] !== c.last_message_at + c.status);
    if (!stale.length) return;
    stale.forEach((c) => (seen.current[c.id] = c.last_message_at + c.status));
    for (const c of stale) {
      ops<ConversationDetail>(client, `/assistant/conversations/${c.id}`)
        // Keep whichever copy is newest, so a slow older reply can't overwrite a newer one.
        .then((x) => setDetails((d) => (d[x.id] && d[x.id].messages.length > x.messages.length ? d : { ...d, [x.id]: x })))
        .catch(() => delete seen.current[c.id]); // fetched again on the next poll
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- convKey captures every change in convs; tick retries failed fetches
  }, [convKey, client, tick]);

  const escalated = convs.filter((c) => c.status === "escalated" || c.escalation_reason);
  const answered = convs.length - escalated.length;
  const times = convs
    .map((c) => {
      const m = details[c.id]?.messages ?? [];
      const q = m.find((x) => x.direction === "inbound");
      const r = m.find((x) => x.direction === "outbound");
      return q && r ? new Date(r.created_at).getTime() - new Date(q.created_at).getTime() : null;
    })
    .filter((x): x is number => x !== null)
    .sort((a, b) => a - b);
  const median = times.length ? times[Math.floor(times.length / 2)] : null;
  const compact = convs.length > 6;

  return (
    <div className="space-y-4">
      {error && <div className="panel border-sev-critical p-3 text-sm text-sev-critical">{error}</div>}

      <div className="panel grid grid-cols-2 divide-line sm:grid-cols-4 sm:divide-x">
        <Stat label="Conversations" value={convs.length} />
        <Stat label="Answered by the assistant" value={answered} tone="ok" />
        <Stat label="Handed to a person" value={escalated.length} tone="signal" />
        <Stat label="Median reply time" value={median === null ? "–" : median < 1000 ? `${median} ms` : `${(median / 1000).toFixed(1)} s`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel title="Messages coming in" hint="WhatsApp / SMS to the site's number" count={convs.length}>
          {convs.length === 0 ? (
            <Empty>Run a step to send the first message.</Empty>
          ) : (
            <div className={compact ? "grid gap-2 py-1 sm:grid-cols-2 2xl:grid-cols-3" : "space-y-3 py-1"}>
              {convs.map((c) => (
                <ConversationCard key={c.id} conv={c} detail={details[c.id]} compact={compact} />
              ))}
            </div>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Waiting for a person" count={escalated.length}>
            {escalated.length === 0 ? (
              <Empty>Nothing yet. Only exceptions land here.</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {escalated.map((c) => (
                  <li key={c.id} className="arrive py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium">{c.display_name ?? c.external_ref}</span>
                      <StatusPill status={c.status} />
                    </div>
                    <div className={`text-[12px] ${c.escalation_reason === "emergency" ? "font-semibold text-sev-critical" : "text-mute"}`}>{REASON[c.escalation_reason ?? ""] ?? c.escalation_reason}</div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Who was told" count={notes.length}>
            {notes.length === 0 ? (
              <Empty>On-call and supervisors are messaged here.</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {notes.map((n) => {
                  const ct = n.contact_id ? lookups?.contacts.get(n.contact_id) : undefined;
                  return (
                    <li key={n.id} className="arrive flex items-start gap-2 py-2">
                      <ChannelIcon channel={n.channel} />
                      <div className="min-w-0 text-[12.5px]">
                        <div>
                          <span className="font-medium">{ct?.name ?? n.recipient}</span>
                          {ct?.role_label && <span className="text-mute"> · {roleLabel(ct.role_label)}</span>}
                        </div>
                        <div className="truncate text-mute">
                          {CHANNEL_LABEL[n.channel]} · {n.subject}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          {alerts.length > 0 && (
            <Panel title="Site alerts" count={alerts.length}>
              <ul className="divide-y divide-line">
                {alerts.map((a) => (
                  <li key={a.id} className="arrive py-2">
                    <div className="flex items-center gap-2">
                      <SeverityBadge severity={a.severity} />
                      <span className="truncate text-[12.5px] font-medium">{a.title}</span>
                    </div>
                    <div className="font-mono text-[10.5px] text-faint">{clock(a.first_seen_at)}</div>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function ConversationCard({ conv, detail, compact }: { conv: Conversation; detail?: ConversationDetail; compact: boolean }) {
  const messages = detail?.messages ?? [];
  // In the busy grid show the question and answer; for a conversation with a person, the latest turns.
  const shown = compact ? (conv.status === "escalated" ? [messages[0], ...messages.slice(-2)].filter((m, i, all) => m && all.indexOf(m) === i) : messages.slice(0, 2)) : messages;
  const tone = conv.escalation_reason === "emergency" ? "border-sev-critical" : conv.status === "escalated" ? "border-signal" : "border-line";
  return (
    <div className={`arrive rounded border bg-paper/40 p-2.5 ${tone}`}>
      <div className="mb-1.5 flex items-center gap-2 text-[12px]">
        <ChannelIcon channel={conv.channel} size={12} />
        <span className="truncate font-medium">{conv.display_name ?? conv.external_ref}</span>
        {conv.locale && <span className="rounded bg-panel px-1 font-mono text-[10px] uppercase text-mute">{conv.locale}</span>}
        <span className="ml-auto">
          <StatusPill status={conv.status} />
        </span>
      </div>
      <div className="space-y-1">
        {shown.length === 0 && <div className="text-[12px] text-faint">…</div>}
        {shown.map((m) => {
          const mine = m.direction === "outbound";
          return (
            <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[88%] rounded-lg px-2.5 py-1.5 ${compact ? "text-[11.5px]" : "text-[13px]"} leading-snug ${mine ? (m.author === "agent" ? "bg-[#d3f9d8]" : "bg-[#e7f5ff]") : "bg-panel"}`}>
                {mine && (
                  <div className="mb-0.5 flex items-center gap-1 font-mono text-[9.5px] uppercase tracking-wide text-mute">
                    {m.author === "agent" ? <UserRound size={10} /> : <Bot size={10} />}
                    {m.author === "agent" ? "Team" : "Assistant"}
                  </div>
                )}
                {m.body}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: "ok" | "signal" }) {
  return (
    <div className="px-4 py-3">
      <div className="text-[11.5px] text-mute">{label}</div>
      <div className={`font-mono text-2xl font-semibold ${tone === "ok" ? "text-ok" : tone === "signal" ? "text-signal" : ""}`}>{value}</div>
    </div>
  );
}

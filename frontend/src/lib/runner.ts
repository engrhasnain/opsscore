"use client";
import { ops } from "./api";
import type { ClientKey } from "./clients";
import type { Action } from "./scenarios";
import type { Alert, AuditVerify, Conversation, Page, WorkOrder } from "./types";

export interface ActionResult {
  ok: boolean;
  text: string;
  /** Messages handed to a person by this action. */
  escalated?: number;
}

interface IngestResult {
  created: boolean;
  alerts: { outcome: string; severity: string; notifications: number; work_order_id: string | null }[];
}
interface InboundResult {
  status: string;
  escalated: boolean;
  reply: string | null;
  locale: string | null;
}

// Each demo session gets its own sender numbers, so earlier runs never interfere.
export function senderFor(base: string, run: number) {
  return base.slice(0, -4) + String((Number(base.slice(-4)) + run) % 10000).padStart(4, "0");
}

/**
 * Resolve alerts left open by earlier demo runs. OpsCore merges repeat events into an open
 * alert without messaging anyone again, so a fresh run needs a clean board to show who is told.
 * Returns the time the run should start from.
 */
export async function clearStage(client: ClientKey): Promise<string> {
  // Start from the server's clock, not the laptop's, so a skewed presenter clock can't
  // hide this run's records or show older ones.
  let start = (await serverNow()) - 2000;
  const open = (await ops<Page<Alert>>(client, "/alerts?status=open&status=acknowledged&limit=100")).items;
  for (const al of open) {
    const done = await ops<Alert>(client, `/alerts/${al.id}/resolve`, { method: "POST", body: { note: "Closed when the scenario was reset." } });
    // Its audit entry is written just after resolved_at; leave a margin so it stays out of this run.
    if (done.resolved_at) start = Math.max(start, new Date(done.resolved_at).getTime() + 1500);
  }
  // Don't let the run begin inside that margin.
  if (open.length) await new Promise((r) => setTimeout(r, 1700));
  return new Date(start).toISOString();
}

async function serverNow(): Promise<number> {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    const body = (await res.json()) as { now?: string };
    if (body.now) return new Date(body.now).getTime();
  } catch {
    // fall back to the browser clock
  }
  return Date.now();
}

/** Run one scenario action against OpsCore. `since` scopes acknowledge/resolve/complete to this run. */
export async function runAction(client: ClientKey, a: Action, since: string, run: number): Promise<ActionResult> {
  switch (a.type) {
    case "event": {
      const r = await ops<IngestResult>(client, "/events", { method: "POST", body: a.body });
      if (!r.alerts.length) return { ok: true, text: "Recorded. No rule matched, so nobody was disturbed." };
      return {
        ok: true,
        text: r.alerts
          .map((x) =>
            x.outcome === "merged"
              ? `Merged into the open ${x.severity} alert (no duplicate messages).`
              : `${cap(x.severity)} alert · ${x.notifications} message${x.notifications === 1 ? "" : "s"} sent${x.work_order_id ? " · work order opened" : ""}`,
          )
          .join(" "),
      };
    }
    case "message": {
      const r = await ops<InboundResult>(client, "/assistant/inbound", {
        method: "POST",
        body: { channel: a.channel ?? "whatsapp", sender: senderFor(a.sender, run), display_name: a.name, body: a.body },
      });
      return { ok: true, text: r.escalated ? "Handed to a person · on-call alerted" : "Answered by the assistant", escalated: r.escalated ? 1 : 0 };
    }
    case "flood": {
      let answered = 0;
      let escalated = 0;
      // A few at a time: a hosted API with its own database per server (see backend
      // app/bundled_db.py) should not be pushed into starting a second server mid-scenario.
      const queue = [...a.messages];
      const send = async () => {
        for (let m = queue.shift(); m; m = queue.shift()) {
          const r = await ops<InboundResult>(client, "/assistant/inbound", {
            method: "POST",
            body: { channel: "whatsapp", sender: senderFor(m.sender, run), display_name: m.name, body: m.body },
          });
          if (!r.escalated && r.reply) answered++;
          if (r.escalated) escalated++;
        }
      };
      await Promise.all([send(), send(), send(), send()]);
      return { ok: true, text: `${answered} of ${a.messages.length} answered by the assistant`, escalated };
    }
    case "ack":
    case "resolve": {
      const alerts = (await ops<Page<Alert>>(client, `/alerts?since=${encodeURIComponent(since)}&limit=100`)).items;
      let n = 0;
      for (const al of alerts) {
        if (a.type === "ack" && al.status === "open") {
          await ops(client, `/alerts/${al.id}/acknowledge`, { method: "POST" });
          n++;
        }
        if (a.type === "resolve" && al.status !== "resolved") {
          await ops(client, `/alerts/${al.id}/resolve`, { method: "POST", body: { note: a.note } });
          n++;
        }
      }
      return { ok: true, text: `${n} alert${n === 1 ? "" : "s"} ${a.type === "ack" ? "acknowledged" : "resolved"}` };
    }
    case "completeWork": {
      const wos = (await ops<Page<WorkOrder>>(client, "/work-orders?limit=100")).items.filter(
        (w) => w.created_at >= since && w.status !== "done" && w.status !== "cancelled" && (!a.titleIncludes || w.title.includes(a.titleIncludes)),
      );
      for (const w of wos) await ops(client, `/work-orders/${w.id}/transition`, { method: "POST", body: { status: "done", note: a.note } });
      if (wos.length) return { ok: true, text: `${wos.length} work order${wos.length === 1 ? "" : "s"} completed` };
      const done = (await ops<Page<WorkOrder>>(client, "/work-orders?status=done&limit=100")).items.some(
        (w) => w.created_at >= since && (!a.titleIncludes || w.title.includes(a.titleIncludes)),
      );
      return done ? { ok: true, text: "Already completed in this run" } : { ok: false, text: "No open work orders from this run yet. Run the earlier steps first." };
    }
    case "replyEscalated": {
      const convs = (await ops<Page<Conversation>>(client, "/assistant/conversations?status=escalated&limit=100")).items.filter((c) => c.created_at >= since);
      // Only ever reply to the named person; never fall back to someone else's chat.
      const target = convs.find((c) => (c.display_name ?? "").includes(a.to));
      if (!target) return { ok: false, text: `${a.to} is not waiting for a person in this run. Run the earlier steps first.` };
      await ops(client, `/assistant/conversations/${target.id}/reply`, { method: "POST", body: { body: a.body } });
      return { ok: true, text: `Replied to ${target.display_name ?? target.external_ref}` };
    }
    case "verify": {
      const v = await ops<AuditVerify>(client, "/audit/verify");
      return v.valid
        ? { ok: true, text: `Record intact: ${v.entries_checked} entries checked, none edited` }
        : { ok: false, text: `Chain broken at entry ${v.first_invalid_seq}: ${v.reason}` };
    }
  }
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

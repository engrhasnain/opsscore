"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Mail, MessageCircle, Smartphone } from "lucide-react";
import type { Severity } from "@/lib/types";

export const SEV_COLOR: Record<Severity, string> = {
  critical: "var(--color-sev-critical)",
  high: "var(--color-sev-high)",
  medium: "var(--color-sev-medium)",
  low: "var(--color-sev-low)",
  info: "var(--color-sev-info)",
};

const SEV_LABEL: Record<Severity, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low", info: "Info" };

export function SeverityBadge({ severity }: { severity: Severity }) {
  const c = SEV_COLOR[severity];
  return (
    <span className="inline-block min-w-[58px] rounded-sm px-1.5 py-px text-center text-[11px] font-semibold text-white" style={{ background: c }}>
      {SEV_LABEL[severity]}
    </span>
  );
}

const STATUS: Record<string, [string, string]> = {
  open: ["Open", "var(--color-sev-critical)"],
  acknowledged: ["Acknowledged", "var(--color-sev-medium)"],
  resolved: ["Resolved", "var(--color-ok)"],
  in_progress: ["In progress", "var(--color-sev-medium)"],
  done: ["Done", "var(--color-ok)"],
  cancelled: ["Cancelled", "var(--color-faint)"],
  bot: ["Assistant", "var(--color-sev-low)"],
  escalated: ["With a person", "var(--color-signal)"],
  closed: ["Closed", "var(--color-faint)"],
  sent: ["Sent", "var(--color-ok)"],
  pending: ["Queued", "var(--color-sev-medium)"],
  failed: ["Failed", "var(--color-sev-critical)"],
  skipped: ["Not sent: no address", "var(--color-mute)"],
};

export function StatusPill({ status }: { status: string }) {
  const [label, c] = STATUS[status] ?? [status, "var(--color-mute)"];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] text-ink">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: c }} aria-hidden />
      {label}
    </span>
  );
}

export function ChannelIcon({ channel, size = 13 }: { channel: string; size?: number }) {
  if (channel === "email") return <Mail size={size} />;
  if (channel === "whatsapp") return <MessageCircle size={size} />;
  return <Smartphone size={size} />;
}

export const CHANNEL_LABEL: Record<string, string> = { email: "Email", sms: "SMS", whatsapp: "WhatsApp" };

// Times are shown in the demo client's own time zone (a Texas pad at Texas time), not
// the presenter's laptop zone. Each page shows one client, so the page sets it once.
let displayZone: string | undefined;

/** Call at the top of a page component, before its children render. */
export function useDisplayZone(zone: string) {
  displayZone = zone;
}

export function clock(iso: string) {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: displayZone });
}

/** Time only for today; month, day and time for anything older. */
export function stamp(iso: string) {
  const d = new Date(iso);
  const day = (x: Date) => x.toLocaleDateString("en-US", { timeZone: displayZone });
  if (day(d) === day(new Date())) return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: displayZone });
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: displayZone });
}

/** Full date and time with the zone, for records that leave the screen. */
export function fullTime(iso: string) {
  return new Date(iso).toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: displayZone, timeZoneName: "short" });
}

/** Short zone name for labels, e.g. "CDT" or "GMT-3". */
export function zoneName() {
  return new Intl.DateTimeFormat("en-US", { timeZone: displayZone, timeZoneName: "short" }).formatToParts(new Date()).find((p) => p.type === "timeZoneName")?.value ?? "";
}

export function roleLabel(role: string | null | undefined) {
  if (!role) return "";
  return role.replace(/_/g, " ");
}

/** A short "1.2 s" style duration between two timestamps. */
export function took(fromIso: string, toIso: string) {
  const ms = Math.max(0, new Date(toIso).getTime() - new Date(fromIso).getTime());
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function TopBar({ right }: { right?: React.ReactNode }) {
  const [up, setUp] = useState<boolean | null>(null);
  useEffect(() => {
    const check = () =>
      fetch("/api/health", { cache: "no-store" })
        .then((r) => setUp(r.ok))
        .catch(() => setUp(false));
    check();
    const t = setInterval(check, 10000);
    return () => clearInterval(t);
  }, []);
  return (
    <header className="border-b border-steel-2 bg-steel text-white">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3">
        <Link href="/" className="flex items-center gap-2">
          <span className="text-[15px] font-semibold">OpsCore</span>
          <span className="rounded-sm bg-white/10 px-1.5 py-px text-[11px] text-white/70">Sales demo</span>
        </Link>
        <nav className="flex gap-4 text-sm text-white/75">
          <Link href="/" className="hover:text-white">
            Scenarios
          </Link>
          <Link href="/console/permian" className="hover:text-white">
            Console
          </Link>
        </nav>
        <div className="ml-auto flex items-center gap-4">
          {right}
          <span className="flex items-center gap-1.5 text-[12px] text-white/70" title="OpsCore API">
            <span className={`h-2 w-2 rounded-full ${up === null ? "bg-white/40" : up ? "bg-[#51cf66]" : "bg-[#ff6b6b]"}`} />
            {up === null ? "Connecting…" : up ? "Connected" : "API offline"}
          </span>
        </div>
      </div>
    </header>
  );
}

// Icons and short labels that make each scenario readable at a glance: what kind of
// situation it is, where each step comes from, and which stage of the flow it reaches.

import {
  BellRing,
  Cctv,
  Construction,
  Container,
  DoorClosed,
  Drone,
  Droplets,
  Factory,
  Flame,
  Gauge,
  HardHat,
  Megaphone,
  MessageCircle,
  MessagesSquare,
  Moon,
  Radio,
  Reply,
  ScanEye,
  ShieldAlert,
  ShieldCheck,
  Ship,
  Truck,
  UserCheck,
  Wind,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { DemoClient } from "./clients";
import type { Action, Scenario, Step } from "./scenarios";

export const INDUSTRY_ICON: Record<DemoClient["industry"], LucideIcon> = { "Oil & Gas": Factory, Maritime: Ship };

/** Icon and "what you'll see" tags per scenario, for the scenario lists. */
export const SCENARIO_LOOK: Record<string, { icon: LucideIcon; shows: string[] }> = {
  "us-og-safety": { icon: Flame, shows: ["3 critical alerts", "SMS, WhatsApp, email", "Work orders", "Sealed record"] },
  "us-og-after-hours": { icon: Moon, shows: ["6 driver messages", "English and Spanish", "On-call handover"] },
  "latam-og-assets": { icon: Drone, shows: ["3 drone measurements", "Manager sign-off", "Wellhead fault", "Sealed record"] },
  "latam-og-contractors": { icon: HardHat, shows: ["3 contractor events", "WhatsApp to supervisor", "Corrective actions", "Sealed record"] },
  "latam-port-disruption": { icon: Megaphone, shows: ["Gate and vessel alerts", "28 truckers at once", "3 languages", "Team handover"] },
  "latam-port-yard": { icon: Construction, shows: ["2 near misses", "Wind warning", "Follow-ups closed", "Sealed record"] },
  "us-port-yard-safety": { icon: Container, shows: ["Yard near miss", "Squall warning", "Gate queue", "Sealed record"] },
  "us-port-congestion": { icon: Ship, shows: ["Gate and vessel alerts", "18 messages at once", "English and Spanish", "Team handover"] },
  "us-port-records": { icon: ShieldAlert, shows: ["Cyber incident", "Security lead told", "Evidence timeline"] },
};

// Where each kind of event comes from on a real site.
const EVENT_SOURCE: Record<string, [LucideIcon, string]> = {
  flare_flashback: [Flame, "Flare sensor"],
  struck_by_hazard: [ScanEye, "Proximity camera"],
  vehicle_incident: [Truck, "Vehicle telematics"],
  material_measurement: [Drone, "Drone survey"],
  equipment_fault: [Gauge, "Wellhead sensor"],
  ppe_violation: [Cctv, "Site camera"],
  spill: [Droplets, "Field report"],
  strike_disruption: [Megaphone, "Operations update"],
  gate_status: [DoorClosed, "Gate system"],
  vessel_delay: [Ship, "Vessel schedule"],
  truck_queue: [Truck, "Gate queue counter"],
  yard_near_miss: [Cctv, "Yard camera"],
  weather_alert: [Wind, "Weather station"],
  cyber_incident: [ShieldAlert, "Security monitoring"],
};

/** The icon and source line shown beside a step. */
export function stepLook(step: Step): { icon: LucideIcon; source: string } {
  const a = step.actions[0];
  switch (a.type) {
    case "event": {
      const [icon, source] = EVENT_SOURCE[a.body.event_type] ?? [Radio, "Site signal"];
      return { icon, source: step.actions.length > 1 ? `${source} and ${step.actions.length - 1} more` : source };
    }
    case "message":
      return { icon: MessageCircle, source: step.actions.length > 1 ? `${step.actions.length} people on WhatsApp` : `${a.name.split(" · ")[0]} on WhatsApp` };
    case "flood":
      return { icon: MessagesSquare, source: `${a.messages.length} people on WhatsApp` };
    case "replyEscalated":
      return { icon: Reply, source: "Your team, from the console" };
    case "verify":
      return { icon: ShieldCheck, source: "Record check" };
    case "completeWork":
      return { icon: Wrench, source: "Supervisor" };
    default:
      return { icon: UserCheck, source: "Supervisor" };
  }
}

export interface Stage {
  icon: LucideIcon;
  title: string;
  text: string;
}

/** The stages a scenario moves through, shown as a strip that fills in as steps run. */
export const FLOW: Record<Scenario["kind"], Stage[]> = {
  events: [
    { icon: Radio, title: "Signal received", text: "From a sensor, camera, survey or field report" },
    { icon: Workflow, title: "Rule applied", text: "Severity and who must know, by role and site" },
    { icon: BellRing, title: "People told", text: "SMS, WhatsApp or email, and work opened" },
    { icon: UserCheck, title: "Handled", text: "Acknowledged, work done, resolved" },
    { icon: ShieldCheck, title: "Record sealed", text: "Every step timestamped and verified" },
  ],
  chat: [
    { icon: MessageCircle, title: "Message received", text: "WhatsApp or SMS, in the sender's language" },
    { icon: MessagesSquare, title: "Answered", text: "Approved answer in seconds, in their language" },
    { icon: BellRing, title: "Exception to a person", text: "Danger or an unknown question alerts on-call" },
    { icon: Reply, title: "Team takes over", text: "A person replies; every message is logged" },
  ],
};

const SIGNAL: Action["type"][] = ["event", "message", "flood"];

/** Which stages a finished step has reached. `escalated` is how many messages went to a person. */
export function stagesReached(kind: Scenario["kind"], step: Step, escalated: number): number[] {
  const t = step.actions.map((a) => a.type);
  if (kind === "chat") {
    if (t.includes("replyEscalated")) return [3];
    if (t.some((x) => SIGNAL.includes(x))) return escalated > 0 ? [0, 1, 2] : [0, 1];
    return [];
  }
  if (t.includes("verify")) return [4];
  if (t.some((x) => SIGNAL.includes(x))) return [0, 1, 2];
  return [3];
}

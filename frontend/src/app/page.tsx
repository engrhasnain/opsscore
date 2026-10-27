import Link from "next/link";
import { ArrowRight, ChevronRight, Flame, Languages, LayoutDashboard, Mail, ShieldCheck, Smartphone } from "lucide-react";
import { SeverityBadge, TopBar } from "@/components/ui";
import { CLIENTS } from "@/lib/clients";
import { MARKETS, SCENARIOS } from "@/lib/scenarios";
import { FLOW, INDUSTRY_ICON, SCENARIO_LOOK } from "@/lib/visuals";

const ORDER = { "Lead with": 0, Then: 1, Context: 2 } as const;

// The four stages of the event flow, each with a small picture of what it looks like on screen.
const HOW = [FLOW.events[0], FLOW.events[1], FLOW.events[2], FLOW.events[4]];

function Sample({ i }: { i: number }) {
  if (i === 0)
    return (
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 place-items-center rounded bg-signal-soft text-signal">
          <Flame size={13} />
        </span>
        <span className="min-w-0">
          <span className="block text-[12px] font-medium">Flare flashback</span>
          <span className="block font-mono text-[10.5px] text-faint">Tank battery 14-1 · flare sensor</span>
        </span>
      </div>
    );
  if (i === 1)
    return (
      <div className="space-y-1">
        <SeverityBadge severity="critical" />
        <div className="text-[11.5px] text-mute">Safety lead and site supervisor · inspection due in 1 h</div>
      </div>
    );
  if (i === 2)
    return (
      <ul className="space-y-1 text-[11.5px]">
        {[
          { Icon: Smartphone, text: "SMS · Jordan Hayes" },
          { Icon: Mail, text: "Email · Jordan Hayes" },
        ].map(({ Icon, text }) => (
          <li key={text} className="flex items-center gap-1.5">
            <Icon size={12} className="text-mute" />
            <span className="flex-1">{text}</span>
            <span className="h-1.5 w-1.5 rounded-full bg-ok" />
            <span className="text-mute">Sent</span>
          </li>
        ))}
      </ul>
    );
  return (
    <div className="flex items-center gap-1.5 rounded bg-[#ebfbee] px-2 py-1.5 text-[11.5px] text-ok">
      <ShieldCheck size={13} /> Record intact, nothing edited
    </div>
  );
}

export default function Home() {
  return (
    <>
      <TopBar />
      <main className="mx-auto max-w-[1400px] px-5 pb-16 pt-8">
        <h1 className="text-[22px] font-semibold">Oil &amp; gas and maritime operations</h1>
        <p className="mt-1.5 max-w-3xl text-[14px] leading-relaxed text-mute">
          Something happens at a site, the right person knows in seconds, and a complete record is kept. Choose an operation and a scenario to see it live.
        </p>

        <section className="panel mt-6 px-5 py-5">
          <h2 className="text-[14px] font-semibold">How OpsCore works</h2>
          <ol className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4 lg:gap-8">
            {HOW.map((s, i) => (
              <li key={s.title} className="relative flex flex-col">
                <div className="flex items-center gap-2.5">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-steel text-white">
                    <s.icon size={17} />
                  </span>
                  <span>
                    <span className="block font-mono text-[11px] text-faint">{i + 1}</span>
                    <span className="block text-[14px] font-semibold leading-tight">{s.title}</span>
                  </span>
                </div>
                <p className="mt-2 text-[12.5px] leading-snug text-mute">{s.text}</p>
                <div className="mt-3 flex-1 rounded border border-line bg-paper p-2.5">
                  <Sample i={i} />
                </div>
                {i < HOW.length - 1 && <ChevronRight size={20} className="absolute -right-7 top-2 hidden text-faint lg:block" aria-hidden />}
              </li>
            ))}
          </ol>
        </section>

        <h2 className="mt-9 text-[16px] font-semibold">Choose an operation</h2>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          {MARKETS.map((m) => {
            const c = CLIENTS[m.key];
            const Industry = INDUSTRY_ICON[c.industry];
            const list = SCENARIOS.filter((s) => s.client === m.key).sort((a, b) => ORDER[a.priority] - ORDER[b.priority]);
            return (
              <section key={m.key} className="panel flex flex-col">
                <div className="flex items-start gap-3 border-b border-line px-5 py-4">
                  <span className="grid h-11 w-11 shrink-0 place-items-center rounded bg-steel text-white">
                    <Industry size={21} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[12px] text-mute">{c.marketLabel.replace(/^./, (x) => x.toUpperCase())}</div>
                    <h3 className="text-[16px] font-semibold leading-snug">{c.name}</h3>
                    <div className="text-[13px] text-mute">{c.place}</div>
                  </div>
                  <div className="hidden items-center gap-1.5 text-[12px] text-mute sm:flex">
                    <Languages size={13} />
                    {c.language.split(" · ").join(", ")}
                  </div>
                </div>
                <ul className="flex-1 divide-y divide-line">
                  {list.map((s) => {
                    const look = SCENARIO_LOOK[s.id];
                    const Icon = look.icon;
                    return (
                      <li key={s.id}>
                        <Link href={`/scenario/${s.id}`} className="group flex items-start gap-3 px-5 py-3.5 hover:bg-paper">
                          <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded border border-line bg-paper text-ink group-hover:border-ink group-hover:bg-panel">
                            <Icon size={17} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block text-[14px] font-medium leading-snug">{s.title}</span>
                            <span className="mt-0.5 block text-[12.5px] leading-snug text-mute">{s.summary}</span>
                            <span className="mt-2 flex flex-wrap gap-1.5">
                              {look.shows.map((t) => (
                                <span key={t} className="rounded-sm border border-line bg-panel px-1.5 py-px text-[11.5px] text-mute">
                                  {t}
                                </span>
                              ))}
                            </span>
                          </span>
                          <span className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
                            <ArrowRight size={15} className="text-faint group-hover:text-ink" />
                            <span className="font-mono text-[11px] text-faint">{s.steps.length} steps</span>
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
                <Link href={`/console/${m.key}`} className="flex items-center gap-2 border-t border-line px-5 py-2.5 text-[13px] font-medium text-mute hover:text-ink">
                  <LayoutDashboard size={14} /> Open the operations console
                </Link>
              </section>
            );
          })}
        </div>
      </main>
    </>
  );
}

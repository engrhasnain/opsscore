import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { TopBar } from "@/components/ui";
import { CLIENTS } from "@/lib/clients";
import { MARKETS, SCENARIOS } from "@/lib/scenarios";

const ORDER = { "Lead with": 0, Then: 1, Context: 2 } as const;

export default function Home() {
  return (
    <>
      <TopBar />
      <main className="mx-auto max-w-[1400px] px-5 pb-16 pt-8">
        <h1 className="text-[22px] font-semibold">Oil &amp; gas and maritime operations</h1>
        <p className="mt-1.5 max-w-3xl text-[14px] leading-relaxed text-mute">
          Something happens at a site, the right person knows in seconds, and a complete record is kept. Choose an operation and a scenario to see it live.
        </p>

        <div className="mt-7 grid gap-4 md:grid-cols-2">
          {MARKETS.map((m) => {
            const c = CLIENTS[m.key];
            const list = SCENARIOS.filter((s) => s.client === m.key).sort((a, b) => ORDER[a.priority] - ORDER[b.priority]);
            return (
              <section key={m.key} className="panel flex flex-col">
                <div className="border-b border-line px-5 py-4">
                  <div className="text-[12px] text-mute">{c.marketLabel.replace(/^./, (x) => x.toUpperCase())}</div>
                  <h2 className="text-[16px] font-semibold">{c.name}</h2>
                  <div className="text-[13px] text-mute">
                    {c.place} · {c.language}
                  </div>
                </div>
                <ul className="flex-1 divide-y divide-line">
                  {list.map((s) => (
                    <li key={s.id}>
                      <Link href={`/scenario/${s.id}`} className="group flex items-start gap-3 px-5 py-3 hover:bg-paper">
                        <span className="min-w-0 flex-1">
                          <span className="block text-[14px] font-medium leading-snug">{s.title}</span>
                          <span className="mt-0.5 block text-[12.5px] leading-snug text-mute">{s.summary}</span>
                        </span>
                        <ArrowRight size={15} className="mt-1 shrink-0 text-faint group-hover:text-ink" />
                      </Link>
                    </li>
                  ))}
                </ul>
                <Link href={`/console/${m.key}`} className="border-t border-line px-5 py-2.5 text-[13px] font-medium text-mute hover:text-ink">
                  Open the operations console
                </Link>
              </section>
            );
          })}
        </div>
      </main>
    </>
  );
}

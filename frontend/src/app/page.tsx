import Link from "next/link";
import { TopBar } from "@/components/ui";
import { CLIENTS, type ClientKey } from "@/lib/clients";
import { MARKETS, SCENARIOS, type Scenario } from "@/lib/scenarios";

// Ratings from the research's "Pain by pain" table.
const PAINS: { pain: string; title: string; us: string; latam: string }[] = [
  { pain: "O&G 1", title: "Safety and compliance in remote, hazardous sites", us: "High. Documented fatalities, new OSHA alert (Sept 2026)", latam: "Medium (hypothesis). Contractor supervision" },
  { pain: "O&G 2", title: "Visibility over remote assets and logistics", us: "Medium. Data fragmentation, paper workflows", latam: "High. Pipeline, road and site constraints" },
  { pain: "O&G 3", title: "Workforce gap and fragmented coordination", us: "High. About 20% retirements cited", latam: "Medium (hypothesis). Growth-driven coordination load" },
  { pain: "Maritime 1", title: "Port congestion and schedule unreliability", us: "Medium-high. Tariffs, surges, labor risk", latam: "High. Waits of 3–5 days, canal queues" },
  { pain: "Maritime 2", title: "Labor shortage, automation tension, yard safety", us: "High. Automation was the core of the 2024 strike", latam: "Medium. Strikes and blockades" },
  { pain: "Maritime 3", title: "Regulatory, emissions, cyber, geopolitics", us: "High. Cyber rules, tariffs, IMO / EU ETS", latam: "Medium-high. Chokepoints, insurance, canal drought" },
];

const find = (client: ClientKey, priority: Scenario["priority"]) => SCENARIOS.find((s) => s.client === client && s.priority === priority);

function DemoLink({ s }: { s?: Scenario }) {
  if (!s) return <span className="text-faint">–</span>;
  return (
    <Link href={`/demo/${s.id}`} className="group block">
      <span className="text-[12px] text-mute">{s.pain}</span>
      <span className="block font-medium text-ink underline decoration-line underline-offset-4 group-hover:decoration-ink">{s.title}</span>
    </Link>
  );
}

export default function Home() {
  return (
    <>
      <TopBar />
      <main className="mx-auto max-w-[1400px] px-5 pb-16 pt-8">
        <h1 className="text-[22px] font-semibold">Sales demos: oil &amp; gas and maritime</h1>
        <p className="mt-1.5 max-w-3xl text-[14px] leading-relaxed text-mute">
          One scenario per pain point from the October 2026 research, run live against OpsCore. Pick the market you are pitching, lead with the first demo and keep each one to five to seven minutes.
        </p>

        <section className="mt-7">
          <h2 className="text-[15px] font-semibold">Priority by market</h2>
          <div className="mt-3 space-y-3 md:hidden">
            {MARKETS.map((m) => {
              const c = CLIENTS[m.key];
              return (
                <div key={m.key} className="panel p-4 text-[13.5px]">
                  <div className="font-semibold">{c.marketLabel.replace(/^./, (x) => x.toUpperCase())}</div>
                  <div className="text-[12.5px] text-mute">
                    {c.name}, {c.place}
                  </div>
                  <div className="mt-3 text-[12px] text-mute">Lead with</div>
                  <DemoLink s={find(m.key, "Lead with")} />
                  <div className="mt-3 text-[12px] text-mute">Then</div>
                  <DemoLink s={find(m.key, "Then")} />
                  <div className="mt-3 text-[12px] text-mute">Skip for now: {m.skip}</div>
                </div>
              );
            })}
          </div>
          <div className="panel mt-3 hidden overflow-x-auto md:block">
            <table className="w-full min-w-[980px] text-[13.5px]">
              <thead>
                <tr className="border-b border-line bg-paper text-left text-[12px] text-mute">
                  <th className="w-[230px] px-4 py-2 font-medium">Market and demo client</th>
                  <th className="px-4 py-2 font-medium">Lead with</th>
                  <th className="px-4 py-2 font-medium">Then</th>
                  <th className="w-[230px] px-4 py-2 font-medium">Skip for now</th>
                </tr>
              </thead>
              <tbody>
                {MARKETS.map((m) => {
                  const c = CLIENTS[m.key];
                  const context = find(m.key, "Context");
                  return (
                    <tr key={m.key} className="border-b border-line align-top last:border-0">
                      <td className="px-4 py-3">
                        <div className="font-semibold">{c.marketLabel.replace(/^./, (x) => x.toUpperCase())}</div>
                        <div className="text-[12.5px] text-mute">
                          {c.name}, {c.place}
                        </div>
                        <div className="text-[12.5px] text-mute">{c.language}</div>
                        <Link href={`/console/${m.key}`} className="mt-1.5 inline-block text-[12.5px] text-mute underline decoration-line underline-offset-4 hover:text-ink">
                          Open the console
                        </Link>
                      </td>
                      <td className="px-4 py-3">
                        <DemoLink s={find(m.key, "Lead with")} />
                      </td>
                      <td className="px-4 py-3">
                        <DemoLink s={find(m.key, "Then")} />
                      </td>
                      <td className="px-4 py-3 text-mute">
                        {m.skip}
                        {context && (
                          <div className="mt-2">
                            <span className="text-[12px]">Short context demo: </span>
                            <Link href={`/demo/${context.id}`} className="text-ink underline decoration-line underline-offset-4 hover:decoration-ink">
                              {context.title}
                            </Link>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="mt-9">
          <h2 className="text-[15px] font-semibold">The six pains, US and Latin America</h2>
          <div className="panel mt-3 overflow-x-auto">
            <table className="w-full min-w-[980px] text-[13.5px]">
              <thead>
                <tr className="border-b border-line bg-paper text-left text-[12px] text-mute">
                  <th className="px-4 py-2 font-medium">Pain</th>
                  <th className="px-4 py-2 font-medium">United States</th>
                  <th className="px-4 py-2 font-medium">Latin America</th>
                  <th className="px-4 py-2 font-medium">Demos</th>
                </tr>
              </thead>
              <tbody>
                {PAINS.map((p) => (
                  <tr key={p.pain} className="border-b border-line align-top last:border-0">
                    <td className="px-4 py-3">
                      <div className="text-[12px] text-mute">{p.pain}</div>
                      <div className="font-medium">{p.title}</div>
                    </td>
                    <td className="px-4 py-3 text-mute">{p.us}</td>
                    <td className="px-4 py-3 text-mute">{p.latam}</td>
                    <td className="px-4 py-3">
                      <ul className="space-y-1">
                        {SCENARIOS.filter((s) => s.pain === p.pain).map((s) => (
                          <li key={s.id}>
                            <Link href={`/demo/${s.id}`} className="underline decoration-line underline-offset-4 hover:decoration-ink">
                              {CLIENTS[s.client].name}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[12px] text-mute">
            Figures come from public sources; several are trade summaries, so treat them as indicative. Claims marked as a hypothesis should be checked in discovery calls.
          </p>
        </section>
      </main>
    </>
  );
}

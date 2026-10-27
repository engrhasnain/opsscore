"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Check, CircleAlert, Loader2, Play, RotateCcw } from "lucide-react";
import { TopBar, useDisplayZone } from "./ui";
import { EventsBoard } from "./EventsBoard";
import { ChatBoard } from "./ChatBoard";
import { CLIENTS } from "@/lib/clients";
import { scenario } from "@/lib/scenarios";
import { clearStage, runAction, type ActionResult } from "@/lib/runner";
import { useLookups } from "@/lib/api";
import { FLOW, INDUSTRY_ICON, SCENARIO_LOOK, stagesReached, stepLook } from "@/lib/visuals";

type StepState = { status: "idle" | "running" | "done" | "error"; results: ActionResult[] };

type Session = { since: string; run: number };
const newRun = (since: string): Session => ({ since, run: Math.floor(Math.random() * 9000) + 1000 });

export function ScenarioRunner({ id }: { id: string }) {
  const sc = scenario(id)!;
  const client = CLIENTS[sc.client];
  useDisplayZone(client.timeZone);
  const lookups = useLookups(sc.client);
  const [session, setSession] = useState<Session | null>(null);
  const [prepError, setPrepError] = useState<string | null>(null);
  const [steps, setSteps] = useState<StepState[]>(() => sc.steps.map(() => ({ status: "idle", results: [] })));

  // Start each run on a clean board (see clearStage).
  const prepare = useCallback(() => {
    setSession(null);
    setPrepError(null);
    clearStage(sc.client)
      .then((since) => setSession(newRun(since)))
      .catch((e: Error) => setPrepError(e.message));
  }, [sc.client]);
  useEffect(prepare, [prepare]);

  const next = steps.findIndex((s) => s.status !== "done");
  const busy = !session || steps.some((s) => s.status === "running");
  const reached = new Set(
    steps.flatMap((st, i) => (st.status === "done" ? stagesReached(sc.kind, sc.steps[i], st.results.reduce((n, r) => n + (r.escalated ?? 0), 0)) : [])),
  );
  const look = SCENARIO_LOOK[sc.id];
  const Industry = INDUSTRY_ICON[client.industry];

  const runStep = useCallback(
    async (i: number) => {
      if (!session) return;
      setSteps((s) => s.map((x, j) => (j === i ? { status: "running", results: [] } : x)));
      const results: ActionResult[] = [];
      let failed = false;
      for (const a of sc.steps[i].actions) {
        try {
          const r = await runAction(sc.client, a, session.since, session.run);
          results.push(r);
          if (!r.ok) failed = true;
        } catch (e) {
          results.push({ ok: false, text: (e as Error).message });
          failed = true;
        }
        setSteps((s) => s.map((x, j) => (j === i ? { status: "running", results: [...results] } : x)));
      }
      setSteps((s) => s.map((x, j) => (j === i ? { status: failed ? "error" : "done", results } : x)));
    },
    [sc, session],
  );

  const restart = () => {
    prepare();
    setSteps(sc.steps.map(() => ({ status: "idle", results: [] })));
  };

  const board = useMemo(
    () =>
      !session ? (
        <div className="panel p-8 text-center text-[13px] text-mute">{prepError ?? "Loading…"}</div>
      ) : sc.kind === "chat" ? (
        <ChatBoard client={sc.client} since={session.since} lookups={lookups} />
      ) : (
        <EventsBoard client={sc.client} since={session.since} lookups={lookups} osha={sc.client === "permian"} />
      ),
    [sc, session, lookups, prepError],
  );

  return (
    <>
      <TopBar
        right={
          <Link href={`/console/${sc.client}`} className="text-[12px] text-white/75 hover:text-white">
            {client.name} console
          </Link>
        }
      />
      <main className="mx-auto grid max-w-[1400px] gap-6 px-5 py-5 lg:grid-cols-[380px_minmax(0,1fr)]">
        <aside className="space-y-5 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-y-auto lg:pr-1">
          <div>
            <Link href="/" className="inline-flex items-center gap-1 text-[12px] text-mute hover:text-ink">
              <ArrowLeft size={13} /> All scenarios
            </Link>
            <div className="mt-3 flex items-center gap-2 text-[12px] text-mute">
              <span className="grid h-6 w-6 place-items-center rounded bg-steel text-white">
                <Industry size={13} />
              </span>
              {client.name} · {client.place}
            </div>
            <h1 className="mt-2 text-[19px] font-semibold leading-snug">{sc.title}</h1>
            <p className="mt-1.5 text-[13px] leading-relaxed text-mute">{sc.summary}</p>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {look.shows.map((t) => (
                <span key={t} className="rounded-sm border border-line bg-panel px-1.5 py-px text-[11.5px] text-mute">
                  {t}
                </span>
              ))}
            </div>
          </div>

          <section>
            <h2 className="mb-1.5 text-[12px] font-semibold text-mute">Steps</h2>
            <ol className="rounded border border-line bg-panel py-1">
              {sc.steps.map((step, i) => {
                const st = steps[i];
                const isNext = i === next;
                const { icon: Icon, source } = stepLook(step);
                const last = i === sc.steps.length - 1;
                return (
                  <li key={step.label} className={`relative flex items-start gap-3 px-3 py-2.5 ${isNext && !busy ? "bg-[#f7f9fc]" : ""}`}>
                    {!last && <span className={`absolute bottom-0 left-[29.5px] top-[46px] w-px ${st.status === "done" ? "bg-ok" : "bg-line"}`} aria-hidden />}
                    <span
                      className={`relative z-[1] grid h-9 w-9 shrink-0 place-items-center rounded-full ${
                        st.status === "done"
                          ? "bg-ok text-white"
                          : st.status === "error"
                            ? "bg-sev-critical text-white"
                            : st.status === "running"
                              ? "bg-signal text-white"
                              : isNext
                                ? "border-2 border-steel bg-panel text-steel"
                                : "border border-line bg-panel text-faint"
                      }`}
                    >
                      {st.status === "running" ? <Loader2 size={16} className="animate-spin" /> : <Icon size={16} />}
                      {st.status === "done" && (
                        <span className="absolute -bottom-0.5 -right-0.5 grid h-3.5 w-3.5 place-items-center rounded-full bg-panel text-ok">
                          <Check size={10} strokeWidth={3} />
                        </span>
                      )}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="font-mono text-[10.5px] text-faint">
                        {i + 1} · {source}
                      </div>
                      <div className="text-[13.5px] font-medium leading-snug">{step.label}</div>
                      <div className="mt-0.5 text-[12.5px] leading-snug text-mute">{step.detail}</div>
                      {st.results.length > 0 && (
                        <ul className="mt-1.5 space-y-0.5" aria-live="polite">
                          {st.results.map((r, j) => (
                            <li key={j} className={`flex gap-1.5 text-[12px] ${r.ok ? "text-ok" : "text-sev-critical"}`}>
                              {r.ok ? <Check size={12} className="mt-0.5 shrink-0" /> : <CircleAlert size={12} className="mt-0.5 shrink-0" />}
                              <span>{r.text}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <button onClick={() => runStep(i)} disabled={busy} className={`${isNext ? "btn-dark" : "btn-line"} shrink-0 !px-2.5 !py-1 !text-[12px]`}>
                      {st.status === "done" ? "Run again" : "Run"}
                    </button>
                  </li>
                );
              })}
            </ol>
            <button onClick={restart} disabled={busy && !prepError} className="mt-2 inline-flex items-center gap-1 text-[12px] text-mute hover:text-ink disabled:opacity-40">
              <RotateCcw size={12} /> Reset
            </button>
          </section>
        </aside>

        <section className="min-w-0 space-y-4">
          <FlowStrip kind={sc.kind} reached={reached} />
          {next >= 0 && (
            <div className="flex flex-wrap items-center gap-3 rounded border border-line bg-panel px-4 py-2.5">
              <span className="text-[12px] text-mute">Next</span>
              <span className="min-w-0 flex-1 text-[13.5px] font-medium">
                {next + 1}. {sc.steps[next].label}
              </span>
              <button onClick={() => runStep(next)} disabled={busy} className="btn-dark !px-3 !py-1 !text-[12.5px]">
                <Play size={12} /> Run
              </button>
            </div>
          )}
          {board}
        </section>
      </main>
    </>
  );
}

/** The stages of the scenario, lit up as steps reach them. */
function FlowStrip({ kind, reached }: { kind: "events" | "chat"; reached: Set<number> }) {
  const stages = FLOW[kind];
  const current = stages.findIndex((_, i) => !reached.has(i));
  return (
    <ol className={`panel grid grid-cols-2 gap-x-3 gap-y-4 px-4 py-4 sm:grid-cols-3 ${stages.length === 5 ? "lg:grid-cols-5" : "lg:grid-cols-4"}`}>
      {stages.map((s, i) => {
        const done = reached.has(i);
        const now = i === current;
        return (
          <li key={s.title} className="relative">
            {i < stages.length - 1 && <span className={`absolute left-[38px] right-[-4px] top-[15px] hidden h-0.5 lg:block ${done ? "bg-ok" : "bg-line"}`} aria-hidden />}
            <span
              className={`relative grid h-[30px] w-[30px] place-items-center rounded-full transition-colors ${
                done ? "bg-ok text-white" : now ? "border-2 border-signal bg-panel text-signal" : "border border-line bg-panel text-faint"
              }`}
            >
              {done ? <Check size={15} strokeWidth={2.5} /> : <s.icon size={15} />}
            </span>
            <span className={`mt-2 block text-[12.5px] font-semibold leading-tight ${done ? "text-ok" : now ? "text-ink" : "text-mute"}`}>{s.title}</span>
            <span className="mt-0.5 block pr-2 text-[11.5px] leading-snug text-mute">{s.text}</span>
          </li>
        );
      })}
    </ol>
  );
}

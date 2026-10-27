"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Check, CircleAlert, Loader2, RotateCcw } from "lucide-react";
import { TopBar, useDisplayZone } from "./ui";
import { EventsBoard } from "./EventsBoard";
import { ChatBoard } from "./ChatBoard";
import { CLIENTS } from "@/lib/clients";
import { scenario } from "@/lib/scenarios";
import { clearStage, runAction, type ActionResult } from "@/lib/runner";
import { useLookups } from "@/lib/api";

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
            <div className="mt-3 text-[12px] text-mute">
              {client.name} · {client.place}
            </div>
            <h1 className="mt-1 text-[19px] font-semibold leading-snug">{sc.title}</h1>
            <p className="mt-1.5 text-[13px] leading-relaxed text-mute">{sc.summary}</p>
          </div>

          <section>
            <h2 className="mb-1.5 text-[12px] font-semibold text-mute">Steps</h2>
            <ol className="divide-y divide-line rounded border border-line bg-panel">
              {sc.steps.map((step, i) => {
                const st = steps[i];
                const isNext = i === next;
                return (
                  <li key={step.label} className={`flex items-start gap-3 p-3 ${isNext && !busy ? "bg-[#f7f9fc]" : ""}`}>
                    <span
                      className={`mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold ${
                        st.status === "done" ? "bg-ok text-white" : st.status === "error" ? "bg-sev-critical text-white" : "border border-line text-mute"
                      }`}
                    >
                      {st.status === "done" ? <Check size={12} /> : st.status === "running" ? <Loader2 size={12} className="animate-spin" /> : i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
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

        <section className="min-w-0">{board}</section>
      </main>
    </>
  );
}


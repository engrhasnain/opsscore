"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientKey } from "./clients";
import type { Asset, Contact, EventType, Page, Rule, Site } from "./types";

/** Call the OpsCore API (through this app's proxy) as the given demo client. */
export async function ops<T = unknown>(
  client: ClientKey,
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const res = await fetch(`/api/ops/${client}${path}`, {
    method: init.method ?? "GET",
    headers: { "Content-Type": "application/json" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok)
    throw new Error(
      (data as { message?: string }).message ||
        `Request failed (${res.status})`,
    );
  return data as T;
}

/**
 * Poll several endpoints together; returns the latest results and a manual refresh.
 * The next poll starts only after the current one finishes, and a reply that arrives
 * after a newer one (from a manual refresh) is dropped.
 */
export function usePoll<T extends Record<string, unknown>>(
  client: ClientKey,
  paths: Record<keyof T, string>,
  intervalMs = 1500,
) {
  const [data, setData] = useState<Partial<T>>({});
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const key = JSON.stringify(paths);
  const pathsRef = useRef(paths);
  pathsRef.current = paths;
  const seq = useRef(0);

  const refresh = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const entries = await Promise.all(
        Object.entries(pathsRef.current).map(
          async ([k, p]) => [k, await ops(client, p as string)] as const,
        ),
      );
      if (mine !== seq.current) return;
      setData(Object.fromEntries(entries) as Partial<T>);
      setError(null);
    } catch (e) {
      if (mine === seq.current) setError((e as Error).message);
    } finally {
      if (mine === seq.current) setTick((t) => t + 1);
    }
  }, [client]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      await refresh();
      if (alive) timer = setTimeout(loop, intervalMs);
    };
    loop();
    return () => {
      alive = false;
      // Bump the counter so a reply still in flight from this effect is ignored.
      // eslint-disable-next-line react-hooks/exhaustive-deps -- a plain counter, not a DOM ref
      seq.current++;
      clearTimeout(timer);
    };
  }, [refresh, intervalMs, key]);

  return { data, error, refresh, tick };
}

export interface Lookups {
  sites: Map<string, Site>;
  assets: Map<string, Asset>;
  contacts: Map<string, Contact>;
  eventTypes: Map<string, EventType>;
  rules: Map<string, Rule>;
}

/** Sites, assets, contacts, event types and rules, to turn ids into names. */
export function useLookups(client: ClientKey): Lookups | null {
  const [lookups, setLookups] = useState<Lookups | null>(null);
  useEffect(() => {
    let alive = true;
    let retry: ReturnType<typeof setTimeout>;
    const byId = <T extends { id: string }>(p: Page<T>) =>
      new Map(p.items.map((x) => [x.id, x]));
    const load = () =>
      Promise.all([
        ops<Page<Site>>(client, "/sites?limit=200"),
        ops<Page<Asset>>(client, "/assets?limit=200"),
        ops<Page<Contact>>(client, "/contacts?limit=200"),
        ops<Page<EventType>>(client, "/event-types?limit=200"),
        ops<Page<Rule>>(client, "/rules?limit=200"),
      ])
        .then(
          ([s, a, c, e, r]) =>
            alive &&
            setLookups({
              sites: byId(s),
              assets: byId(a),
              contacts: byId(c),
              eventTypes: byId(e),
              rules: byId(r),
            }),
        )
        // Retry until the backend answers, so names fill in once it is up.
        .catch(() => alive && (retry = setTimeout(load, 3000)));
    load();
    return () => {
      alive = false;
      clearTimeout(retry);
    };
  }, [client]);
  return lookups;
}

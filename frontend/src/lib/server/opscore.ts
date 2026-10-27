import "server-only";
import { CLIENTS, type ClientKey } from "../clients";

// Talks to the OpsCore API on behalf of the demo screens.
// - People's actions (reading, acknowledging, replying) use the client's owner login.
// - Device traffic (sensor events, inbound WhatsApp/SMS) needs a device API key, which
//   OpsCore only hands out once, so the first time it's needed we create one and keep it.

const API = (process.env.OPSCORE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "") + "/api/v1";
const PASSWORD = process.env.OPSCORE_DEMO_PASSWORD || "demo-password-1234";

interface Cache {
  tokens: Partial<Record<ClientKey, { token: string; expires: number }>>;
  keys: Partial<Record<ClientKey, string>>;
  // In-flight logins and key creations, so parallel requests share one call
  // (OpsCore rate-limits logins to 10 a minute).
  loggingIn: Partial<Record<ClientKey, Promise<string>>>;
  creatingKey: Partial<Record<ClientKey, Promise<string>>>;
}
const g = globalThis as unknown as { __opscore?: Cache };
const cache: Cache = (g.__opscore ??= { tokens: {}, keys: {}, loggingIn: {}, creatingKey: {} });

export class OpsError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

async function raw(path: string, init: RequestInit & { auth: Record<string, string> }): Promise<Response> {
  const { auth, headers, ...rest } = init;
  try {
    return await fetch(API + path, {
      ...rest,
      headers: { "Content-Type": "application/json", ...auth, ...(headers as Record<string, string>) },
      cache: "no-store",
    });
  } catch {
    throw new OpsError(503, `Can't reach the OpsCore API at ${API}. Is the backend running?`);
  }
}

async function token(client: ClientKey, fresh = false): Promise<string> {
  const hit = cache.tokens[client];
  if (!fresh && hit && hit.expires > Date.now() + 60_000) return hit.token;
  cache.loggingIn[client] ??= login(client).finally(() => delete cache.loggingIn[client]);
  return cache.loggingIn[client];
}

async function login(client: ClientKey): Promise<string> {
  const res = await raw("/auth/login", {
    method: "POST",
    auth: {},
    body: JSON.stringify({ email: CLIENTS[client].email, password: PASSWORD }),
  });
  if (res.status === 429) throw new OpsError(429, "Too many logins to OpsCore in the last minute. Wait a moment and try again.");
  if (!res.ok) {
    throw new OpsError(res.status, `Could not sign in to OpsCore for ${CLIENTS[client].name}.`);
  }
  const data = (await res.json()) as { access_token: string; expires_in?: number };
  cache.tokens[client] = { token: data.access_token, expires: Date.now() + (data.expires_in ?? 3600) * 1000 };
  return data.access_token;
}

async function deviceKey(client: ClientKey): Promise<string> {
  const hit = cache.keys[client];
  if (hit) return hit;
  cache.creatingKey[client] ??= createKey(client).finally(() => delete cache.creatingKey[client]);
  return cache.creatingKey[client];
}

async function createKey(client: ClientKey): Promise<string> {
  const created = (await asUser(client, "/api-keys", {
    method: "POST",
    body: JSON.stringify({ name: "Site devices", scopes: ["events:write", "messages:write"] }),
  })) as { key?: string; secret?: string; api_key?: string };
  const key = created.key ?? created.secret ?? created.api_key;
  if (!key) throw new OpsError(500, "OpsCore did not return a device key.");
  cache.keys[client] = key;
  return key;
}

async function parse(res: Response) {
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    // OpsCore errors look like {"error": {"code", "message", "details"}}.
    const message = (body && (body.error?.message || body.message || body.detail)) || `OpsCore returned ${res.status}`;
    throw new OpsError(res.status, typeof message === "string" ? message : JSON.stringify(message), body);
  }
  return body;
}

/** Call as the client's owner (a signed-in person). Retries once with a fresh login. */
export async function asUser(client: ClientKey, path: string, init: RequestInit = {}): Promise<unknown> {
  let res = await raw(path, { ...init, auth: { Authorization: `Bearer ${await token(client)}` } });
  if (res.status === 401) res = await raw(path, { ...init, auth: { Authorization: `Bearer ${await token(client, true)}` } });
  return parse(res);
}

/** Call as a device (sensor, WhatsApp gateway). */
export async function asDevice(client: ClientKey, path: string, init: RequestInit = {}): Promise<unknown> {
  let res = await raw(path, { ...init, auth: { "X-API-Key": await deviceKey(client) } });
  if (res.status === 401) {
    delete cache.keys[client];
    res = await raw(path, { ...init, auth: { "X-API-Key": await deviceKey(client) } });
  }
  return parse(res);
}

/** Paths that only devices may call. */
export function isDevicePath(method: string, path: string): boolean {
  return method === "POST" && (path === "/events" || path === "/assistant/inbound");
}

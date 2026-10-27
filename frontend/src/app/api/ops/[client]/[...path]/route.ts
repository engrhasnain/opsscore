import { NextResponse } from "next/server";
import { isClientKey } from "@/lib/clients";
import { asDevice, asUser, isDevicePath, OpsError } from "@/lib/server/opscore";

export const dynamic = "force-dynamic";

// Forwards the demo screens' calls to the OpsCore API, signed in as the chosen demo client.
// Only the method + path pairs the screens use are allowed through: the demo can read
// setup and act on alerts, work orders and conversations, but cannot change setup.
const ALLOWED: [string, RegExp][] = [
  ["GET", /^\/(sites|assets|contacts|event-types|rules|events|alerts|work-orders|notifications|audit)$/],
  ["GET", /^\/(alerts|work-orders|events)\/[\w-]+$/],
  ["GET", /^\/audit\/verify$/],
  ["GET", /^\/members$/], // names on the incident record
  ["GET", /^\/assistant\/(knowledge|conversations)$/],
  ["GET", /^\/assistant\/conversations\/[\w-]+$/],
  ["POST", /^\/events$/],
  ["POST", /^\/assistant\/inbound$/],
  ["POST", /^\/alerts\/[\w-]+\/(acknowledge|resolve|reopen)$/],
  ["POST", /^\/work-orders\/[\w-]+\/transition$/],
  ["POST", /^\/assistant\/conversations\/[\w-]+\/(reply|hand-back|close)$/],
];

async function handle(req: Request, { params }: { params: Promise<{ client: string; path: string[] }> }) {
  const { client, path } = await params;
  if (!isClientKey(client)) return NextResponse.json({ message: `Unknown demo client "${client}"` }, { status: 404 });
  const apiPath = "/" + path.join("/");
  if (!ALLOWED.some(([method, re]) => method === req.method && re.test(apiPath))) return NextResponse.json({ message: "Not available in the demo" }, { status: 404 });

  const url = new URL(req.url);
  const target = apiPath + url.search;
  const body = req.method === "GET" ? undefined : await req.text();
  try {
    const data = isDevicePath(req.method, apiPath)
      ? await asDevice(client, target, { method: req.method, body })
      : await asUser(client, target, { method: req.method, body: body || undefined });
    return NextResponse.json(data ?? {});
  } catch (err) {
    if (err instanceof OpsError) return NextResponse.json({ message: err.message, details: err.body }, { status: err.status });
    return NextResponse.json({ message: "Unexpected error talking to OpsCore" }, { status: 500 });
  }
}

export { handle as GET, handle as POST };

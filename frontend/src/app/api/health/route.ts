import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const API = (process.env.OPSCORE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export async function GET() {
  try {
    const res = await fetch(`${API}/health/ready`, { cache: "no-store" });
    return NextResponse.json({ ok: res.ok, now: new Date().toISOString() }, { status: res.ok ? 200 : 503 });
  } catch {
    return NextResponse.json({ ok: false, now: new Date().toISOString() }, { status: 503 });
  }
}

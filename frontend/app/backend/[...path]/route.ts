import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const TARGET = process.env.BACKEND_URL || "http://127.0.0.1:43124";

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = `${TARGET}/${path.join("/")}${req.nextUrl.search}`;
  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  // 后端只接受回环来源（uvicorn 会信任来自 127.0.0.1 的 X-Forwarded-For）。认证已经在
  // frontend/server/mobile-auth.mjs 里按真实 socket 地址做完，这里不再把手机 IP 转给后端。
  for (const name of ["x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port", "x-real-ip", "forwarded"]) {
    headers.delete(name);
  }
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const res = await fetch(url, {
    method: req.method,
    headers,
    body: hasBody ? await req.arrayBuffer() : undefined,
    cache: "no-store",
    redirect: "manual",
  });
  const out = new Headers(res.headers);
  out.delete("content-encoding");
  out.delete("content-length");
  out.set("Cache-Control", "no-cache, no-transform");
  out.set("X-Accel-Buffering", "no");
  return new Response(res.body, { status: res.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;

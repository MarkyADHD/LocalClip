import { NextResponse } from "next/server";

import { createProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

// Settings that apply to the whole app (AI model, API keys); the backend checks the user may change them.
async function proxyAdminRequest(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { path } = await params;
  const body = request.method === "GET" ? undefined : await request.text();
  const upstream = await fetchBackend(`/admin/${path.join("/")}`, {
    method: request.method,
    userId: session.user.id,
    extraHeaders: body ? { "Content-Type": "application/json" } : undefined,
    body,
    cache: "no-store",
  });
  return createProxyResponse(upstream);
}

export { proxyAdminRequest as GET, proxyAdminRequest as PATCH };

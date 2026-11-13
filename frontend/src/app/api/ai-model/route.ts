import { NextRequest, NextResponse } from "next/server";

import { createTextProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

// GET: the selected LLM plus every model found on this PC. PUT: pick one.
async function proxy(method: "GET" | "PUT", body?: string) {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const upstream = await fetchBackend("/admin/llm", {
    method,
    body,
    userId: session.user.id,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    cache: "no-store",
  });
  return createTextProxyResponse(upstream);
}

export function GET() {
  return proxy("GET");
}

export async function PUT(request: NextRequest) {
  return proxy("PUT", await request.text());
}

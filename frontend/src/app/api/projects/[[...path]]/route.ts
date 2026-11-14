import { NextResponse } from "next/server";

import { createProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

/** Forwards /api/projects/* to the backend, streaming uploads and ranged video requests through. */
async function proxy(
  request: Request,
  { params }: { params: Promise<{ path?: string[] }> },
) {
  const session = await getServerSession();
  if (!session?.user?.id)
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { path = [] } = await params;
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const forwarded = ["content-type", "accept", "range", "if-range"].flatMap(
    (name) => {
      const value = request.headers.get(name);
      return value ? [[name, value] as [string, string]] : [];
    },
  );
  const upstream = await fetchBackend(
    `/projects${path.length ? `/${path.join("/")}` : ""}${new URL(request.url).search}`,
    {
      method: request.method,
      signal: request.signal,
      userId: session.user.id,
      extraHeaders: Object.fromEntries(forwarded),
      body: hasBody ? request.body : undefined,
      cache: "no-store",
      // Node needs this to send a streamed body.
      ...(hasBody ? { duplex: "half" } : {}),
    } as RequestInit & { userId: string },
  );
  return createProxyResponse(upstream);
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };

import { NextResponse } from "next/server";

import { createTextProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

// What stops this PC from making clips, for the home screen. Checked on this PC only.
export async function GET() {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const upstream = await fetchBackend("/admin/setup-check", { userId: session.user.id, cache: "no-store" });
  return createTextProxyResponse(upstream);
}

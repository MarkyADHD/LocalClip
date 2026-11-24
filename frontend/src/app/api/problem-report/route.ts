import { NextResponse } from "next/server";

import { createTextProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

// The text for Settings > Help > "Report a problem". Read from this PC's logs; nothing is sent anywhere.
export async function GET() {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const upstream = await fetchBackend("/admin/problem-report", { userId: session.user.id, cache: "no-store" });
  return createTextProxyResponse(upstream);
}

"use client";

import { useEffect, useRef } from "react";

import { useSession } from "@/lib/auth-client";

/** Signs into LocalClip's built-in account (see /api/local-session) so there's no login screen. */
export function LocalAutoSignIn() {
  const { data, isPending } = useSession();
  const started = useRef(false);

  useEffect(() => {
    if (isPending || data?.user || started.current) return;
    started.current = true;
    fetch("/api/local-session", { method: "POST" }).then((response) => {
      if (response.ok) window.location.reload();
    });
  }, [data, isPending]);

  return null;
}

"use client";

import dynamic from "next/dynamic";

import { useSession } from "@/lib/auth-client";

const HomeApp = dynamic(() => import("@/components/home-app"), {
  ssr: false,
});

// LocalClip signs in on its own (LocalAutoSignIn); show nothing until it has.
export function HomeRouter() {
  const { data: session, isPending } = useSession();
  return !isPending && session?.user ? <HomeApp /> : null;
}

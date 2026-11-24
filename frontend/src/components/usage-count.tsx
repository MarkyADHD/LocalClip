"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

/** true = counted, false = not counted, null = not asked yet, undefined = still loading. */
function useUsageCount() {
  const [enabled, setEnabled] = useState<boolean | null | undefined>(undefined);
  useEffect(() => {
    fetch("/api/usage-count", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => data && setEnabled(data.enabled))
      .catch(() => {});
  }, []);
  const choose = (next: boolean) => {
    setEnabled(next);
    void fetch("/api/usage-count", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: next }) });
  };
  return [enabled, choose] as const;
}

const WHAT_IS_SENT = "It adds 1 to a public counter once a month. No ID, nothing about you, your PC or your videos.";

/** Settings > Privacy. */
export function UsageCountSwitch() {
  const [enabled, choose] = useUsageCount();
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <Label htmlFor="usage-count" className="text-sm">Count me as a LocalClip user</Label>
        <p className="mt-1 text-xs text-muted-foreground">{WHAT_IS_SENT}</p>
      </div>
      <Switch id="usage-count" checked={enabled === true} disabled={enabled === undefined} onCheckedChange={choose} />
    </div>
  );
}

/** Asked once, until the user picks either answer. */
export function UsageCountPrompt() {
  const [enabled, choose] = useUsageCount();
  if (enabled !== null) return null;
  return (
    <div role="region" aria-label="Count me as a LocalClip user?"
      className="fixed inset-x-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-40 mx-auto max-w-sm rounded-2xl border bg-popover p-4 shadow-lg md:inset-x-auto md:bottom-6 md:right-6">
      <p className="text-sm font-semibold">Count me as a LocalClip user?</p>
      <p className="mt-1 text-xs text-muted-foreground">
        LocalClip is free and has no accounts, so Marky can&apos;t tell how many people use it. {WHAT_IS_SENT} You can change this in Settings.
      </p>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => choose(false)}>No thanks</Button>
        <Button size="sm" onClick={() => choose(true)}>Count me</Button>
      </div>
    </div>
  );
}

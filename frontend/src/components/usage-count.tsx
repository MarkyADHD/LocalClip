"use client";

import { useEffect, useState } from "react";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

/** true = counted, false = not counted, undefined = still loading. */
function useUsageCount() {
  const [enabled, setEnabled] = useState<boolean | undefined>(undefined);
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

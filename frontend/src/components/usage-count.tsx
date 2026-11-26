"use client";

import { useEffect, useState } from "react";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

/** An on/off setting kept by the backend at `/api/<name>` ({enabled}); undefined while loading. */
function useSetting(name: string) {
  const [enabled, setEnabled] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    fetch(`/api/${name}`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => data && setEnabled(data.enabled))
      .catch(() => {});
  }, [name]);
  const choose = (next: boolean) => {
    setEnabled(next);
    void fetch(`/api/${name}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: next }) });
  };
  return [enabled, choose] as const;
}

function SettingSwitch({ name, label, hint }: { name: string; label: string; hint: string }) {
  const [enabled, choose] = useSetting(name);
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <Label htmlFor={name} className="text-sm">{label}</Label>
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      </div>
      <Switch id={name} checked={enabled === true} disabled={enabled === undefined} onCheckedChange={choose} />
    </div>
  );
}

const WHAT_IS_SENT = "It adds 1 to a public counter once a month. No ID, nothing about you, your PC or your videos.";

/** Settings > Privacy. */
export const UsageCountSwitch = () => (
  <SettingSwitch name="usage-count" label="Count me as a LocalClip user" hint={WHAT_IS_SENT} />
);

/** Settings > Auto-blur. */
export const AutoBlurSwitch = () => (
  <SettingSwitch
    name="auto-blur"
    label="Blur vapes and nudity in new clips"
    hint="Looks for a vape in your hand and nudity in the game, on this PC, and blurs just that spot while it's on screen. Remove a wrong blur in the clip editor."
  />
);

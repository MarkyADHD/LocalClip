"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Loader2, Twitch } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { TwitchCode, useTwitchLogin } from "@/components/twitch-vod-picker";

// The Twitch clip made from a clip, so coming back to it shows its link instead of making another.
const stored = (clipId: string) => `localclip-twitch-clip:${clipId}`;

function readStored(clipId: string): string | null {
  try {
    return localStorage.getItem(stored(clipId));
  } catch {
    return null;
  }
}

/** Make a clip from a Twitch VOD a real Twitch clip too, logging in with Twitch first when needed. Key it by clip. */
export function ClipOnTwitch({ taskId, clipId }: { taskId: string; clipId: string }) {
  const [made, setMade] = useState(() => readStored(clipId));
  const [busy, setBusy] = useState(false);

  const clipOnTwitch = async () => {
    setBusy(true);
    try {
      const response = await fetch(`/api/tasks/${taskId}/clips/${clipId}/twitch-clip`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || body.error || "Twitch did not make the clip");
      if (body.need_login) {
        await twitch.start(); // once approved, clipOnTwitch runs again
        return;
      }
      setMade(body.url);
      try {
        localStorage.setItem(stored(clipId), body.url);
      } catch {
        // Storage blocked: the link still shows until another clip is opened.
      }
      toast.success(body.duration < 60 ? "Clipped on Twitch" : "Clipped on Twitch: its first minute, Twitch's longest clip");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Twitch did not make the clip");
    } finally {
      setBusy(false);
    }
  };
  const twitch = useTwitchLogin(() => void clipOnTwitch(), (message) => toast.error(message));
  const { cancel } = twitch;
  useEffect(() => cancel, [cancel]); // the preview closed or moved on

  if (made) {
    return (
      <a href={made} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-[#a970ff] hover:underline">
        <Twitch className="size-3.5" />Twitch clip<ExternalLink className="size-3" />
      </a>
    );
  }
  return (
    <Popover open={twitch.login !== null} onOpenChange={(open) => { if (!open) cancel(); }}>
      <PopoverAnchor asChild>
        <Button size="sm" onClick={() => void clipOnTwitch()} disabled={busy || twitch.login !== null} className="h-7 bg-[#9146FF] text-xs text-white hover:bg-[#7d2ff7]">
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Twitch className="size-3.5" />}Clip on Twitch
        </Button>
      </PopoverAnchor>
      <PopoverContent align="start" className="w-80">{twitch.login && <TwitchCode login={twitch.login} />}</PopoverContent>
    </Popover>
  );
}

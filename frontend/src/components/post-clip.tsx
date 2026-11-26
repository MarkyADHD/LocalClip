"use client";

import { useEffect, useState } from "react";
import { ExternalLink, FolderOpen, Loader2, Send, Sparkles, Twitch } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { TwitchCode, useTwitchLogin } from "@/components/twitch-vod-picker";

export interface PostableClip {
  id: string;
  clip_order: number;
  hook_title: string | null;
  hashtags?: string[];
}

// No ?query in these links: desktop apps before 1.6.1 open File Explorer for a link that has one.
export const UPLOAD_PAGES = [
  { name: "YouTube", key: "youtube", url: "https://www.youtube.com/upload", label: "Title", max: 100 },
  { name: "TikTok", key: "tiktok", url: "https://www.tiktok.com/tiktokstudio/upload", label: "Caption", max: 2200 },
  { name: "Instagram", key: "instagram", url: "https://www.instagram.com/", label: "Caption", max: 2200 },
] as const;

type SiteKey = (typeof UPLOAD_PAGES)[number]["key"];
type Captions = Record<SiteKey, string>;

// AI-written and edited captions stay with the clip on this PC, so reopening the window does not ask the model again.
const stored = (clipId: string) => `localclip-post-captions:${clipId}`;

function readStored(clipId: string): Captions | null {
  try {
    const saved = JSON.parse(localStorage.getItem(stored(clipId)) ?? "null");
    return saved && UPLOAD_PAGES.every((site) => typeof saved[site.key] === "string") ? saved : null;
  } catch {
    return null;
  }
}

// The Twitch clip made from a clip, so reopening the window shows its link instead of making another.
const twitchStored = (clipId: string) => `localclip-twitch-clip:${clipId}`;

function readTwitchClip(clipId: string): string | null {
  try {
    return localStorage.getItem(twitchStored(clipId));
  } catch {
    return null;
  }
}

export function clipCaption(clip: PostableClip) {
  const name = clip.hook_title || `Clip ${clip.clip_order}`;
  return [name, (clip.hashtags ?? []).map((tag) => `#${tag}`).join(" ")].filter(Boolean).join(" ");
}

/** Post one finished clip: caption on the clipboard, the file selected in File Explorer, the site's upload page open. */
export function PostClipDialog({ clip, taskId, twitchVod = false, onClose }: {
  clip: PostableClip | null;
  taskId: string;
  /** The generation's source is a Twitch VOD, so the clip can also be made a Twitch clip. */
  twitchVod?: boolean;
  onClose: () => void;
}) {
  const [captions, setCaptions] = useState<Captions>({ youtube: "", tiktok: "", instagram: "" });
  const [tab, setTab] = useState<SiteKey>("youtube");
  const [writing, setWriting] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filePath, setFilePath] = useState<string | null>(null);
  const [twitchClip, setTwitchClip] = useState<string | null>(null);
  const clipId = clip?.id;

  useEffect(() => {
    if (!clip) return;
    const plain = clipCaption(clip);
    setCaptions(readStored(clip.id) ?? { youtube: plain.slice(0, 100), tiktok: plain, instagram: plain });
    setTab("youtube");
    setFilePath(null);
    setError(null);
    setTwitchClip(readTwitchClip(clip.id));
    // Only when another clip is opened: typing must not be overwritten.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipId]);

  const keep = (next: Captions) => {
    setCaptions(next);
    try {
      if (clipId) localStorage.setItem(stored(clipId), JSON.stringify(next));
    } catch {
      // Storage full or blocked: the captions still work until the window closes.
    }
  };

  const writeWithAi = async () => {
    setWriting(true);
    setError(null);
    try {
      const response = await fetch(`/api/tasks/${taskId}/clips/${clipId}/captions`, { method: "POST" });
      const written = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(written.detail || written.error || "The AI model could not answer");
      keep({ youtube: written.youtube, tiktok: written.tiktok, instagram: written.instagram });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setWriting(false);
    }
  };

  const open = async (site: (typeof UPLOAD_PAGES)[number]) => {
    window.open(site.url, "_blank", "noopener"); // first, while the click still counts as the user's
    setTab(site.key);
    setBusy(site.name);
    setError(null);
    try {
      await navigator.clipboard.writeText(captions[site.key]).catch(() => undefined);
      const response = await fetch(`/api/tasks/${taskId}/clips/${clipId}/reveal`, { method: "POST" });
      const shown = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(shown.detail || shown.error || "Could not find the clip's file");
      setFilePath(shown.path);
      toast.success(shown.revealed ? `${site.name} caption copied. Drag the clip from the folder onto ${site.name}.` : `${site.name} caption copied.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(null);
    }
  };

  const clipOnTwitch = async () => {
    setBusy("Twitch");
    setError(null);
    try {
      const response = await fetch(`/api/tasks/${taskId}/clips/${clipId}/twitch-clip`, { method: "POST" });
      const made = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(made.detail || made.error || "Twitch did not make the clip");
      if (made.need_login) {
        await twitch.start(); // once approved, clipOnTwitch runs again
        return;
      }
      setTwitchClip(made.url);
      try {
        if (clipId) localStorage.setItem(twitchStored(clipId), made.url);
      } catch {
        // Storage blocked: the link still shows until the window closes.
      }
      toast.success(made.duration < 60 ? "Clipped on Twitch" : "Clipped on Twitch: its first minute, Twitch's longest clip");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(null);
    }
  };
  const twitch = useTwitchLogin(() => void clipOnTwitch(), setError);
  const { cancel: cancelTwitchLogin } = twitch;
  useEffect(() => cancelTwitchLogin, [clipId, cancelTwitchLogin]); // another clip, or the window closed

  const site = UPLOAD_PAGES.find((page) => page.key === tab) ?? UPLOAD_PAGES[0];

  return (
    <Dialog open={clip !== null} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Send className="size-4" />Post this clip</DialogTitle>
          <DialogDescription>
            Each site has its own caption. A button copies that site&apos;s caption, shows the clip&apos;s file in its folder and opens the upload page. Drag the file in and paste the caption.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Tabs value={tab} onValueChange={(value) => setTab(value as SiteKey)}>
              <TabsList>
                {UPLOAD_PAGES.map((page) => <TabsTrigger key={page.key} value={page.key}>{page.name}</TabsTrigger>)}
              </TabsList>
            </Tabs>
            <Button size="sm" onClick={() => void writeWithAi()} disabled={writing}>
              {writing ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              {writing ? "Writing..." : "Write with AI"}
            </Button>
          </div>
          <div className="flex items-baseline justify-between">
            <Label htmlFor="post-caption">{site.name} {site.label.toLowerCase()}</Label>
            <span className="text-xs text-muted-foreground">{captions[tab].length}/{site.max}</span>
          </div>
          <Textarea
            id="post-caption"
            rows={5}
            maxLength={site.max}
            value={captions[tab]}
            disabled={writing}
            onChange={(event) => keep({ ...captions, [tab]: event.target.value })}
          />
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex flex-wrap gap-2">
          {UPLOAD_PAGES.map((page) => (
            <Button key={page.name} variant="outline" onClick={() => void open(page)} disabled={busy !== null}>
              {busy === page.name ? <Loader2 className="size-4 animate-spin" /> : <FolderOpen className="size-4" />}Open {page.name}
            </Button>
          ))}
        </div>
        {filePath && <p className="break-all text-xs text-muted-foreground">File: {filePath}</p>}
        {twitchVod && (
          <div className="space-y-2 border-t pt-3">
            {twitch.login ? (
              <TwitchCode login={twitch.login} />
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={() => void clipOnTwitch()} disabled={busy !== null} className="bg-[#9146FF] text-white hover:bg-[#7d2ff7]">
                  {busy === "Twitch" ? <Loader2 className="size-4 animate-spin" /> : <Twitch className="size-4" />}Clip on Twitch
                </Button>
                {twitchClip ? (
                  <a href={twitchClip} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm underline underline-offset-4">
                    Your Twitch clip<ExternalLink className="size-3.5" />
                  </a>
                ) : (
                  <span className="text-xs text-muted-foreground">Makes the same moment a clip on your Twitch channel (up to 60 s).</span>
                )}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

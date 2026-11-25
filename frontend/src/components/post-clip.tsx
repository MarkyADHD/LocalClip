"use client";

import { useEffect, useState } from "react";
import { FolderOpen, Loader2, Send } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export interface PostableClip {
  id: string;
  clip_order: number;
  hook_title: string | null;
  hashtags?: string[];
}

// No ?query in these links: desktop apps before 1.6.1 open File Explorer for a link that has one.
export const UPLOAD_PAGES = [
  { name: "YouTube", url: "https://www.youtube.com/upload" },
  { name: "TikTok", url: "https://www.tiktok.com/tiktokstudio/upload" },
  { name: "Instagram", url: "https://www.instagram.com/" },
];

export function clipCaption(clip: PostableClip) {
  const name = clip.hook_title || `Clip ${clip.clip_order}`;
  return [name, (clip.hashtags ?? []).map((tag) => `#${tag}`).join(" ")].filter(Boolean).join(" ");
}

/** Post one finished clip: caption on the clipboard, the file selected in File Explorer, the site's upload page open. */
export function PostClipDialog({ clip, taskId, onClose }: { clip: PostableClip | null; taskId: string; onClose: () => void }) {
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filePath, setFilePath] = useState<string | null>(null);
  const clipId = clip?.id;

  useEffect(() => {
    if (!clip) return;
    setCaption(clipCaption(clip));
    setFilePath(null);
    setError(null);
    // Only when another clip is opened: typing must not be overwritten.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipId]);

  const open = async (site: (typeof UPLOAD_PAGES)[number]) => {
    window.open(site.url, "_blank", "noopener"); // first, while the click still counts as the user's
    setBusy(site.name);
    setError(null);
    try {
      await navigator.clipboard.writeText(caption).catch(() => undefined);
      const response = await fetch(`/api/tasks/${taskId}/clips/${clipId}/reveal`, { method: "POST" });
      const shown = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(shown.detail || shown.error || "Could not find the clip's file");
      setFilePath(shown.path);
      toast.success(shown.revealed ? `Caption copied. Drag the clip from the folder onto ${site.name}.` : "Caption copied.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog open={clip !== null} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Send className="size-4" />Post this clip</DialogTitle>
          <DialogDescription>
            Copies the caption, shows the clip&apos;s file in its folder and opens the upload page. Drag the file in and paste the caption.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="post-caption">Caption</Label>
          <Textarea id="post-caption" rows={4} maxLength={2200} value={caption} onChange={(event) => setCaption(event.target.value)} />
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex flex-wrap gap-2">
          {UPLOAD_PAGES.map((site) => (
            <Button key={site.name} variant="outline" onClick={() => void open(site)} disabled={busy !== null}>
              {busy === site.name ? <Loader2 className="size-4 animate-spin" /> : <FolderOpen className="size-4" />}Open {site.name}
            </Button>
          ))}
        </div>
        {filePath && <p className="break-all text-xs text-muted-foreground">File: {filePath}</p>}
      </DialogContent>
    </Dialog>
  );
}

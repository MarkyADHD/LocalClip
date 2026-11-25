"use client";

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, FolderOpen, Loader2, Send } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

export interface PostableClip {
  id: string;
  clip_order: number;
  hook_title: string | null;
  hashtags?: string[];
}

interface YouTubeStatus {
  configured: boolean;
  logged_in: boolean;
  name?: string | null;
}

interface Login {
  user_code: string;
  verification_uri: string;
  interval: number;
}

// No ?query in these links: desktop apps before 1.6.1 open File Explorer for a link that has one.
const UPLOAD_PAGES = [
  { id: "tiktok", name: "TikTok", url: "https://www.tiktok.com/tiktokstudio/upload" },
  { id: "instagram", name: "Instagram", url: "https://www.instagram.com/", hint: "Press Create (+), then Post." },
  { id: "youtube", name: "YouTube", url: "https://www.youtube.com/upload" },
] as const;

async function api<T>(path: string, method: "GET" | "POST" = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/tasks/${path}`, {
    method,
    cache: "no-store",
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || "Request failed");
  return data as T;
}

/** Post one finished clip: straight to YouTube with the user's login, or by opening a site's upload page with the file shown. */
export function PostClipDialog({ clip, taskId, onClose }: { clip: PostableClip | null; taskId: string; onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [privacy, setPrivacy] = useState("public");
  const [youtube, setYoutube] = useState<YouTubeStatus | null>(null);
  const [login, setLogin] = useState<Login | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [postedUrl, setPostedUrl] = useState<string | null>(null);
  const [filePath, setFilePath] = useState<string | null>(null);
  const clipId = clip?.id;

  const run = useCallback(async (name: string, work: () => Promise<void>) => {
    setBusy(name);
    setError(null);
    try {
      await work();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    if (!clip) return;
    const name = clip.hook_title || `Clip ${clip.clip_order}`;
    setTitle(name);
    setCaption([name, (clip.hashtags ?? []).map((tag) => `#${tag}`).join(" ")].filter(Boolean).join(" "));
    setPostedUrl(null);
    setFilePath(null);
    setLogin(null);
    setError(null);
    void api<YouTubeStatus>("post/youtube").then(setYoutube, () => setYoutube({ configured: false, logged_in: false }));
    // Only when another clip is opened: typing must not be overwritten.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipId]);

  // While a code is waiting for approval, ask the backend at Google's pace until it is approved.
  useEffect(() => {
    if (!login) return;
    const timer = setInterval(async () => {
      try {
        const { logged_in } = await api<{ logged_in: boolean }>("post/youtube/login/poll", "POST");
        if (logged_in) {
          setLogin(null);
          setYoutube(await api<YouTubeStatus>("post/youtube"));
        }
      } catch (err) {
        setLogin(null);
        setError(err instanceof Error ? err.message : "YouTube login failed");
      }
    }, Math.max(2, login.interval) * 1000);
    return () => clearInterval(timer);
  }, [login]);

  const startLogin = () => run("login", async () => {
    const started = await api<Login>("post/youtube/login", "POST");
    setLogin(started);
    window.open(started.verification_uri, "_blank", "noopener");
  });

  const postToYouTube = () => run("youtube", async () => {
    try {
      const posted = await api<{ url: string }>(`${taskId}/clips/${clipId}/post/youtube`, "POST", { title, description: caption, privacy });
      setPostedUrl(posted.url);
      toast.success("Posted to YouTube");
    } finally {
      setYoutube(await api<YouTubeStatus>("post/youtube")); // an expired login shows the login button again
    }
  });

  const logout = () => run("logout", async () => {
    await api("post/youtube/logout", "POST");
    setYoutube((prev) => ({ configured: prev?.configured ?? false, logged_in: false }));
  });

  // The lazy way, for sites with no posting API a desktop app can use: caption on the clipboard,
  // the file selected in File Explorer, the site's upload page open.
  const openUploadPage = (site: (typeof UPLOAD_PAGES)[number]) => {
    window.open(site.url, "_blank", "noopener"); // first, while the click still counts as the user's
    void run(site.id, async () => {
      await navigator.clipboard.writeText(caption).catch(() => undefined);
      const shown = await api<{ revealed: boolean; path: string }>(`${taskId}/clips/${clipId}/reveal`, "POST");
      setFilePath(shown.path);
      toast.success(shown.revealed ? `Caption copied. Drag the clip from the folder onto ${site.name}.` : "Caption copied.");
    });
  };

  const youtubeDirect = youtube?.configured;
  const pages = UPLOAD_PAGES.filter((site) => site.id !== "youtube" || !youtubeDirect);

  return (
    <Dialog open={clip !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Send className="size-4" />Post this clip</DialogTitle>
          <DialogDescription>Nothing is posted until you press a button here.</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="post-title">Title (YouTube)</Label>
            <Input id="post-title" maxLength={100} value={title} onChange={(event) => setTitle(event.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="post-caption">Caption</Label>
            <Textarea id="post-caption" rows={4} maxLength={2200} value={caption} onChange={(event) => setCaption(event.target.value)} />
          </div>
        </div>

        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

        {youtubeDirect && (
          <section className="space-y-3 rounded-xl border p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">YouTube Shorts</h3>
              {youtube.logged_in && (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  {youtube.name}
                  <Button variant="ghost" size="sm" className="h-6 px-1.5 text-xs" onClick={logout} disabled={busy !== null}>Log out</Button>
                </span>
              )}
            </div>
            {login ? (
              <div className="flex flex-col items-center gap-2 text-center">
                <p className="text-sm text-muted-foreground">Enter this code on the Google page that just opened, then allow LocalClip:</p>
                <p className="rounded-lg border bg-muted px-4 py-2 font-mono text-2xl font-semibold tracking-widest">{login.user_code}</p>
                <a href={login.verification_uri} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm underline underline-offset-4">
                  Open the Google page again<ExternalLink className="size-3.5" />
                </a>
                <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />Waiting for approval</p>
              </div>
            ) : !youtube.logged_in ? (
              <Button onClick={startLogin} disabled={busy !== null}>
                {busy === "login" && <Loader2 className="size-4 animate-spin" />}Log in to YouTube
              </Button>
            ) : postedUrl ? (
              <a href={postedUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-medium underline underline-offset-4">
                Posted. Open it on YouTube<ExternalLink className="size-3.5" />
              </a>
            ) : (
              <div className="flex items-center gap-2">
                <Select value={privacy} onValueChange={setPrivacy}>
                  <SelectTrigger aria-label="Who can see it" className="w-32"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="public">Public</SelectItem>
                    <SelectItem value="unlisted">Unlisted</SelectItem>
                    <SelectItem value="private">Private</SelectItem>
                  </SelectContent>
                </Select>
                <Button onClick={postToYouTube} disabled={busy !== null || !title.trim()}>
                  {busy === "youtube" ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                  {busy === "youtube" ? "Uploading" : "Post to YouTube"}
                </Button>
              </div>
            )}
          </section>
        )}

        <section className="space-y-3 rounded-xl border p-4">
          <div>
            <h3 className="text-sm font-semibold">{pages.map((site) => site.name).join(" and ")}</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Copies the caption, shows the clip&apos;s file in its folder and opens the upload page. Drag the file in and paste the caption.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {pages.map((site) => (
              <Button key={site.id} variant="outline" onClick={() => openUploadPage(site)} disabled={busy !== null} title={"hint" in site ? site.hint : undefined}>
                {busy === site.id ? <Loader2 className="size-4 animate-spin" /> : <FolderOpen className="size-4" />}Open {site.name}
              </Button>
            ))}
          </div>
          {filePath && <p className="break-all text-xs text-muted-foreground">File: {filePath}</p>}
        </section>
      </DialogContent>
    </Dialog>
  );
}

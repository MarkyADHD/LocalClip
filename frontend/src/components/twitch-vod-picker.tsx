"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, Loader2, Twitch } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface Vod {
  id: string;
  title: string;
  url: string;
  thumbnail: string;
  duration: string;
  created_at: string;
  type: string;
}

interface Listing {
  configured: boolean;
  logged_in: boolean;
  name?: string;
  vods?: Vod[];
  cursor?: string | null;
}

interface Login {
  user_code: string;
  verification_uri: string;
  interval: number;
}

async function api<T>(path: string, method: "GET" | "POST" = "GET"): Promise<T> {
  const response = await fetch(`/api/tasks/twitch/${path}`, { method, cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.error || "Twitch request failed");
  return body as T;
}

/** Log in with Twitch (device code) and pick one of your own VODs; `onPick` gets its link. */
export function TwitchVodPicker({ open, onOpenChange, onPick }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (url: string) => void;
}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [login, setLogin] = useState<Login | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const openRef = useRef(open);
  openRef.current = open;

  const run = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Twitch request failed");
    } finally {
      setBusy(false);
    }
  }, []);

  const load = useCallback(() => run(async () => setListing(await api<Listing>("vods"))), [run]);

  useEffect(() => {
    if (open) void load();
    else setLogin(null);
  }, [open, load]);

  // While a code is waiting for approval, ask the backend at Twitch's pace until it is approved.
  useEffect(() => {
    if (!login) return;
    const timer = setInterval(async () => {
      try {
        const { logged_in } = await api<{ logged_in: boolean }>("login/poll", "POST");
        if (logged_in && openRef.current) {
          setLogin(null);
          void load();
        }
      } catch (err) {
        setLogin(null);
        setError(err instanceof Error ? err.message : "Twitch login failed");
      }
    }, Math.max(2, login.interval) * 1000);
    return () => clearInterval(timer);
  }, [login, load]);

  const startLogin = () => run(async () => {
    const started = await api<Login>("login", "POST");
    setLogin(started);
    window.open(started.verification_uri, "_blank", "noopener");
  });

  const more = () => run(async () => {
    const next = await api<Listing>(`vods?after=${encodeURIComponent(listing?.cursor ?? "")}`);
    setListing((prev) => ({ ...next, vods: [...(prev?.vods ?? []), ...(next.vods ?? [])] }));
  });

  const logout = () => run(async () => {
    await api("logout", "POST");
    setListing({ configured: true, logged_in: false });
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Twitch className="size-5" />Your Twitch VODs</DialogTitle>
          <DialogDescription>
            {listing?.logged_in ? `Logged in as ${listing.name}. Pick a stream to clip.` : "Log in to pick one of your past streams."}
          </DialogDescription>
        </DialogHeader>

        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

        {!listing ? (
          <div className="flex justify-center py-10"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
        ) : !listing.configured ? (
          <p className="py-6 text-sm text-muted-foreground">Twitch login is not set up in this build yet (no TWITCH_CLIENT_ID).</p>
        ) : login ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <p className="text-sm text-muted-foreground">Approve LocalClip in the Twitch page that just opened. If it asks for a code, enter:</p>
            <p className="rounded-lg border bg-muted px-4 py-2 font-mono text-2xl font-semibold tracking-widest">{login.user_code}</p>
            <a href={login.verification_uri} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm underline underline-offset-4">
              Open the Twitch page again<ExternalLink className="size-3.5" />
            </a>
            <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />Waiting for approval</p>
          </div>
        ) : !listing.logged_in ? (
          <div className="flex justify-center py-8">
            <Button onClick={startLogin} disabled={busy} className="bg-[#9146FF] text-white hover:bg-[#7d2ff7]">
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Twitch className="size-4" />}Log in with Twitch
            </Button>
          </div>
        ) : (
          <>
            {listing.vods?.length ? (
              <ul className="grid max-h-[60vh] grid-cols-2 gap-3 overflow-y-auto pr-1 sm:grid-cols-3">
                {listing.vods.map((vod) => (
                  <li key={vod.id}>
                    <button
                      type="button"
                      onClick={() => { onPick(vod.url); onOpenChange(false); }}
                      className="group w-full rounded-lg border bg-card p-1.5 text-left transition-colors hover:border-foreground/40 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <span className="relative block aspect-video overflow-hidden rounded-md bg-muted">
                        {vod.thumbnail && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={vod.thumbnail} alt="" loading="lazy" className="size-full object-cover" />
                        )}
                        <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 text-[11px] font-medium text-white">{vod.duration}</span>
                      </span>
                      <span className="mt-1.5 block truncate text-sm font-medium">{vod.title}</span>
                      <span className="block text-xs text-muted-foreground">
                        {vod.created_at ? new Date(vod.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : ""}
                        {vod.type !== "archive" ? ` · ${vod.type}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-6 text-sm text-muted-foreground">No videos on this channel. Twitch only keeps past streams if Store past broadcasts is on, and deletes them after 7 to 60 days.</p>
            )}
            <div className="flex items-center justify-between">
              <Button variant="ghost" size="sm" onClick={logout} disabled={busy}>Log out of Twitch</Button>
              {listing.cursor && <Button variant="outline" size="sm" onClick={more} disabled={busy}>{busy && <Loader2 className="size-4 animate-spin" />}Load more</Button>}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

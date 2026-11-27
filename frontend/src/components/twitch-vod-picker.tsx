"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, Loader2, Twitch } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface Vod {
  id: string;
  title: string;
  url: string;
  thumbnail: string;
  duration: string;
  created_at: string;
  type: string;
}

interface TwitchClip {
  id: string;
  title: string;
  url: string;
  thumbnail: string;
  duration: number;
  created_at: string;
  views: number;
  creator: string;
}

interface Listing {
  configured: boolean;
  logged_in: boolean;
  name?: string;
  vods?: Vod[];
  clips?: TwitchClip[];
  cursor?: string | null;
}

type Kind = "vods" | "clips";

/** One grid tile, a stream or a clip. */
interface Item {
  id: string;
  url: string;
  title: string;
  thumbnail: string;
  badge: string;
  meta: string;
}

const day = (iso: string) => iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";

function items(listing: Listing): Item[] {
  return [
    ...(listing.vods ?? []).map((vod) => ({
      id: vod.id, url: vod.url, title: vod.title, thumbnail: vod.thumbnail, badge: vod.duration,
      meta: day(vod.created_at) + (vod.type !== "archive" ? ` · ${vod.type}` : ""),
    })),
    ...(listing.clips ?? []).map((clip) => ({
      id: clip.id, url: clip.url, title: clip.title, thumbnail: clip.thumbnail, badge: `${Math.round(clip.duration)}s`,
      meta: `${clip.views.toLocaleString()} views · ${day(clip.created_at)}`,
    })),
  ];
}

export interface Login {
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

/** Twitch's device code login: `start` opens Twitch's page and polls at Twitch's pace until the code is approved. */
export function useTwitchLogin(onApproved: () => void, onError: (message: string) => void) {
  const [login, setLogin] = useState<Login | null>(null);
  const approved = useRef(onApproved);
  approved.current = onApproved;
  const failed = useRef(onError);
  failed.current = onError;

  useEffect(() => {
    if (!login) return;
    const timer = setInterval(async () => {
      try {
        const { logged_in } = await api<{ logged_in: boolean }>("login/poll", "POST");
        if (logged_in) {
          setLogin(null);
          approved.current();
        }
      } catch (err) {
        setLogin(null);
        failed.current(err instanceof Error ? err.message : "Twitch login failed");
      }
    }, Math.max(2, login.interval) * 1000);
    return () => clearInterval(timer);
  }, [login]);

  const start = useCallback(async () => {
    const started = await api<Login>("login", "POST");
    // Without Twitch's ?device-code=: desktop apps before 1.6.1 open File Explorer for a link with a query.
    started.verification_uri = started.verification_uri.split("?")[0];
    setLogin(started);
    window.open(started.verification_uri, "_blank", "noopener");
  }, []);
  const cancel = useCallback(() => setLogin(null), []);
  return { login, start, cancel };
}

/** The code to type on Twitch's page while a login waits for approval. */
export function TwitchCode({ login }: { login: Login }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <p className="text-sm text-muted-foreground">Enter this code on the Twitch page that just opened, then approve LocalClip:</p>
      <p className="rounded-lg border bg-muted px-4 py-2 font-mono text-2xl font-semibold tracking-widest">{login.user_code}</p>
      <a href={login.verification_uri} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm underline underline-offset-4">
        Open the Twitch page again<ExternalLink className="size-3.5" />
      </a>
      <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />Waiting for approval</p>
    </div>
  );
}

/** Log in with Twitch (device code) and pick one of your own VODs or clips; `onPick` gets its link.
 * A VOD brings the clips viewers made from it along with the AI's picks; a clip is imported whole to edit. */
export function TwitchVodPicker({ open, onOpenChange, onPick }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (url: string) => void;
}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [kind, setKind] = useState<Kind>("vods");
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

  const load = useCallback(() => run(async () => setListing(await api<Listing>(kind))), [run, kind]);
  const twitch = useTwitchLogin(() => { if (openRef.current) void load(); }, setError);
  const { login, cancel } = twitch;

  useEffect(() => {
    if (open) void load();
    else cancel();
  }, [open, load, cancel]);

  const startLogin = () => run(twitch.start);

  const more = () => run(async () => {
    const next = await api<Listing>(`${kind}?after=${encodeURIComponent(listing?.cursor ?? "")}`);
    setListing((prev) => ({ ...next, [kind]: [...(prev?.[kind] ?? []), ...(next[kind] ?? [])] }));
  });

  const logout = () => run(async () => {
    await api("logout", "POST");
    setListing({ configured: true, logged_in: false });
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Twitch className="size-5" />Your Twitch videos</DialogTitle>
          <DialogDescription>
            {!listing?.logged_in
              ? "Log in to pick one of your past streams or clips."
              : kind === "vods"
                ? `Logged in as ${listing.name}. Pick a stream: the clips viewers made from it come along with the AI's picks.`
                : `Logged in as ${listing.name}. Pick a clip to bring it in whole and edit it.`}
          </DialogDescription>
        </DialogHeader>

        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

        {!listing ? (
          <div className="flex justify-center py-10"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
        ) : !listing.configured ? (
          <p className="py-6 text-sm text-muted-foreground">Twitch login is not set up in this build yet (no TWITCH_CLIENT_ID).</p>
        ) : login ? (
          <TwitchCode login={login} />
        ) : !listing.logged_in ? (
          <div className="flex justify-center py-8">
            <Button onClick={startLogin} disabled={busy} className="bg-[#9146FF] text-white hover:bg-[#7d2ff7]">
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Twitch className="size-4" />}Log in with Twitch
            </Button>
          </div>
        ) : (
          <>
            <Tabs value={kind} onValueChange={(value) => { setBusy(true); setListing({ ...listing, vods: undefined, clips: undefined, cursor: null }); setKind(value as Kind); }}>
              <TabsList>
                <TabsTrigger value="vods">Streams</TabsTrigger>
                <TabsTrigger value="clips">Clips</TabsTrigger>
              </TabsList>
            </Tabs>
            {items(listing).length ? (
              <ul className="grid max-h-[60vh] grid-cols-2 gap-3 overflow-y-auto pr-1 sm:grid-cols-3">
                {items(listing).map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => { onPick(item.url); onOpenChange(false); }}
                      className="group w-full rounded-lg border bg-card p-1.5 text-left transition-colors hover:border-foreground/40 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <span className="relative block aspect-video overflow-hidden rounded-md bg-muted">
                        {item.thumbnail && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={item.thumbnail} alt="" loading="lazy" className="size-full object-cover" />
                        )}
                        <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 text-[11px] font-medium text-white">{item.badge}</span>
                      </span>
                      <span className="mt-1.5 block truncate text-sm font-medium">{item.title}</span>
                      <span className="block text-xs text-muted-foreground">{item.meta}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : busy ? (
              <div className="flex justify-center py-10"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
            ) : kind === "clips" ? (
              <p className="py-6 text-sm text-muted-foreground">No clips on this channel yet. You can also paste any Twitch clip link.</p>
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

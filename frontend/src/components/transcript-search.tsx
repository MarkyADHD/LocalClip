"use client";

import { useState } from "react";
import { Loader2, Scissors, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiRequestError, parseApiError } from "@/lib/api-error";

type Hit = { start: number; end: number; label: string; text: string };

/** Seconds kept before and after the phrase: the setup usually comes first, the reaction right after. */
export const CLIP_BEFORE = 20;
export const CLIP_AFTER = 10;

export const clipRange = (hit: Pick<Hit, "start" | "end">) => ({
  start: Math.max(0, hit.start - CLIP_BEFORE),
  end: hit.end + CLIP_AFTER,
});

/** "Search the stream" on a finished generation: find a phrase in the transcript and clip around it. */
export function TranscriptSearch({
  taskId,
  disabled,
  onClip,
}: {
  taskId: string;
  disabled?: boolean;
  /** Queue a clip of this part of the video (seconds); resolves once it is queued. */
  onClip: (range: { start: number; end: number }) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`/api/tasks/${taskId}/transcript/search?q=${encodeURIComponent(query.trim())}`, { cache: "no-store" });
      if (!response.ok) throw new ApiRequestError(await parseApiError(response, "Could not search this video."));
      setHits((await response.json()).hits);
    } catch (error) {
      setHits(null);
      setMessage(error instanceof Error ? error.message : "Could not search this video.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" disabled={disabled}>
          <Search className="size-4" /><span className="hidden sm:inline">Search the stream</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Search the stream</DialogTitle>
          <DialogDescription>
            Type something that was said. Clipping a result makes a new clip from {CLIP_BEFORE} seconds before it to {CLIP_AFTER} seconds after.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={search} className="flex gap-2">
          <Input autoFocus aria-label="Words to find" placeholder="no way, clip that, let's go..." value={query} onChange={(event) => setQuery(event.target.value)} />
          <Button type="submit" disabled={busy || !query.trim()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}Search
          </Button>
        </form>
        {message && <p className="text-sm text-destructive">{message}</p>}
        {hits?.length === 0 && <p className="text-sm text-muted-foreground">Nobody said that in this video. Try fewer words.</p>}
        {!!hits?.length && (
          <ul aria-label="Search results" className="max-h-[50vh] space-y-1 overflow-y-auto">
            {hits.map((hit) => (
              <li key={`${hit.start}-${hit.end}`} className="flex items-center gap-3 rounded-lg border bg-card p-2 text-sm">
                <span className="w-14 shrink-0 font-mono text-xs text-muted-foreground">{hit.label}</span>
                <span className="min-w-0 flex-1">{hit.text}</span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  aria-label={`Clip the moment at ${hit.label}`}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await onClip(clipRange(hit));
                      setOpen(false);
                    } catch (error) {
                      setMessage(error instanceof Error ? error.message : "Could not start the clip.");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <Scissors className="size-4" />Clip this
                </Button>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}

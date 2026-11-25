"use client";

import { useState } from "react";
import { Copy, FolderOpen, Loader2, PackageCheck, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { clipCaption, UPLOAD_PAGES, type PostableClip } from "@/components/post-clip";

async function post(url: string) {
  const response = await fetch(url, { method: "POST" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.error || "Request failed");
  return body;
}

/** The bar shown while clips are ticked: copies them all into one folder, then helps post them. */
export function BatchExportBar({ clips, taskId, preset, onClear }: {
  clips: PostableClip[];
  taskId: string;
  preset: string;
  onClear: () => void;
}) {
  const [done, setDone] = useState<number | null>(null); // clips finished so far, null when idle
  const [result, setResult] = useState<{ folder: string; exported: PostableClip[]; failed: string[] } | null>(null);

  const openFolder = () => post(`/api/tasks/${taskId}/export-folder/open`)
    .then((shown) => { if (!shown.opened) toast.info(`Clips are in ${shown.folder}`); })
    .catch((err: Error) => toast.error(err.message));

  const exportAll = async () => {
    const exported: PostableClip[] = [];
    const failed: string[] = [];
    let folder = "";
    // One at a time: a format other than Original re-encodes each clip.
    for (const clip of clips) {
      setDone(exported.length + failed.length);
      try {
        folder = (await post(`/api/tasks/${taskId}/clips/${clip.id}/export-to-folder?preset=${preset}`)).folder;
        exported.push(clip);
      } catch (err) {
        failed.push(`${clip.hook_title || `Clip ${clip.clip_order}`}: ${err instanceof Error ? err.message : "failed"}`);
      }
    }
    setDone(null);
    if (!exported.length) {
      toast.error(`No clips were exported. ${failed[0] ?? ""}`);
      return;
    }
    setResult({ folder, exported, failed });
    void openFolder();
  };

  const copy = (text: string) => navigator.clipboard.writeText(text)
    .then(() => toast.success("Caption copied."), () => toast.error("Could not copy the caption."));

  return (
    <>
      {clips.length > 0 && (
        <div role="region" aria-label="Selected clips"
          className="fixed inset-x-0 bottom-4 z-40 mx-auto flex w-fit max-w-[calc(100vw-2rem)] items-center gap-2 rounded-full border bg-card py-1.5 pl-4 pr-1.5 shadow-xl">
          <span className="text-sm font-medium tabular-nums" aria-live="polite">
            {done === null ? `${clips.length} selected` : `Exporting ${done + 1} of ${clips.length}`}
          </span>
          <Button size="sm" className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" disabled={done !== null} onClick={() => void exportAll()}>
            {done === null ? <PackageCheck className="size-4" /> : <Loader2 className="size-4 animate-spin" />}
            Export {clips.length === 1 ? "clip" : `all ${clips.length}`}
          </Button>
          <Button size="icon-sm" variant="ghost" className="rounded-full" aria-label="Clear selection" disabled={done !== null} onClick={onClear}>
            <X className="size-4" />
          </Button>
        </div>
      )}

      <Dialog open={result !== null} onOpenChange={(isOpen) => { if (!isOpen) { setResult(null); onClear(); } }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <PackageCheck className="size-4" />{result?.exported.length} {result?.exported.length === 1 ? "clip" : "clips"} exported
            </DialogTitle>
            <DialogDescription>
              They are in one folder, numbered and named. Open an upload page, drag the clips in and copy each caption.
            </DialogDescription>
          </DialogHeader>
          <p className="break-all text-xs text-muted-foreground">{result?.folder}</p>
          {result && result.failed.length > 0 && (
            <ul role="alert" className="space-y-0.5 text-sm text-destructive">
              {result.failed.map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void openFolder()}><FolderOpen className="size-4" />Show folder</Button>
            {UPLOAD_PAGES.map((site) => (
              <Button key={site.name} variant="outline" asChild>
                <a href={site.url} target="_blank" rel="noopener">Open {site.name}</a>
              </Button>
            ))}
          </div>
          <ul className="max-h-64 space-y-1 overflow-y-auto">
            {result?.exported.map((clip) => (
              <li key={clip.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5">
                <span className="min-w-0 flex-1 truncate text-sm">
                  <span className="mr-1.5 tabular-nums text-muted-foreground">{String(clip.clip_order).padStart(2, "0")}</span>
                  {clipCaption(clip)}
                </span>
                <Button size="sm" variant="ghost" className="h-7 shrink-0 px-2 text-xs" onClick={() => void copy(clipCaption(clip))}
                  aria-label={`Copy caption for clip ${clip.clip_order}`}>
                  <Copy className="size-3.5" />Copy
                </Button>
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>
    </>
  );
}

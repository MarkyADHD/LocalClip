"use client";
import { useState } from "react";
import { AudioLines, FolderOpen, Image as ImageIcon, Loader2, Plus, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { editorRequest } from "@/components/editor/use-editor";
import { cn } from "@/lib/utils";
import { addAssetClip, timecode, type Asset } from "@/lib/project/document";
import { ASSET_DRAG } from "./timeline";
import type { Project } from "./use-project";

/** The project's files: add them by browsing, pasting a path or link, or dropping them in. */
export function MediaBin({ project, playhead }: { project: Project; playhead: () => number }) {
  const { endpoint, refresh, update, doc } = project;
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  // The Windows picker only exists in the desktop install; elsewhere the path box does the job.
  const [picker, setPicker] = useState(true);

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await work();
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not add that file");
    } finally {
      setBusy(false);
    }
  };
  const addSource = (value: string) => {
    const text = value.trim();
    if (!text) return;
    return run(async () => {
      await editorRequest(`${endpoint}/assets`, "POST", /^https?:\/\//i.test(text) ? { url: text } : { path: text });
      setSource("");
    });
  };
  const browse = () =>
    run(async () => {
      try {
        const { paths } = await editorRequest<{ paths: string[] }>("/api/projects/browse", "POST", {});
        for (const path of paths) await editorRequest(`${endpoint}/assets`, "POST", { path });
      } catch (error) {
        setPicker(false);
        throw error;
      }
    });
  const upload = (files: File[]) =>
    run(async () => {
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        const response = await fetch(`${endpoint}/assets/upload`, { method: "POST", body });
        if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `Could not add ${file.name}`);
      }
    });
  const remove = (asset: Asset) =>
    run(async () => {
      update((d) => ({ ...d, clips: d.clips.filter((c) => c.asset !== asset.id) }));
      await editorRequest(`${endpoint}/assets/${asset.id}`, "DELETE");
    });

  return (
    <div
      className={cn("flex h-full min-h-0 flex-col", over && "ring-2 ring-inset ring-brand")}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        setOver(false);
        if (!event.dataTransfer.files.length) return;
        event.preventDefault();
        void upload([...event.dataTransfer.files]);
      }}
    >
      <div className="space-y-2 border-b p-2">
        {picker && (
          <Button size="sm" className="w-full" disabled={busy} onClick={browse}>
            {busy ? <Loader2 className="animate-spin" /> : <FolderOpen />} Add media
          </Button>
        )}
        <form
          className="flex gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            void addSource(source);
          }}
        >
          <Input
            aria-label="File path or video link"
            placeholder="Paste a file path or link"
            className="h-8 text-xs"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          />
          <Button size="icon-sm" variant="outline" type="submit" aria-label="Add" disabled={busy || !source.trim()}>
            <Plus />
          </Button>
        </form>
      </div>
      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        {!project.assetList.length && (
          <li className="px-2 py-6 text-center text-xs leading-relaxed text-muted-foreground">
            Add a recording to start. Big files are used where they are, nothing is copied. You can also drop pictures,
            music and clips here.
          </li>
        )}
        {project.assetList.map((asset) => {
          const ready = asset.status === "ready";
          return (
            <li
              key={asset.id}
              draggable={ready}
              onDragStart={(event) => {
                event.dataTransfer.setData(ASSET_DRAG, asset.id);
                event.dataTransfer.effectAllowed = "copy";
              }}
              onDoubleClick={() => ready && doc && update((d) => addAssetClip(d, asset, undefined, asset.kind === "video" ? undefined : playhead()))}
              className={cn("group flex items-center gap-2 rounded-md p-1.5 text-xs hover:bg-accent", ready && "cursor-grab")}
              title={ready ? "Drag to the timeline, or double-click to add" : undefined}
            >
              <span
                className="flex h-9 w-16 shrink-0 items-center justify-center overflow-hidden rounded bg-muted text-muted-foreground"
                style={
                  ready && asset.kind === "video"
                    ? { backgroundImage: `url(${endpoint}/assets/${asset.id}/thumbs.jpg)`, backgroundSize: `${asset.thumbs?.columns ?? 1}00% auto` }
                    : ready && asset.kind === "image"
                      ? { backgroundImage: `url(${endpoint}/assets/${asset.id}/image)`, backgroundSize: "contain", backgroundRepeat: "no-repeat", backgroundPosition: "center" }
                      : undefined
                }
              >
                {asset.status === "preparing" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : asset.status === "failed" ? (
                  <TriangleAlert className="size-4 text-destructive" />
                ) : asset.kind === "audio" ? (
                  <AudioLines className="size-4" />
                ) : asset.kind === "image" && !ready ? (
                  <ImageIcon className="size-4" />
                ) : null}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-foreground">{asset.name}</span>
                <span className="block truncate text-muted-foreground">
                  {asset.status === "preparing"
                    ? `Preparing ${asset.progress || 0}%`
                    : asset.status === "failed"
                      ? asset.error
                      : asset.transcript === "pending"
                        ? "Transcribing…"
                        : asset.kind === "image"
                          ? `${asset.width}×${asset.height}`
                          : timecode(asset.duration)}
                </span>
              </span>
              {ready && asset.hasAudio && (asset.transcript === "none" || asset.transcript === "failed") && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="hidden h-6 px-1.5 text-[10px] group-hover:inline-flex"
                  onClick={() => run(() => editorRequest(`${endpoint}/assets/${asset.id}/transcribe`, "POST", {}))}
                >
                  Transcribe
                </Button>
              )}
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`Remove ${asset.name}`}
                className="size-6 shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                onClick={() => remove(asset)}
              >
                <Trash2 />
              </Button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

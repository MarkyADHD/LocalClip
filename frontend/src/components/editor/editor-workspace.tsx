"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CloudOff,
  Download,
  Film,
  Keyboard,
  Layers,
  Loader2,
  Redo2,
  RotateCcw,
  Undo2,
} from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { downloadBlob } from "@/lib/clip-actions";
import {
  clamp,
  splitSegment,
  timecode,
  type CaptionStyle,
} from "@/lib/editor/document";
import { cn } from "@/lib/utils";
import { editorRequest, useEditor } from "./use-editor";
import { Preview } from "./preview";
import { Timeline } from "./timeline";
import { Inspector, type InspectorTab } from "./inspector";
import { ExportPanel, readyEditor, type ClipSummary } from "./export-panel";
import { Keys, ToolButton } from "./studio-ui";

const SHORTCUTS: [string[], string][] = [
  [["Space"], "Play / pause"],
  [["←", "→"], "Previous / next frame"],
  [["Shift", "←", "→"], "Jump one second"],
  [["I"], "Set in point"],
  [["O"], "Set out point"],
  [["S"], "Split at playhead"],
  [["Del"], "Remove the selected segment"],
  [["Ctrl/⌘", "Z"], "Undo"],
  [["Ctrl/⌘", "Shift", "Z"], "Redo"],
  [["Ctrl/⌘", "S"], "Save draft"],
];

// Widgets that own these keys natively; the editor shortcuts must not steal them.
const WIDGET_KEYS: Record<string, string[]> = {
  "[role=tab],[role=radio]": ["arrowleft", "arrowright", " "],
  "[role=switch],[role=checkbox]": [" "],
};

interface Props {
  taskId: string;
  title: string;
  clips: ClipSummary[];
  clip: ClipSummary;
  onSelect: (id: string) => void;
  refreshClips: (id?: string) => Promise<void>;
}
export function EditorWorkspace({
  taskId,
  title,
  clips,
  clip,
  onSelect,
  refreshClips,
}: Props) {
  const endpoint = `/api/tasks/${taskId}/clips/${clip.id}/editor`;
  const editor = useEditor(endpoint),
    doc = editor.document,
    asset = editor.asset;
  const [tab, setTab] = useState<InspectorTab>("captions"),
    [segmentIndex, setSegmentIndex] = useState(0),
    [time, setTime] = useState(0);
  const [seekRequest, setSeekRequest] = useState({ time: 0, nonce: 0 });
  const [exportOpen, setExportOpen] = useState(false),
    [helpOpen, setHelpOpen] = useState(false),
    [restoreOpen, setRestoreOpen] = useState(false),
    [reloadOpen, setReloadOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]),
    [combining, setCombining] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const index = doc ? Math.min(segmentIndex, doc.segments.length - 1) : 0;
  const segments = useRef(doc?.segments);
  segments.current = doc?.segments;
  const seek = useCallback((value: number) => {
    setTime(value);
    setSeekRequest({ time: value, nonce: Date.now() });
    // Jumping into another segment (from the transcript, say) selects it, so Split and trim act there.
    setSegmentIndex((current) => {
      const list = segments.current ?? [],
        inside = (i: number) =>
          list[i] && value >= list[i].start && value <= list[i].end;
      if (inside(current)) return current;
      const found = list.findIndex((_, i) => inside(i));
      return found < 0 ? current : found;
    });
  }, []);
  const switchClip = async (id: string) => {
    if (id === clip.id) return;
    try {
      await editor.save();
    } catch {
      toast.error(
        "Your draft is kept locally. Save it before switching clips.",
      );
      return;
    }
    onSelect(id);
  };
  const applyAll = async (style: CaptionStyle) => {
    try {
      await editor.save();
      for (const c of clips) {
        if (c.id === clip.id) continue;
        const url = `/api/tasks/${taskId}/clips/${c.id}/editor`,
          state = await readyEditor(url);
        await editorRequest(url, "PATCH", {
          basis: state.basis,
          revision: state.draft.revision,
          document: { ...state.draft.document, captions: style },
        });
      }
      toast.success("Caption style applied to all clips");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const combine = async () => {
    setCombining(true);
    try {
      await editor.save();
      for (const id of selected)
        await readyEditor(`/api/tasks/${taskId}/clips/${id}/editor`);
      const result = await editorRequest<{
        id: string;
        anchor_clip_id: string;
      }>(`/api/tasks/${taskId}/editor/combine`, "POST", { clip_ids: selected });
      const started = Date.now();
      let combinedId = "";
      while (!combinedId) {
        const job = await editorRequest<{
          status: string;
          clip_id?: string;
          error?: string;
        }>(
          `/api/tasks/${taskId}/clips/${result.anchor_clip_id}/editor/exports/${result.id}`,
        );
        if (job.status === "failed" || job.status === "cancelled")
          throw new Error(job.error || "Combine cancelled");
        if (job.clip_id) combinedId = job.clip_id;
        else {
          if (Date.now() - started > 600_000)
            throw new Error(
              "The combine is still running in the export queue. Refresh your clips when it completes.",
            );
          await new Promise((r) => setTimeout(r, 1500));
        }
      }
      await refreshClips(combinedId);
      toast.success("Combined draft created. Original clips are unchanged.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setCombining(false);
    }
  };
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const key = event.key.toLowerCase();
      if (
        target.closest(
          "input,textarea,select,[contenteditable=true],[role=dialog],[role=slider],[role=listbox],[role=combobox]",
        ) ||
        Object.entries(WIDGET_KEYS).some(
          ([selector, keys]) => target.closest(selector) && keys.includes(key),
        ) ||
        helpOpen ||
        exportOpen ||
        restoreOpen ||
        reloadOpen ||
        !doc ||
        !asset
      )
        return;
      if (event.metaKey || event.ctrlKey) {
        if (key === "z") {
          event.preventDefault();
          if (event.shiftKey) editor.redo();
          else editor.undo();
        }
        if (key === "y") {
          event.preventDefault();
          editor.redo();
        }
        if (key === "s") {
          event.preventDefault();
          void editor.save().catch(() => {});
        }
        return;
      }
      const segment = doc.segments[index];
      if (event.code === "Space") {
        event.preventDefault();
        document
          .querySelector<HTMLButtonElement>(
            videoRef.current?.paused
              ? 'button[aria-label="Play"]'
              : 'button[aria-label="Pause"]',
          )
          ?.click();
      }
      if (key === "arrowleft" || key === "arrowright") {
        event.preventDefault();
        videoRef.current?.pause();
        seek(
          clamp(
            time +
              (key === "arrowleft" ? -1 : 1) *
                (event.shiftKey ? 1 : 1 / asset.fps),
            0,
            asset.duration,
          ),
        );
      }
      if (key === "i") {
        event.preventDefault();
        editor.update((d) => ({
          ...d,
          segments: d.segments.map((s, i) =>
            i === index
              ? { ...s, start: clamp(time, 0, segment.end - 0.04) }
              : s,
          ),
        }));
      }
      if (key === "o") {
        event.preventDefault();
        editor.update((d) => ({
          ...d,
          segments: d.segments.map((s, i) =>
            i === index
              ? { ...s, end: clamp(time, segment.start + 0.04, asset.duration) }
              : s,
          ),
        }));
      }
      if (key === "s") {
        event.preventDefault();
        editor.update((d) => splitSegment(d, index, time));
      }
      if ((key === "delete" || key === "backspace") && doc.segments.length > 1) {
        event.preventDefault();
        editor.update((d) => ({
          ...d,
          segments: d.segments.filter((_, i) => i !== index),
        }));
        setSegmentIndex(Math.max(0, index - 1));
      }
      if (key === "?") setHelpOpen(true);
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [
    asset,
    doc,
    editor,
    index,
    time,
    seek,
    helpOpen,
    exportOpen,
    restoreOpen,
    reloadOpen,
  ]);
  const saved = editor.status === "All changes saved",
    saving = editor.status === "Saving…";
  // The studio is dark like every video editor; menus and dialogs render outside it, so the page goes dark too.
  useEffect(() => {
    const root = document.documentElement;
    if (root.classList.contains("dark")) return;
    root.classList.add("dark");
    return () => root.classList.remove("dark");
  }, []);
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background text-foreground">
      <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b bg-card px-3 py-2">
        <Button variant="ghost" size="icon-sm" asChild>
          <Link href={`/tasks/${taskId}`} aria-label="Back to generation">
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold">
            {clip.hook_title || `Clip ${clip.clip_order}`}
          </h1>
          <p className="truncate text-xs text-muted-foreground">
            Clip {clip.clip_order} · {title}
          </p>
        </div>
        <span
          role="status"
          aria-live="polite"
          className={cn(
            "flex items-center gap-1.5 text-xs text-muted-foreground",
            editor.error && "text-destructive",
          )}
        >
          {saved ? (
            <Check className="size-3.5" />
          ) : saving ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : editor.error ? (
            <CloudOff className="size-3.5" />
          ) : null}
          <span className="max-sm:hidden">{editor.status}</span>
        </span>
        <div className="flex items-center">
          <ToolButton
            label="Undo"
            shortcut={["Ctrl/⌘", "Z"]}
            size="icon-sm"
            disabled={!editor.canUndo}
            onClick={editor.undo}
          >
            <Undo2 />
          </ToolButton>
          <ToolButton
            label="Redo"
            shortcut={["Ctrl/⌘", "Shift", "Z"]}
            size="icon-sm"
            disabled={!editor.canRedo}
            onClick={editor.redo}
          >
            <Redo2 />
          </ToolButton>
          <ToolButton
            label="Restore original"
            size="icon-sm"
            disabled={!doc}
            onClick={() => setRestoreOpen(true)}
          >
            <RotateCcw />
          </ToolButton>
          <ToolButton
            label="Keyboard shortcuts"
            shortcut="?"
            size="icon-sm"
            onClick={() => setHelpOpen(true)}
          >
            <Keyboard />
          </ToolButton>
        </div>
        <Button
          size="sm"
          className="bg-brand text-brand-foreground hover:bg-brand/90"
          disabled={!doc}
          onClick={() => setExportOpen(true)}
        >
          <Download />
          Export
        </Button>
      </header>
      <div className="shrink-0 space-y-2 px-3 pt-2 empty:hidden">
        {editor.error && (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertDescription className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="mr-auto">{editor.error}</span>
              <span className="flex flex-wrap gap-1">
                {doc ? (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void editor.save().catch(() => {})}
                    >
                      Retry save
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        downloadBlob(
                          new Blob([JSON.stringify(doc, null, 2)], {
                            type: "application/json",
                          }),
                          `localclip-draft-${clip.id}.json`,
                        )
                      }
                    >
                      Back up draft
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setReloadOpen(true)}
                    >
                      Reload saved version
                    </Button>
                  </>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await editorRequest(`${endpoint}/prepare`, "POST");
                        window.location.reload();
                      } catch (e) {
                        toast.error((e as Error).message);
                      }
                    }}
                  >
                    Retry preparation
                  </Button>
                )}
              </span>
            </AlertDescription>
          </Alert>
        )}
        {editor.storageError && (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertDescription>
              Local draft storage is full or unavailable. Keep this tab open
              until the server confirms your changes are saved.
            </AlertDescription>
          </Alert>
        )}
      </div>
      <div className="flex min-h-0 flex-1 max-lg:flex-col max-lg:overflow-y-auto">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col max-lg:flex-none">
          <div className="flex min-h-0 flex-1 max-lg:flex-col">
            <aside
              aria-label="Your clips"
              className="flex shrink-0 flex-col border-r bg-card lg:w-44"
            >
              <ul className="flex min-h-0 flex-1 gap-1 overflow-auto p-1.5 lg:flex-col">
                {clips.map((c) => {
                  const active = c.id === clip.id,
                    order = selected.indexOf(c.id);
                  return (
                    <li
                      key={c.id}
                      className={cn(
                        "group relative flex w-44 shrink-0 gap-2 rounded-md p-1.5 transition-colors hover:bg-accent lg:w-auto",
                        active && "bg-accent ring-1 ring-brand",
                      )}
                    >
                      <span
                        aria-hidden
                        className="flex h-14 w-9 shrink-0 items-center justify-center overflow-hidden rounded bg-muted text-muted-foreground"
                        style={{
                          backgroundImage: `url(/api/tasks/${taskId}/clips/${c.id}/editor/media/thumbnails.jpg)`,
                          backgroundSize: "auto 100%",
                          backgroundPosition: "center",
                        }}
                      >
                        <Film className="size-3.5 opacity-40" />
                      </span>
                      <button
                        className="min-w-0 flex-1 text-left outline-none after:absolute after:inset-0 after:rounded-md focus-visible:after:ring-[3px] focus-visible:after:ring-ring/50"
                        onClick={() => void switchClip(c.id)}
                        aria-pressed={active}
                        aria-label={`Edit clip ${c.clip_order}`}
                      >
                        <span className="flex items-center justify-between gap-2 text-[11px]">
                          <span className="font-medium">Clip {c.clip_order}</span>
                          <span className="text-muted-foreground tabular-nums">
                            {timecode(c.duration).replace(/\.\d+$/, "")}
                          </span>
                        </span>
                        <span className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
                          {c.hook_title || c.text}
                        </span>
                      </button>
                      <Checkbox
                        aria-label={`Select clip ${c.clip_order} for combine`}
                        title="Add to a montage"
                        checked={order >= 0}
                        onCheckedChange={(checked) =>
                          setSelected((ids) =>
                            checked
                              ? [...ids, c.id]
                              : ids.filter((id) => id !== c.id),
                          )
                        }
                        className={cn(
                          "absolute right-1.5 bottom-1.5 z-10 bg-background transition-opacity",
                          order < 0 &&
                            "opacity-0 group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100",
                        )}
                      />
                    </li>
                  );
                })}
              </ul>
              {clips.length > 1 && (
                <div className="space-y-1.5 border-t p-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    className="h-7 w-full text-xs"
                    disabled={combining || selected.length < 2}
                    onClick={() => void combine()}
                  >
                    {combining ? <Loader2 className="animate-spin" /> : <Layers />}
                    {combining
                      ? "Building…"
                      : selected.length >= 2
                        ? `Montage of ${selected.length}`
                        : "Make a montage"}
                  </Button>
                  <p className="text-[11px] leading-snug text-muted-foreground max-lg:hidden">
                    {selected.length >= 2
                      ? "Joined in the order you ticked them, as a new clip."
                      : "Tick two or more clips to join them into one."}
                  </p>
                </div>
              )}
            </aside>
            {doc && asset?.status === "ready" ? (
              <Preview
                doc={doc}
                asset={asset}
                endpoint={endpoint}
                segmentIndex={index}
                select={setSegmentIndex}
                onTime={setTime}
                seekRequest={seekRequest}
                update={editor.update}
                videoRef={videoRef}
              />
            ) : (
              <div className="flex min-h-[420px] flex-1 flex-col items-center justify-center p-8 text-center">
                <div className="mb-5 flex size-14 items-center justify-center rounded-full bg-muted">
                  {editor.error ? (
                    <AlertCircle className="size-6 text-destructive" />
                  ) : (
                    <Film className="size-6 text-muted-foreground" />
                  )}
                </div>
                <h2 className="font-display text-xl font-bold">
                  {editor.error
                    ? "Let’s get your preview back"
                    : "Getting this clip ready to edit"}
                </h2>
                <p className="mt-2 max-w-sm text-sm text-muted-foreground">
                  {editor.error
                    ? "Your original clip is safe. Retry preparation to continue."
                    : "Loading the video, word timings and facecam position. This only happens once per clip."}
                </p>
                {!editor.error && (
                  <Loader2 className="mt-5 size-5 animate-spin text-muted-foreground" />
                )}
              </div>
            )}
          </div>
          {doc && asset?.status === "ready" && (
            <Timeline
              doc={doc}
              asset={asset}
              endpoint={endpoint}
              currentTime={time}
              index={index}
              select={setSegmentIndex}
              seek={seek}
              update={editor.update}
            />
          )}
        </div>
        {doc && asset?.status === "ready" && (
          <Inspector
            doc={doc}
            asset={asset}
            tab={tab}
            setTab={setTab}
            time={time}
            seek={seek}
            update={editor.update}
            applyAll={applyAll}
            videoRef={videoRef}
            suggestedTitle={clip.hook_title}
          />
        )}
      </div>
      {doc && asset && (
        <ExportPanel
          open={exportOpen}
          setOpen={setExportOpen}
          taskId={taskId}
          clip={clip}
          clips={clips}
          doc={doc}
          asset={asset}
          save={editor.save}
        />
      )}
      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Keyboard shortcuts</DialogTitle>
            <DialogDescription>
              Shortcuts work whenever you’re outside a text field.
            </DialogDescription>
          </DialogHeader>
          <dl className="divide-y rounded-lg border">
            {SHORTCUTS.map(([keys, label]) => (
              <div
                key={label}
                className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
              >
                <dt>{label}</dt>
                <dd>
                  <Keys keys={keys} />
                </dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>
      <Dialog open={restoreOpen} onOpenChange={setRestoreOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Restore the original edit?</DialogTitle>
            <DialogDescription>
              This resets cuts, captions, framing, audio, and effects. You can
              undo this action.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRestoreOpen(false)}>
              Keep editing
            </Button>
            <Button
              onClick={() => {
                if (asset) editor.update(() => structuredClone(asset.original));
                setSegmentIndex(0);
                seek(0);
                setRestoreOpen(false);
              }}
            >
              Restore original
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={reloadOpen} onOpenChange={setReloadOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Load the saved version?</DialogTitle>
            <DialogDescription>
              This replaces local changes and undo history with the server
              draft. Back up your draft first if you want to keep your local
              changes.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReloadOpen(false)}>
              Keep local draft
            </Button>
            <Button
              onClick={async () => {
                try {
                  await editor.reload();
                  setReloadOpen(false);
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              Load saved version
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

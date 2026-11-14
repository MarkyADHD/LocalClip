"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Check,
  CloudOff,
  Loader2,
  Magnet,
  Maximize2,
  Minus,
  Plus,
  Redo2,
  Scissors,
  Sparkles,
  Trash2,
  Type,
  Undo2,
  Upload,
} from "lucide-react";
import { PageError, PageLoading } from "@/components/app/page-state";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ToolButton } from "@/components/editor/studio-ui";
import { cn } from "@/lib/utils";
import {
  addAssetClip,
  addTextClip,
  addTrack,
  captionLines,
  deleteClips,
  docDuration,
  mainTrack,
  splitAt,
  timelineWords,
} from "@/lib/project/document";
import type { Engine } from "./engine";
import { ExportDialog } from "./export-dialog";
import { CaptionSettings, Properties } from "./inspector";
import { MediaBin } from "./media-bin";
import { Assistant } from "./assistant";
import { Publish } from "./publish";
import { Timeline } from "./timeline";
import { TranscriptPanel } from "./transcript";
import { useProject } from "./use-project";
import { usePlayhead, Viewer } from "./viewer";

export function ProjectWorkspace({ id }: { id: string }) {
  const project = useProject(id);
  const { doc, update, assets, words } = project;
  const [engine, setEngine] = useState<Engine | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [zoom, setZoom] = useState(0);
  const [snapping, setSnapping] = useState(true);
  const [tab, setTab] = useState("transcript");
  const [exporting, setExporting] = useState(false);
  const [name, setName] = useState<string | null>(null);

  const clips = doc?.clips,
    tracks = doc?.tracks,
    edits = doc?.wordEdits,
    perLine = doc?.captions.wordsPerLine;
  const lines = useMemo(
    () => (doc ? captionLines(doc, timelineWords(doc, words)) : []),
    // Only what changes the words on screen, so dragging a slider elsewhere costs nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [clips, tracks, edits, perLine, words],
  );
  useEffect(() => {
    if (engine && doc) engine.set(doc, assets, lines);
  }, [engine, doc, assets, lines]);

  // The first recording goes straight onto the timeline when it is ready.
  const placed = useRef(new Set<string>());
  useEffect(() => {
    if (!doc || doc.clips.length) return;
    const first = project.assetList.find((a) => a.status === "ready" && a.kind === "video" && !placed.current.has(a.id));
    if (!first) return;
    placed.current.add(first.id);
    update((d) => (d.clips.length ? d : addAssetClip(d, first)));
  }, [doc, project.assetList, update]);

  const remove = useCallback(
    (invert: boolean) => {
      if (!selected.size) return;
      update((d) => {
        const onMain = d.clips.some((c) => selected.has(c.id) && c.track === mainTrack(d).id);
        return deleteClips(d, selected, onMain !== invert);
      });
      setSelected(new Set());
    },
    [selected, update],
  );
  const split = useCallback(() => engine && update((d) => splitAt(d, engine.time, selected)), [engine, selected, update]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true], [role=dialog]")) return;
      const mod = event.ctrlKey || event.metaKey,
        key = event.key.toLowerCase(),
        frame = 1 / (doc?.fps ?? 30);
      const done = () => event.preventDefault();
      if (mod && key === "z") return done(), event.shiftKey ? project.redo() : project.undo();
      if (mod && key === "y") return done(), project.redo();
      if (mod && key === "s") return done(), void project.save().catch(() => {});
      if (mod && key === "a") return done(), setSelected(new Set(doc?.clips.map((c) => c.id)));
      if (mod || !engine || !doc) return;
      if (key === " ") return done(), engine.toggle();
      if (key === "s") return done(), split();
      if (key === "t") return done(), update((d) => addTextClip(d, engine.time));
      if (key === "n") return done(), setSnapping((value) => !value);
      if (key === "delete" || key === "backspace") return done(), remove(event.shiftKey);
      if (key === "escape") return setSelected(new Set());
      if (key === "home") return done(), engine.seek(0);
      if (key === "end") return done(), engine.seek(docDuration(doc));
      if (key === "arrowleft") return done(), engine.seek(engine.time - (event.shiftKey ? 1 : frame));
      if (key === "arrowright") return done(), engine.seek(engine.time + (event.shiftKey ? 1 : frame));
      if (key === "=" || key === "+") return done(), setZoom((z) => Math.min(400, (z || 20) * 1.5));
      if (key === "-") return done(), setZoom((z) => (z ? z / 1.5 : 0));
      if (key === "0") return done(), setZoom(0);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doc, engine, project, remove, split, update]);

  // The studio is dark like every video editor; menus and dialogs render outside it, so the page goes dark too.
  useEffect(() => {
    const root = document.documentElement;
    if (root.classList.contains("dark")) return;
    root.classList.add("dark");
    return () => root.classList.remove("dark");
  }, []);
  const playhead = useCallback(() => engine?.time ?? 0, [engine]);

  if (project.error && !doc) return <PageError message={project.error} />;
  if (!doc) return <PageLoading />;
  const saved = project.status === "All changes saved",
    saving = project.status === "Saving…";
  return (
    <TooltipProvider>
      <div className="fixed inset-0 z-50 flex flex-col bg-background text-foreground">
        <header className="flex shrink-0 items-center gap-3 border-b bg-card px-3 py-2">
          <Button variant="ghost" size="icon-sm" asChild>
            <Link href="/projects" aria-label="Back to projects">
              <ArrowLeft />
            </Link>
          </Button>
          <input
            aria-label="Project name"
            className="min-w-0 flex-1 truncate rounded bg-transparent px-1 text-sm font-semibold outline-none focus:bg-muted"
            value={name ?? project.name}
            onChange={(event) => setName(event.target.value)}
            onBlur={() => {
              if (name?.trim() && name !== project.name) project.rename(name.trim());
              setName(null);
            }}
            onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
          />
          <span role="status" aria-live="polite" className={cn("flex items-center gap-1.5 text-xs text-muted-foreground", project.error && "text-destructive")}>
            {saved ? <Check className="size-3.5" /> : saving ? <Loader2 className="size-3.5 animate-spin" /> : project.error ? <CloudOff className="size-3.5" /> : null}
            <span className="max-sm:hidden">{project.error ?? project.status}</span>
          </span>
          <div className="flex items-center">
            <ToolButton label="Undo" shortcut={["Ctrl", "Z"]} size="icon-sm" disabled={!project.canUndo} onClick={project.undo}>
              <Undo2 />
            </ToolButton>
            <ToolButton label="Redo" shortcut={["Ctrl", "Shift", "Z"]} size="icon-sm" disabled={!project.canRedo} onClick={project.redo}>
              <Redo2 />
            </ToolButton>
          </div>
          <Button size="sm" onClick={() => setExporting(true)} disabled={!doc.clips.length}>
            <Upload /> Export
          </Button>
        </header>
        <div className="grid min-h-0 flex-1 grid-cols-[15rem_minmax(0,1fr)_minmax(20rem,26rem)]">
          <aside className="min-h-0 border-r bg-card" aria-label="Media">
            <MediaBin project={project} playhead={playhead} />
          </aside>
          <main className="min-h-0">
            <Viewer project={project} selected={selected} engine={engine} onEngine={setEngine} />
          </main>
          <aside className="min-h-0 border-l bg-card" aria-label="Tools">
            <Tabs value={tab} onValueChange={setTab} className="flex h-full min-h-0 flex-col gap-0">
              <TabsList className="m-2 grid shrink-0 grid-cols-5">
                <TabsTrigger value="transcript">Transcript</TabsTrigger>
                <TabsTrigger value="clip">Clip</TabsTrigger>
                <TabsTrigger value="captions">Captions</TabsTrigger>
                <TabsTrigger value="publish">Publish</TabsTrigger>
                <TabsTrigger value="assistant" className="relative">
                  <Sparkles /> AI
                  {project.proposals.length > 0 && <span className="absolute right-1 top-1 size-1.5 rounded-full bg-brand" />}
                </TabsTrigger>
              </TabsList>
              <TabsContent value="transcript" className="min-h-0 flex-1">
                <TranscriptPanel project={project} engine={engine} />
              </TabsContent>
              <TabsContent value="clip" className="min-h-0 flex-1 overflow-y-auto">
                <ClipTab project={project} engine={engine} selected={selected} />
              </TabsContent>
              <TabsContent value="captions" className="min-h-0 flex-1 overflow-y-auto">
                <CaptionSettings project={project} />
              </TabsContent>
              <TabsContent value="publish" className="min-h-0 flex-1 overflow-y-auto">
                <Publish project={project} engine={engine} lines={lines} />
              </TabsContent>
              <TabsContent value="assistant" className="min-h-0 flex-1">
                <Assistant project={project} engine={engine} />
              </TabsContent>
            </Tabs>
          </aside>
        </div>
        <section className="flex h-[38%] min-h-52 shrink-0 flex-col border-t bg-card" aria-label="Timeline">
          <div className="flex shrink-0 items-center gap-1 border-b px-2 py-1">
            <ToolButton label="Split at playhead" shortcut="S" size="icon-sm" onClick={split}>
              <Scissors />
            </ToolButton>
            <ToolButton label="Delete selected" shortcut="Del" size="icon-sm" disabled={!selected.size} onClick={() => remove(false)}>
              <Trash2 />
            </ToolButton>
            <ToolButton label="Add text" shortcut="T" size="icon-sm" onClick={() => engine && update((d) => addTextClip(d, engine.time))}>
              <Type />
            </ToolButton>
            <ToolButton label={snapping ? "Snapping on" : "Snapping off"} shortcut="N" size="icon-sm" onClick={() => setSnapping(!snapping)}>
              <Magnet className={snapping ? "text-brand" : ""} />
            </ToolButton>
            <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => update((d) => addTrack(d, "video"))}>
              <Plus /> Video track
            </Button>
            <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => update((d) => addTrack(d, "audio"))}>
              <Plus /> Audio track
            </Button>
            <span className="ml-auto max-lg:hidden text-[11px] text-muted-foreground">
              Deleting on the main track closes the gap. Hold Shift to leave it open.
            </span>
            <ToolButton label="Zoom out" shortcut="-" size="icon-sm" onClick={() => setZoom((z) => (z ? z / 1.5 : 0))}>
              <Minus />
            </ToolButton>
            <ToolButton label="Zoom in" shortcut="+" size="icon-sm" onClick={() => setZoom((z) => Math.min(400, (z || 20) * 1.5))}>
              <Plus />
            </ToolButton>
            <ToolButton label="Fit the whole video" shortcut="0" size="icon-sm" onClick={() => setZoom(0)}>
              <Maximize2 />
            </ToolButton>
          </div>
          <Timeline
            project={project}
            engine={engine}
            lines={lines}
            selected={selected}
            onSelect={(ids) => {
              setSelected(ids);
              if (ids.size && tab === "transcript") setTab("clip");
            }}
            snapping={snapping}
            zoom={zoom}
            onZoom={setZoom}
          />
        </section>
        <ExportDialog project={project} lines={lines} open={exporting} onOpenChange={setExporting} />
      </div>
    </TooltipProvider>
  );
}

/** Re-reads the playhead so the clip's values follow it. */
function ClipTab(props: Parameters<typeof Properties>[0]) {
  usePlayhead(props.engine);
  return <Properties {...props} />;
}

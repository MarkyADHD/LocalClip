"use client";
import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { editorRequest } from "@/components/editor/use-editor";
import { chapterText, docDuration, timecode, toSrt, type TimedWord } from "@/lib/project/document";
import type { Project } from "./use-project";

const QUALITY: [string, string, string][] = [
  ["high", "High", "Largest file, for uploading to YouTube"],
  ["standard", "Standard", "A good balance"],
  ["small", "Small", "Quick drafts and sharing"],
];

export function saveText(name: string, text: string) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function ExportDialog({ project, lines, open, onOpenChange }: { project: Project; lines: TimedWord[][]; open: boolean; onOpenChange: (open: boolean) => void }) {
  const doc = project.doc!;
  const [quality, setQuality] = useState("high");
  const [starting, setStarting] = useState(false);
  const job = project.jobs[0];
  const running = job && (job.status === "queued" || job.status === "rendering");
  const start = async () => {
    setStarting(true);
    try {
      await project.save();
      await editorRequest(`${project.endpoint}/exports`, "POST", { document: doc, quality });
      await project.refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start the export");
    } finally {
      setStarting(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Export video</DialogTitle>
          <DialogDescription>
            {doc.width}×{doc.height} · {Number(doc.fps.toFixed(2))} fps · {timecode(docDuration(doc))} · MP4 (H.264). Rendered on this PC from your
            original files, so you can close this window while it runs.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-1.5" role="radiogroup" aria-label="Quality">
          {QUALITY.map(([value, name, hint]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={quality === value}
              disabled={running}
              onClick={() => setQuality(value)}
              className={`rounded-md border px-3 py-2 text-left text-sm ${quality === value ? "border-brand bg-brand/10" : "hover:bg-accent"}`}
            >
              <b>{name}</b>
              <span className="ml-2 text-xs text-muted-foreground">{hint}</span>
            </button>
          ))}
        </div>
        {job && (
          <div className="space-y-2 rounded-md bg-muted p-3 text-sm" role="status">
            {running ? (
              <>
                <div className="flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin" />
                  {job.status === "queued" ? "Waiting to start…" : `Rendering ${job.progress}%`}
                  <Button size="sm" variant="ghost" className="ml-auto h-7" onClick={() => editorRequest(`${project.endpoint}/exports/${job.id}`, "DELETE").then(project.refresh)}>
                    Cancel
                  </Button>
                </div>
                <Progress value={job.progress} />
              </>
            ) : job.status === "completed" ? (
              <div className="flex items-center gap-2">
                Your last export is ready.
                <Button size="sm" className="ml-auto" asChild>
                  <a href={`${project.endpoint}/exports/${job.id}/file`} download>
                    <Download /> Save video
                  </a>
                </Button>
              </div>
            ) : (
              <p className={job.status === "failed" ? "text-destructive" : ""}>{job.status === "failed" ? job.error : "The last export was cancelled."}</p>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button onClick={start} disabled={running || starting || docDuration(doc) <= 0}>
            {starting && <Loader2 className="animate-spin" />} Export
          </Button>
          <Button variant="outline" disabled={!lines.length} onClick={() => saveText(`${project.name || "captions"}.srt`, toSrt(lines))}>
            Captions file (.srt)
          </Button>
          {doc.chapters.length > 0 && (
            <Button variant="outline" onClick={() => navigator.clipboard.writeText(chapterText(doc.chapters)).then(() => toast.success("Chapters copied"))}>
              Copy chapters
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

"use client";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Section } from "@/components/editor/studio-ui";
import { chapterText, timecode, toSrt, type ProjectDocument, type TimedWord } from "@/lib/project/document";
import type { Engine } from "./engine";
import { saveText } from "./export-dialog";
import type { Project } from "./use-project";

/** Everything YouTube asks for next to the video file: title, description, chapters, captions. */
export function Publish({ project, engine, lines }: { project: Project; engine: Engine | null; lines: TimedWord[][] }) {
  const doc = project.doc!;
  const set = (values: Partial<ProjectDocument>, group = "") => project.update((d) => ({ ...d, ...values }), group);
  const chapters = [...doc.chapters].sort((a, b) => a.time - b.time);
  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast.success("Copied"));
  return (
    <div className="space-y-6 p-4">
      <Section title="Title">
        <Input aria-label="Video title" maxLength={200} value={doc.title} onChange={(event) => set({ title: event.target.value }, "title")} />
      </Section>
      <Section
        title="Description"
        action={
          <Button size="sm" variant="ghost" className="h-7" disabled={!doc.description && !chapters.length} onClick={() => copy([doc.description, chapterText(chapters)].filter(Boolean).join("\n\n"))}>
            Copy
          </Button>
        }
      >
        <Textarea aria-label="Video description" rows={6} maxLength={5000} value={doc.description} onChange={(event) => set({ description: event.target.value }, "description")} />
      </Section>
      <Section
        title="Chapters"
        description="YouTube shows these on the progress bar when they are pasted into the description. The first must start at 0:00."
        action={
          <Button
            size="sm"
            variant="outline"
            className="h-7"
            onClick={() => set({ chapters: [...doc.chapters, { time: Math.round((engine?.time ?? 0) * 10) / 10, title: `Chapter ${doc.chapters.length + 1}` }] })}
          >
            <Plus /> At playhead
          </Button>
        }
      >
        <ul className="space-y-1.5">
          {chapters.map((chapter) => (
            <li key={`${chapter.time}-${doc.chapters.indexOf(chapter)}`} className="flex items-center gap-2">
              <button type="button" className="w-12 shrink-0 text-left text-xs tabular-nums text-muted-foreground hover:text-foreground" onClick={() => engine?.seek(chapter.time)}>
                {timecode(chapter.time)}
              </button>
              <Input
                aria-label={`Chapter at ${timecode(chapter.time)}`}
                className="h-8 text-sm"
                maxLength={120}
                value={chapter.title}
                onChange={(event) => set({ chapters: doc.chapters.map((c) => (c === chapter ? { ...c, title: event.target.value } : c)) }, "chapter")}
              />
              <Button size="icon-sm" variant="ghost" aria-label="Remove chapter" onClick={() => set({ chapters: doc.chapters.filter((c) => c !== chapter) })}>
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Captions file" description="Upload this to YouTube for captions viewers can switch on and off.">
        <Button size="sm" variant="outline" disabled={!lines.length} onClick={() => saveText(`${project.name || "captions"}.srt`, toSrt(lines))}>
          Download .srt
        </Button>
      </Section>
    </div>
  );
}

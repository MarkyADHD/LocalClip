"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Clapperboard, Loader2, Plus, Trash2 } from "lucide-react";
import { PageError, PageLoading } from "@/components/app/page-state";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { editorRequest } from "@/components/editor/use-editor";
import { timeAgo } from "@/lib/generations";
import { timecode } from "@/lib/project/document";

interface ProjectSummary {
  id: string;
  name: string;
  updated_at: number;
  duration: number;
}

export default function ProjectsPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [toDelete, setToDelete] = useState<ProjectSummary | null>(null);
  const load = useCallback(() => {
    editorRequest<{ projects: ProjectSummary[] }>("/api/projects")
      .then((result) => {
        setProjects(result.projects);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  const create = async () => {
    setCreating(true);
    try {
      const project = await editorRequest<{ id: string }>("/api/projects", "POST", { name: "Untitled video" });
      router.push(`/projects/${project.id}`);
    } catch (e) {
      setError((e as Error).message);
      setCreating(false);
    }
  };
  if (error) return <PageError message={error} retry={load} />;
  if (!projects) return <PageLoading />;
  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-8 md:py-10">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Video editor</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Edit full-length videos by their transcript: cut silences and filler words, add captions, overlays and music, and export for YouTube.
          </p>
        </div>
        <Button onClick={create} disabled={creating} className="shrink-0 bg-brand text-brand-foreground hover:bg-brand/90">
          {creating ? <Loader2 className="animate-spin" /> : <Plus />} New video
        </Button>
      </div>
      {!projects.length ? (
        <div className="mt-8 flex flex-col items-center rounded-2xl border border-dashed px-6 py-20 text-center">
          <span className="flex size-14 items-center justify-center rounded-2xl bg-muted"><Clapperboard className="size-7 text-muted-foreground" /></span>
          <h2 className="mt-4 text-lg font-semibold">No videos yet</h2>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">Start one, add your recording, and edit it by deleting words from the transcript.</p>
          <Button onClick={create} disabled={creating} className="mt-6">Start your first video</Button>
        </div>
      ) : (
        <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {projects.map((project) => (
            <li key={project.id} className="group relative">
              <Link
                href={`/projects/${project.id}`}
                className="flex h-full flex-col rounded-2xl border bg-card p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-foreground/25 hover:shadow-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="flex aspect-video items-center justify-center rounded-xl bg-muted text-muted-foreground">
                  <Clapperboard className="size-7" aria-hidden />
                </span>
                <span className="mt-3 block truncate text-sm font-semibold">{project.name}</span>
                <span className="mt-0.5 text-xs text-muted-foreground">
                  {project.duration ? timecode(project.duration) : "Empty"} · edited {timeAgo(new Date(project.updated_at * 1000).toISOString())}
                </span>
              </Link>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`Delete ${project.name}`}
                className="absolute right-6 top-6 bg-background/80 text-muted-foreground backdrop-blur hover:bg-destructive/10 hover:text-destructive md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100"
                onClick={() => setToDelete(project)}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => { if (!open) setToDelete(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this video project?</AlertDialogTitle>
            <AlertDialogDescription>&ldquo;{toDelete?.name}&rdquo; and its edits are removed. Your original files are not touched.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={() => { if (toDelete) void editorRequest(`/api/projects/${toDelete.id}`, "DELETE").then(load); }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}

"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Clapperboard, Loader2, Plus, Trash2 } from "lucide-react";
import { PageError, PageLoading } from "@/components/app/page-state";
import { Button } from "@/components/ui/button";
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
    <div className="mx-auto w-full max-w-4xl space-y-6 p-6 md:p-10">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">Video editor</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Edit full-length videos by their transcript: cut silences and filler words, add captions, overlays and music, and export for YouTube.
          </p>
        </div>
        <Button onClick={create} disabled={creating}>
          {creating ? <Loader2 className="animate-spin" /> : <Plus />} New video
        </Button>
      </div>
      {!projects.length ? (
        <button
          type="button"
          onClick={create}
          className="flex w-full flex-col items-center gap-3 rounded-xl border border-dashed p-14 text-sm text-muted-foreground hover:bg-accent"
        >
          <Clapperboard className="size-8" />
          Start your first video
        </button>
      ) : (
        <ul className="divide-y rounded-xl border bg-card">
          {projects.map((project) => (
            <li key={project.id} className="group flex items-center gap-3 px-4 py-3">
              <Link href={`/projects/${project.id}`} className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium group-hover:underline">{project.name}</span>
                <span className="text-xs text-muted-foreground">
                  {project.duration ? timecode(project.duration) : "Empty"} · edited {timeAgo(new Date(project.updated_at * 1000).toISOString())}
                </span>
              </Link>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`Delete ${project.name}`}
                className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                onClick={() => {
                  if (window.confirm(`Delete "${project.name}"? Your original files are not touched.`))
                    void editorRequest(`/api/projects/${project.id}`, "DELETE").then(load);
                }}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

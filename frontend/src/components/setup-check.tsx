"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, TriangleAlert, X } from "lucide-react";

import { cn } from "@/lib/utils";

type Problem = { id: string; level: "error" | "warning"; title: string; detail: string; link?: string };

const DISMISSED_KEY = "localclip-setup-dismissed";

function readDismissed(): string[] {
  try {
    return JSON.parse(localStorage.getItem(DISMISSED_KEY) ?? "[]");
  } catch {
    return [];
  }
}

/** Home screen: what is missing before this PC can make clips. Renders nothing when all is well. */
export function SetupCheck({ className }: { className?: string }) {
  const [problems, setProblems] = useState<Problem[]>([]);
  useEffect(() => {
    fetch("/api/setup-check", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        const dismissed = readDismissed();
        // Errors always show: clips will fail until they are fixed.
        setProblems((data?.problems ?? []).filter((p: Problem) => p.level === "error" || !dismissed.includes(p.id)));
      })
      .catch(() => {});
  }, []);

  const dismiss = (id: string) => {
    setProblems((current) => current.filter((p) => p.id !== id));
    try {
      localStorage.setItem(DISMISSED_KEY, JSON.stringify([...readDismissed(), id]));
    } catch {}
  };

  if (problems.length === 0) return null;
  return (
    <section aria-label="Setup problems" className={cn("space-y-2", className)}>
      {problems.map((problem) => (
        <div
          key={problem.id}
          className={cn("flex items-start gap-3 rounded-xl border bg-card p-4 text-sm", problem.level === "error" && "border-destructive/50")}
        >
          {problem.level === "error" ? <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" /> : <TriangleAlert className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
          <div className="min-w-0 flex-1">
            <p className="font-medium">{problem.title}</p>
            <p className="mt-1 text-muted-foreground">{problem.detail}</p>
            {problem.link && <Link href={problem.link} className="mt-2 inline-block font-medium text-brand underline-offset-4 hover:underline">Open Settings</Link>}
          </div>
          {problem.level === "warning" && (
            <button type="button" aria-label={`Hide: ${problem.title}`} onClick={() => dismiss(problem.id)} className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
              <X className="size-4" />
            </button>
          )}
        </div>
      ))}
    </section>
  );
}

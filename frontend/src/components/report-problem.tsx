"use client";

import { useState } from "react";
import { Bug, Copy, ExternalLink, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// No ?body= on the link: LocalClip.exe up to 1.6.0 opens File Explorer for any link with a query.
const NEW_ISSUE_URL = "https://github.com/MarkyADHD/LocalClip/issues/new";

/** Settings > Help. Builds a report from this PC's logs and lets the user copy it into a GitHub issue. */
export function ReportProblem() {
  const [report, setReport] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Report copied. Paste it into the GitHub page.");
    } catch {
      toast.message("Select the text below and copy it.");
    }
  };

  const build = async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/problem-report", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const text: string = (await response.json()).report;
      setReport(text);
      await copy(text);
    } catch {
      toast.error("Could not build the report. The logs are in the .localclip\\logs folder.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Something broke?</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Builds a report from this PC: your GPU, AI model and the last lines of LocalClip&apos;s logs. Nothing is sent until you post it yourself.
          </p>
        </div>
        <Button variant="outline" onClick={build} disabled={loading}>
          {loading ? <Loader2 className="size-4 animate-spin" /> : <Bug className="size-4" />}
          Report a problem
        </Button>
      </div>
      {report !== null && (
        <>
          <Textarea aria-label="Problem report" readOnly value={report} className="h-48 font-mono text-xs" onFocus={(event) => event.currentTarget.select()} />
          <p className="text-xs text-muted-foreground">
            Read it first: logs can include video links and file names. Your Windows user name and anything that looks like a password are already removed.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => copy(report)}><Copy className="size-4" />Copy again</Button>
            <Button asChild size="sm">
              <a href={NEW_ISSUE_URL} target="_blank" rel="noreferrer"><ExternalLink className="size-4" />Open GitHub and paste</a>
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { editorRequest } from "@/components/editor/use-editor";
import type {
  Asset,
  Assets,
  ProjectDocument,
  Word,
} from "@/lib/project/document";

export interface ExportJob {
  id: string;
  status: "queued" | "rendering" | "completed" | "failed" | "cancelled";
  progress: number;
  error?: string;
}
interface History {
  past: ProjectDocument[];
  present: ProjectDocument;
  future: ProjectDocument[];
}
interface Loaded {
  id: string;
  name: string;
  assets: Asset[];
  draft: { revision: number; document: ProjectDocument };
  jobs: ExportJob[];
}

/** Loads a project, keeps its undo history, saves edits shortly after they happen and follows its media and exports. */
export function useProject(id: string) {
  const endpoint = `/api/projects/${id}`;
  const [name, setName] = useState("");
  const [assetList, setAssetList] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [history, setHistory] = useState<History | null>(null);
  const [status, setStatus] = useState("Loading…");
  const [error, setError] = useState<string | null>(null);
  const [words, setWords] = useState<Record<string, Word[]>>({});
  const [waves, setWaves] = useState<Record<string, Uint8Array>>({});
  const historyRef = useRef<History | null>(null);
  const revision = useRef(0),
    saved = useRef<ProjectDocument | null>(null);
  const inFlight = useRef<Promise<void> | null>(null);
  const lastEdit = useRef({ group: "", at: 0 });
  const requested = useRef(new Set<string>());

  const publish = useCallback((next: History) => {
    historyRef.current = next;
    setHistory(next);
    setStatus(next.present === saved.current ? "All changes saved" : "Unsaved changes");
  }, []);
  /** Applies an edit. Edits sharing a `group` within a moment of each other (a drag, a slider) undo as one. */
  const update = useCallback(
    (change: (doc: ProjectDocument) => ProjectDocument, group = "") => {
      const current = historyRef.current;
      if (!current) return;
      const next = change(current.present);
      if (next === current.present) return;
      const coalesce =
        group && lastEdit.current.group === group && Date.now() - lastEdit.current.at < 1000;
      publish({
        past: coalesce ? current.past : [...current.past, current.present].slice(-100),
        present: next,
        future: [],
      });
      lastEdit.current = { group, at: Date.now() };
    },
    [publish],
  );
  const undo = useCallback(() => {
    const h = historyRef.current;
    if (h?.past.length)
      publish({
        past: h.past.slice(0, -1),
        present: h.past[h.past.length - 1],
        future: [h.present, ...h.future],
      });
    lastEdit.current.group = "";
  }, [publish]);
  const redo = useCallback(() => {
    const h = historyRef.current;
    if (h?.future.length)
      publish({
        past: [...h.past, h.present],
        present: h.future[0],
        future: h.future.slice(1),
      });
    lastEdit.current.group = "";
  }, [publish]);

  const save = useCallback(async () => {
    for (;;) {
      while (inFlight.current) await inFlight.current.catch(() => {});
      const document = historyRef.current?.present;
      if (!document || document === saved.current) return;
      setStatus("Saving…");
      const operation = (async () => {
        try {
          const result = await editorRequest<{ revision: number }>(endpoint, "PATCH", {
            revision: revision.current,
            document,
          });
          revision.current = result.revision;
          saved.current = document;
          setError(null);
          setStatus(
            historyRef.current?.present === document ? "All changes saved" : "Unsaved changes",
          );
        } catch (e) {
          setError(e instanceof Error ? e.message : "Could not save the project");
          setStatus("Save failed");
          throw e;
        }
      })();
      inFlight.current = operation;
      try {
        await operation;
      } finally {
        inFlight.current = null;
      }
    }
  }, [endpoint]);

  useEffect(() => {
    let stopped = false;
    editorRequest<Loaded>(endpoint)
      .then((loaded) => {
        if (stopped) return;
        setName(loaded.name);
        setAssetList(loaded.assets);
        setJobs(loaded.jobs);
        revision.current = loaded.draft.revision;
        saved.current = loaded.draft.document;
        publish({ past: [], present: loaded.draft.document, future: [] });
      })
      .catch((e) => !stopped && setError(e instanceof Error ? e.message : "Could not open the project"));
    return () => {
      stopped = true;
    };
  }, [endpoint, publish]);

  useEffect(() => {
    if (!history || error) return;
    const timer = setTimeout(() => void save().catch(() => {}), 800);
    return () => clearTimeout(timer);
  }, [history, save, error]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (historyRef.current && historyRef.current.present !== saved.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  const refresh = useCallback(async () => {
    const next = await editorRequest<{ assets: Asset[]; jobs: ExportJob[] }>(`${endpoint}/assets`);
    setAssetList(next.assets);
    setJobs(next.jobs);
  }, [endpoint]);
  // Follow anything still being worked on: a file being prepared, a transcript, an export.
  const busy =
    assetList.some((a) => a.status === "preparing" || a.transcript === "pending") ||
    jobs.some((j) => j.status === "queued" || j.status === "rendering");
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void refresh().catch(() => {}), 2000);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  // Fetch each transcript and waveform once, when it is ready.
  useEffect(() => {
    for (const asset of assetList) {
      if (asset.transcript === "ready" && !requested.current.has(`w${asset.id}`)) {
        requested.current.add(`w${asset.id}`);
        editorRequest<{ words: Word[] }>(`${endpoint}/assets/${asset.id}/transcript.json`)
          .then((data) => setWords((all) => ({ ...all, [asset.id]: data.words })))
          .catch(() => requested.current.delete(`w${asset.id}`));
      }
      if (
        asset.status === "ready" &&
        asset.hasAudio &&
        asset.kind !== "image" &&
        !requested.current.has(`a${asset.id}`)
      ) {
        requested.current.add(`a${asset.id}`);
        fetch(`${endpoint}/assets/${asset.id}/waveform.bin`)
          .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject()))
          .then((data) => setWaves((all) => ({ ...all, [asset.id]: new Uint8Array(data) })))
          .catch(() => requested.current.delete(`a${asset.id}`));
      }
    }
  }, [assetList, endpoint]);

  const assets = useMemo<Assets>(
    () => Object.fromEntries(assetList.map((a) => [a.id, a])),
    [assetList],
  );
  const rename = useCallback(
    (next: string) => {
      setName(next);
      void editorRequest(endpoint, "PATCH", { name: next }).catch(() => {});
    },
    [endpoint],
  );
  return {
    endpoint,
    name,
    rename,
    assets,
    assetList,
    jobs,
    refresh,
    doc: history?.present ?? null,
    update,
    undo,
    redo,
    canUndo: !!history?.past.length,
    canRedo: !!history?.future.length,
    save,
    status,
    error,
    words,
    waves,
  };
}
export type Project = ReturnType<typeof useProject>;

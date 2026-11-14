"use client";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, RotateCcw, Scissors, Search, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Range } from "@/components/editor/studio-ui";
import { cn } from "@/lib/utils";
import {
  FILLERS,
  cutRanges,
  cutSavings,
  cutSource,
  findFillers,
  findSilences,
  keptRanges,
  keptWords,
  restoreCuts,
  setWordText,
  timecode,
  timelineTime,
  wordRange,
  type Cut,
  type ProjectDocument,
  type Word,
} from "@/lib/project/document";
import type { Engine } from "./engine";
import type { Project } from "./use-project";

const REASON = { manual: "m", silence: "s", filler: "f", ai: "a" } as const;
const CUT_STYLE: Record<string, string> = {
  m: "text-muted-foreground/60 line-through decoration-destructive/70",
  s: "text-muted-foreground/60 line-through decoration-sky-400/70",
  f: "text-muted-foreground/60 line-through decoration-amber-400/70",
  a: "text-muted-foreground/60 line-through decoration-violet-400/70",
  x: "text-muted-foreground/60 line-through",
};

/** One letter per word: "1" on the timeline, otherwise why it was cut. */
function wordStates(doc: ProjectDocument, asset: string, words: Word[]) {
  const kept = keptWords(words, keptRanges(doc, asset));
  const cuts = doc.cuts.filter((c) => c.asset === asset).sort((a, b) => a.start - b.start);
  let c = 0;
  return words.map((word, i) => {
    if (kept[i]) return "1";
    while (c < cuts.length && cuts[c].end <= word.s) c++;
    // The narrowest record that covers the word names the reason.
    let best: Cut | undefined;
    for (let k = c; k < cuts.length && cuts[k].start <= word.s + 0.001; k++)
      if (cuts[k].end > word.s && (!best || cuts[k].end - cuts[k].start < best.end - best.start)) best = cuts[k];
    return best ? REASON[best.reason] : "x";
  });
}

const Paragraph = memo(function Paragraph({
  words,
  first,
  states,
  texts,
  label,
}: {
  words: Word[];
  first: number;
  /** Joined so an unchanged paragraph is skipped when the rest of the transcript changes. */
  states: string;
  texts: string;
  label: string;
}) {
  const shown = texts.split("\u0001");
  return (
    <p
      className="mb-3 leading-7 [contain-intrinsic-size:auto_84px] [content-visibility:auto]"
      data-first={first}
    >
      <span className="mr-2 select-none text-[10px] tabular-nums text-muted-foreground">{label}</span>
      {words.map((word, k) => {
        const pause = k > 0 ? word.s - words[k - 1].e : 0;
        return (
          <span key={k}>
            {pause >= 1 && (
              <span
                className={cn(
                  "mx-1 select-none rounded bg-muted px-1 text-[10px] text-muted-foreground",
                  states[k] !== "1" && states[k - 1] !== "1" && "line-through opacity-50",
                )}
              >
                {pause.toFixed(1)}s
              </span>
            )}
            <span
              data-i={first + k}
              className={cn(
                "cursor-pointer rounded-sm px-[1px] hover:bg-accent",
                states[k] === "1" ? "" : CUT_STYLE[states[k]],
                shown[k] !== word.t && states[k] === "1" && "underline decoration-dotted underline-offset-4",
              )}
            >
              {shown[k] || "∅"}
            </span>{" "}
          </span>
        );
      })}
    </p>
  );
});

export function TranscriptPanel({ project, engine }: { project: Project; engine: Engine | null }) {
  const doc = project.doc!;
  const { assets, words: allWords, waves, update } = project;
  const spoken = useMemo(
    () => project.assetList.filter((a) => a.transcript && a.transcript !== "none"),
    [project.assetList],
  );
  // Follow the source that fills most of the timeline unless another is picked.
  const busiest = useMemo(() => {
    const seconds = new Map<string, number>();
    for (const clip of doc.clips) if (clip.asset) seconds.set(clip.asset, (seconds.get(clip.asset) ?? 0) + clip.duration);
    return [...spoken].sort((a, b) => (seconds.get(b.id) ?? 0) - (seconds.get(a.id) ?? 0))[0]?.id;
  }, [doc.clips, spoken]);
  const [picked, setPicked] = useState<string | null>(null);
  const assetId = picked && assets[picked] ? picked : busiest;
  const asset = assetId ? assets[assetId] : undefined;
  const words = useMemo(() => (assetId && allWords[assetId]) || [], [allWords, assetId]);
  const states = useMemo(() => (assetId ? wordStates(doc, assetId, words) : []), [doc, assetId, words]);
  const paragraphs = useMemo(() => {
    const result: [number, number][] = [];
    let start = 0;
    for (let i = 1; i <= words.length; i++)
      if (i === words.length || words[i].s - words[i - 1].e > 1.5 || (i - start >= 60 && /[.?!]$/.test(words[i - 1].t)) || i - start >= 120) {
        result.push([start, i]);
        start = i;
      }
    return result;
  }, [words]);

  const body = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<[number, number] | null>(null);
  const [editing, setEditing] = useState<{ index: number; text: string } | null>(null);
  const [query, setQuery] = useState("");
  const [match, setMatch] = useState(0);

  const readSelection = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !body.current?.contains(sel.anchorNode)) return setSelection(null);
    const range = sel.getRangeAt(0);
    const picked = [...body.current.querySelectorAll<HTMLElement>("[data-i]")].filter((el) => range.intersectsNode(el));
    if (!picked.length) return setSelection(null);
    setSelection([Number(picked[0].dataset.i), Number(picked[picked.length - 1].dataset.i)]);
  }, []);
  useEffect(() => {
    document.addEventListener("selectionchange", readSelection);
    return () => document.removeEventListener("selectionchange", readSelection);
  }, [readSelection]);

  const cutSelection = useCallback(() => {
    if (!selection || !assetId) return;
    const [s, e] = wordRange(words, selection[0], selection[1]);
    update((d) => cutSource(d, assetId, s, e, "manual"));
    window.getSelection()?.removeAllRanges();
  }, [assetId, selection, update, words]);
  const restoreSelection = useCallback(() => {
    if (!selection || !assetId) return;
    const s = words[selection[0]].s,
      e = words[selection[1]].e;
    update((d) => restoreCuts(d, (c) => c.asset === assetId && c.start < e && c.end > s));
    window.getSelection()?.removeAllRanges();
  }, [assetId, selection, update, words]);

  // Light up the word being spoken, without re-rendering the transcript on every frame.
  useEffect(() => {
    if (!engine || !assetId) return;
    let lit: Element | null = null;
    const follow = () => {
      const d = engine.doc;
      const clip = d?.clips.find((c) => c.asset === assetId && c.start <= engine.time && engine.time < c.start + c.duration);
      let next: Element | null = null;
      if (clip && words.length) {
        const at = clip.offset + (engine.time - clip.start) * clip.speed;
        let lo = 0,
          hi = words.length;
        while (lo < hi) {
          const mid = (lo + hi) >> 1;
          if (words[mid].s <= at) lo = mid + 1;
          else hi = mid;
        }
        if (lo > 0 && at < words[lo - 1].e + 0.3)
          next = body.current?.querySelector(`[data-i="${lo - 1}"]`) ?? null;
      }
      if (next === lit) return;
      lit?.classList.remove("bg-brand/30", "text-foreground");
      next?.classList.add("bg-brand/30", "text-foreground");
      lit = next;
      if (next && engine.playing) next.scrollIntoView({ block: "nearest" });
    };
    follow();
    const stop = engine.subscribe(follow);
    return () => {
      stop();
      lit?.classList.remove("bg-brand/30", "text-foreground");
    };
  }, [engine, assetId, words, states]);

  const matches = useMemo(() => {
    const tokens = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return [];
    const found: number[] = [];
    for (let i = 0; i + tokens.length <= words.length; i++)
      if (tokens.every((token, k) => words[i + k].t.toLowerCase().includes(token))) found.push(i);
    return found;
  }, [query, words]);
  const goTo = useCallback(
    (index: number) => {
      const element = body.current?.querySelector<HTMLElement>(`[data-i="${index}"]`);
      // Paragraphs far off screen are not laid out yet; scrolling to the paragraph first makes the word real.
      element?.closest("p")?.scrollIntoView({ block: "center" });
      element?.scrollIntoView({ block: "center" });
      const time = assetId ? timelineTime(doc, assetId, words[index].s) : null;
      if (time !== null) engine?.seek(time);
    },
    [assetId, doc, engine, words],
  );

  if (!spoken.length)
    return (
      <Empty>
        Add a recording with speech and its transcript appears here. Delete text to cut the video; the timeline closes
        up by itself.
      </Empty>
    );
  if (!asset) return null;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b p-2">
        {spoken.length > 1 && (
          <select
            aria-label="Transcript of"
            className="h-8 max-w-40 rounded-md border bg-background px-2 text-xs"
            value={assetId}
            onChange={(event) => setPicked(event.target.value)}
          >
            {spoken.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        )}
        <SilenceTool project={project} assetId={asset.id} words={words} wave={waves[asset.id]} />
        <FillerTool project={project} assetId={asset.id} words={words} />
        <div className="relative ml-auto">
          <Search className="pointer-events-none absolute left-2 top-2 size-3.5 text-muted-foreground" />
          <Input
            aria-label="Find in transcript"
            placeholder="Find"
            className="h-8 w-32 pl-7 text-xs"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setMatch(0);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || !matches.length) return;
              const next = (match + (event.shiftKey ? -1 : 1) + matches.length) % matches.length;
              setMatch(next);
              goTo(matches[next]);
            }}
          />
          {query && (
            <span className="absolute right-2 top-2 text-[10px] text-muted-foreground">
              {matches.length ? `${match + 1}/${matches.length}` : "0"}
            </span>
          )}
        </div>
      </div>
      {selection && (
        <div className="flex items-center gap-2 border-b bg-accent/40 px-3 py-1.5 text-xs">
          <span className="text-muted-foreground">
            {selection[1] - selection[0] + 1} words · {(words[selection[1]].e - words[selection[0]].s).toFixed(1)}s
          </span>
          <Button size="sm" variant="destructive" className="ml-auto h-7" onMouseDown={(e) => e.preventDefault()} onClick={cutSelection}>
            <Scissors /> Cut
          </Button>
          <Button size="sm" variant="outline" className="h-7" onMouseDown={(e) => e.preventDefault()} onClick={restoreSelection}>
            <RotateCcw /> Restore
          </Button>
        </div>
      )}
      {asset.transcript === "pending" && (
        <Empty>
          <Loader2 className="mx-auto mb-2 size-5 animate-spin" />
          Listening to {asset.name}. You can start cutting on the timeline meanwhile.
        </Empty>
      )}
      {asset.transcript === "failed" && <Empty>The transcript could not be made for this file. Right-click it in the media bin to try again.</Empty>}
      {asset.transcript === "ready" && !words.length && <Empty>No speech was found in this file.</Empty>}
      <div
        ref={body}
        tabIndex={0}
        role="textbox"
        aria-label="Transcript"
        aria-multiline
        aria-readonly
        className="min-h-0 flex-1 overflow-y-auto px-4 py-3 text-sm outline-none"
        onKeyDown={(event) => {
          if ((event.key === "Delete" || event.key === "Backspace") && selection) {
            event.preventDefault();
            event.stopPropagation();
            cutSelection();
          }
        }}
        onClick={(event) => {
          const target = (event.target as HTMLElement).closest<HTMLElement>("[data-i]");
          if (!target || !window.getSelection()?.isCollapsed) return;
          goTo(Number(target.dataset.i));
        }}
        onDoubleClick={(event) => {
          const target = (event.target as HTMLElement).closest<HTMLElement>("[data-i]");
          if (!target) return;
          const index = Number(target.dataset.i);
          setEditing({ index, text: doc.wordEdits[asset.id]?.[index] ?? words[index].t });
        }}
      >
        {paragraphs.map(([a, b]) => {
          const at = timelineTime(doc, asset.id, words.slice(a, b).find((_, k) => states[a + k] === "1")?.s ?? -1);
          return (
            <Paragraph
              key={a}
              first={a}
              words={words.slice(a, b)}
              states={states.slice(a, b).join("")}
              texts={words.slice(a, b).map((w, k) => doc.wordEdits[asset.id]?.[a + k] ?? w.t).join("\u0001")}
              label={at === null ? "cut" : timecode(at)}
            />
          );
        })}
      </div>
      {editing && (
        <form
          className="flex items-center gap-2 border-t p-2"
          onSubmit={(event) => {
            event.preventDefault();
            update((d) => setWordText(d, asset.id, editing.index, editing.text.trim()));
            setEditing(null);
          }}
        >
          <span className="text-xs text-muted-foreground">Caption text</span>
          <Input
            autoFocus
            aria-label="Corrected word"
            className="h-8 flex-1 text-sm"
            value={editing.text}
            onChange={(event) => setEditing({ ...editing, text: event.target.value })}
            onKeyDown={(event) => event.key === "Escape" && setEditing(null)}
          />
          <Button size="sm" type="submit" className="h-8">
            Save
          </Button>
        </form>
      )}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="p-6 text-center text-sm leading-relaxed text-muted-foreground">{children}</div>;
}

function Savings({ count, seconds, noun }: { count: number; seconds: number; noun: string }) {
  return (
    <p className="rounded-md bg-muted px-3 py-2 text-xs">
      {count ? (
        <>
          <b>{count}</b> {noun}
          {count === 1 ? "" : "s"}, <b>{timecode(seconds)}</b> shorter
        </>
      ) : (
        `No ${noun}s found on the timeline`
      )}
    </p>
  );
}

function SilenceTool({ project, assetId, words, wave }: { project: Project; assetId: string; words: Word[]; wave?: Uint8Array }) {
  const doc = project.doc!,
    asset = project.assets[assetId];
  const [open, setOpen] = useState(false);
  const [minPause, setMinPause] = useState(1);
  const [padding, setPadding] = useState(0.15);
  const [keepLoud, setKeepLoud] = useState(false);
  const ranges = useMemo(
    () => (open ? findSilences(words, asset.duration, { minPause, padding, keepLoud }, wave, asset.waveRate) : []),
    [open, words, asset, minPause, padding, keepLoud, wave],
  );
  const savings = useMemo(() => cutSavings(doc, assetId, ranges), [doc, assetId, ranges]);
  const existing = doc.cuts.filter((c) => c.asset === assetId && c.reason === "silence").length;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="outline" className="h-8" disabled={!words.length}>
          <Sparkles /> Remove silences
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-4">
        <Range label="Cut pauses longer than" value={minPause} min={0.3} max={5} step={0.1} unit=" s" onChange={setMinPause} />
        <Range label="Leave around speech" value={padding} min={0} max={0.5} step={0.05} unit=" s" onChange={setPadding} />
        <label className="flex items-start gap-2 text-xs leading-relaxed">
          <Checkbox checked={keepLoud} onCheckedChange={(value) => setKeepLoud(value === true)} className="mt-0.5" />
          <span>
            Keep pauses where the sound stays loud
            <span className="block text-muted-foreground">For gameplay moments when nobody is talking.</span>
          </span>
        </label>
        <Savings {...savings} noun="pause" />
        <div className="flex gap-2">
          <Button
            size="sm"
            className="flex-1"
            disabled={!savings.count}
            onClick={() => {
              project.update((d) => cutRanges(d, assetId, ranges, "silence"));
              setOpen(false);
            }}
          >
            Remove {savings.count || ""} pauses
          </Button>
          {existing > 0 && (
            <Button size="sm" variant="outline" onClick={() => project.update((d) => restoreCuts(d, (c) => c.asset === assetId && c.reason === "silence"))}>
              Put {existing} back
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function FillerTool({ project, assetId, words }: { project: Project; assetId: string; words: Word[] }) {
  const doc = project.doc!;
  const [open, setOpen] = useState(false);
  const [list, setList] = useState(FILLERS.join(", "));
  const ranges = useMemo(() => (open ? findFillers(words, list.split(",")) : []), [open, words, list]);
  const savings = useMemo(() => cutSavings(doc, assetId, ranges), [doc, assetId, ranges]);
  const existing = doc.cuts.filter((c) => c.asset === assetId && c.reason === "filler").length;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="outline" className="h-8" disabled={!words.length}>
          <Sparkles /> Remove filler words
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-4">
        <label className="block space-y-2 text-xs text-muted-foreground">
          Words and phrases to remove, separated by commas
          <textarea
            className="h-20 w-full rounded-md border bg-background p-2 text-sm text-foreground"
            value={list}
            onChange={(event) => setList(event.target.value)}
          />
        </label>
        <Savings {...savings} noun="filler" />
        <div className="flex gap-2">
          <Button
            size="sm"
            className="flex-1"
            disabled={!savings.count}
            onClick={() => {
              project.update((d) => cutRanges(d, assetId, ranges, "filler"));
              setOpen(false);
            }}
          >
            Remove {savings.count || ""} fillers
          </Button>
          {existing > 0 && (
            <Button size="sm" variant="outline" onClick={() => project.update((d) => restoreCuts(d, (c) => c.asset === assetId && c.reason === "filler"))}>
              Put {existing} back
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

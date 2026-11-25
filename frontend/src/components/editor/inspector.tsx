"use client";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import {
  AlignCenter,
  Bookmark,
  Captions,
  Crop,
  Highlighter,
  Info,
  Maximize2,
  Palette,
  Plus,
  RotateCcw,
  Trash2,
  Volume2,
  VolumeX,
  ZoomIn,
} from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Input } from "@/components/ui/input";
import { loadEditorFont } from "@/lib/editor/render";
import {
  CAPTION_FONTS,
  DEFAULT_EFFECTS,
  clamp,
  isSwear,
  loudestMoment,
  paintSpeaker,
  replaceWords,
  speakerCount,
  SPEAKER_COLORS,
  timecode,
  wordColor,
  uid,
  type EditDocument,
  type CaptionAnimation,
  type CaptionStyle,
  type EditorState,
  type Framing,
  type Region,
} from "@/lib/editor/document";
import { cn } from "@/lib/utils";
import { Field, Range, Section } from "./studio-ui";
export type InspectorTab = "captions" | "layout" | "audio" | "effects";

const TABS = [
  ["captions", "Captions", Captions],
  ["layout", "Layout", Crop],
  ["audio", "Audio", Volume2],
  ["effects", "Effects", Palette],
] as const;

function ColorField({
  label,
  inputLabel,
  value,
  onChange,
}: {
  label: string;
  inputLabel: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label}>
      <div className="flex h-9 items-center gap-2 rounded-md border bg-transparent pl-1.5 pr-2 shadow-xs focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50">
        <input
          aria-label={inputLabel}
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="size-6 shrink-0 cursor-pointer rounded border-0 ring-1 ring-border bg-transparent p-0 outline-none [&::-moz-color-swatch]:rounded [&::-moz-color-swatch]:border-0 [&::-webkit-color-swatch]:rounded [&::-webkit-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0"
        />
        <span className="font-mono text-xs uppercase text-muted-foreground">
          {value}
        </span>
      </div>
    </Field>
  );
}

function SwitchRow({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <Label htmlFor={id} className="text-sm font-normal">
        {label}
      </Label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

/**
 * One-click looks; each sets every style field it shows so presets never mix.
 * The same rows are in backend/src/caption_templates.py, so new clips can be made with a look.
 */
export const PRESETS: [string, Partial<CaptionStyle>][] = [
  ["Clean", { font: "TikTokSans-Bold", color: "#FFFFFF", accent: "#FACC15", background: false, uppercase: false, outline: 5, active: false, animation: "fade", wordsPerLine: 4 }],
  ["Karaoke", { font: "Poppins-ExtraBold", color: "#FFFFFF", accent: "#FACC15", background: false, uppercase: false, outline: 6, active: true, animation: "pop", wordsPerLine: 4 }],
  ["Hype", { font: "THEBOLDFONT", color: "#FFFFFF", accent: "#A3E635", background: false, uppercase: true, outline: 7, active: true, animation: "pop", wordsPerLine: 3 }],
  ["Impact", { font: "Anton-Regular", color: "#FFFFFF", accent: "#FB7185", background: false, uppercase: true, outline: 5, active: true, animation: "slide", wordsPerLine: 3 }],
  ["Comic", { font: "Bangers-Regular", color: "#FDE047", accent: "#FFFFFF", background: false, uppercase: true, outline: 7, active: true, animation: "pop", wordsPerLine: 3 }],
  ["Boxed", { font: "TikTokSans-Regular", color: "#FFFFFF", accent: "#FACC15", background: true, uppercase: false, outline: 0, active: true, animation: "fade", wordsPerLine: 5 }],
  ["Solo", { font: "Poppins-ExtraBold", color: "#FFFFFF", accent: "#FACC15", background: false, uppercase: true, outline: 7, active: false, animation: "pop", wordsPerLine: 1 }],
  ["Arcade", { font: "Bangers-Regular", color: "#A3E635", accent: "#FFFFFF", background: false, uppercase: true, outline: 7, active: true, animation: "pop", wordsPerLine: 2 }],
  ["Cyber", { font: "BebasNeue-Regular", color: "#67E8F9", accent: "#F0ABFC", background: false, uppercase: true, outline: 5, active: true, animation: "fade", wordsPerLine: 3 }],
  ["Sunset", { font: "ArchivoBlack-Regular", color: "#FFFFFF", accent: "#FB923C", background: false, uppercase: false, outline: 6, active: true, animation: "slide", wordsPerLine: 3 }],
  ["Stream", { font: "TikTokSans-Bold", color: "#FFFFFF", accent: "#C084FC", background: true, uppercase: true, outline: 0, active: true, animation: "pop", wordsPerLine: 3 }],
  ["Soft", { font: "TikTokSans-Regular", color: "#FFFFFF", accent: "#FDE68A", background: false, uppercase: false, outline: 3, active: false, animation: "fade", wordsPerLine: 6 }],
];

const LAYOUTS: [string, Partial<Framing>, ReactNode][] = [
  ["Fill", { layout: "crop", fit: "cover" }, <i key="g" className="absolute inset-0 bg-brand/70" />],
  [
    "Fit",
    { layout: "crop", fit: "contain" },
    <i key="g" className="absolute inset-x-0 top-[34%] h-[32%] bg-brand/70" />,
  ],
  [
    "Cam top",
    { layout: "cam_top" },
    <>
      <i className="absolute inset-x-0 top-0 h-[40%] bg-sky-400/80" />
      <i className="absolute inset-x-0 bottom-0 h-[58%] bg-brand/70" />
    </>,
  ],
  [
    "Cam bottom",
    { layout: "cam_bottom" },
    <>
      <i className="absolute inset-x-0 top-0 h-[58%] bg-brand/70" />
      <i className="absolute inset-x-0 bottom-0 h-[40%] bg-sky-400/80" />
    </>,
  ],
  [
    "Floating cam",
    { layout: "floating" },
    <>
      <i className="absolute inset-x-0 top-[38%] h-[32%] bg-brand/70" />
      <i className="absolute inset-x-[20%] top-[12%] h-[22%] bg-sky-400/80" />
    </>,
  ],
];

/**
 * The source frame with the facecam box: drag the box to move it, drag elsewhere to draw a new one.
 * The small one in the panel opens a big one (`onTap`) when it is tapped without dragging.
 */
function FacecamPicker({
  video,
  time,
  cam,
  onChange,
  onTap,
}: {
  video: RefObject<HTMLVideoElement | null>;
  time: number;
  cam: Region;
  onChange: (cam: Region) => void;
  onTap?: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{
    x: number;
    y: number;
    cam: Region;
    move: boolean;
    dragged?: boolean;
  } | null>(null);
  useEffect(() => {
    const source = video.current,
      ctx = canvas.current?.getContext("2d");
    if (!ctx || !source) return;
    const paint = () => {
      if (source.readyState >= 2)
        ctx.drawImage(source, 0, 0, ctx.canvas.width, ctx.canvas.height);
    };
    paint();
    source.addEventListener("seeked", paint);
    return () => source.removeEventListener("seeked", paint);
  }, [video, time]);
  const point = (e: React.PointerEvent) => {
    const box = e.currentTarget.getBoundingClientRect();
    return {
      x: clamp((e.clientX - box.left) / box.width, 0, 1),
      y: clamp((e.clientY - box.top) / box.height, 0, 1),
    };
  };
  return (
    <div
      aria-label="Facecam area"
      className="relative aspect-video w-full cursor-crosshair touch-none overflow-hidden rounded-md bg-black"
      onPointerDown={(e) => {
        const p = point(e);
        drag.current = {
          ...p,
          cam,
          move:
            p.x >= cam.x &&
            p.x <= cam.x + cam.w &&
            p.y >= cam.y &&
            p.y <= cam.y + cam.h,
        };
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d) return;
        const p = point(e);
        if (Math.abs(p.x - d.x) + Math.abs(p.y - d.y) > 0.02) d.dragged = true;
        if (d.move)
          onChange({
            ...d.cam,
            x: clamp(d.cam.x + p.x - d.x, 0, 1 - d.cam.w),
            y: clamp(d.cam.y + p.y - d.y, 0, 1 - d.cam.h),
          });
        else if (Math.abs(p.x - d.x) >= 0.05 && Math.abs(p.y - d.y) >= 0.05)
          onChange({
            x: Math.min(p.x, d.x),
            y: Math.min(p.y, d.y),
            w: Math.abs(p.x - d.x),
            h: Math.abs(p.y - d.y),
          });
      }}
      onPointerUp={() => {
        if (drag.current && !drag.current.dragged) onTap?.();
        drag.current = null;
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
    >
      <canvas
        ref={canvas}
        width={onTap ? 320 : 1280}
        height={onTap ? 180 : 720}
        className="h-full w-full opacity-60"
      />
      <div
        className="absolute cursor-move rounded-sm border-2 border-sky-400 bg-sky-400/20"
        style={{
          left: `${cam.x * 100}%`,
          top: `${cam.y * 100}%`,
          width: `${cam.w * 100}%`,
          height: `${cam.h * 100}%`,
        }}
      />
    </div>
  );
}

interface Props {
  doc: EditDocument;
  asset: EditorState;
  tab: InspectorTab;
  setTab: (tab: InspectorTab) => void;
  time: number;
  seek: (value: number) => void;
  update: (change: (doc: EditDocument) => EditDocument, group?: string) => void;
  applyAll: (style: CaptionStyle) => Promise<void>;
  videoRef: RefObject<HTMLVideoElement | null>;
  /** The AI's hook title for this clip, offered as the on-screen title. */
  suggestedTitle?: string | null;
}
export function Inspector({
  doc,
  asset,
  tab,
  setTab,
  time,
  seek,
  update,
  applyAll,
  videoRef,
  suggestedTitle,
}: Props) {
  const [wordId, setWordId] = useState<string | null>(null);
  const [camBig, setCamBig] = useState(false);
  const [, setFontsReady] = useState(0);
  useEffect(() => {
    // Preset tiles are drawn in their own fonts.
    for (const [, style] of PRESETS)
      void loadEditorFont(style.font!).then(
        () => setFontsReady((n) => n + 1),
        () => {},
      );
  }, []);
  const frame = (change: Partial<Framing>, group?: string) =>
    update((d) => ({ ...d, framing: { ...d.framing, ...change } }), group);
  const word = (id: string, change: Partial<EditDocument["words"][number]>, group?: string) =>
    update(
      (d) => ({
        ...d,
        words: d.words.map((w) => (w.id === id ? { ...w, ...change } : w)),
      }),
      group,
    );
  const punch = (start: number) =>
    update((d) => ({
      ...d,
      punches: [...d.punches, { id: uid(), start, end: start + 1.2 }].slice(-50),
    }));
  const picked = doc.words.find((w) => w.id === wordId),
    pickedIndex = picked ? doc.words.indexOf(picked) : -1;
  const layout = doc.framing.aspect === "original" ? "crop" : doc.framing.layout;
  const scriptWords = useRef(doc.words);
  const [script, setScript] = useState<string | null>(null),
    [applying, setApplying] = useState(false);
  const swearCount = doc.words.filter((w) => isSwear(w.text)).length,
    allBleeped =
      swearCount > 0 &&
      doc.words.every((w) => !isSwear(w.text) || w.bleep);
  const caption = (change: Partial<CaptionStyle>, group = "caption-style") =>
    update((d) => ({ ...d, captions: { ...d.captions, ...change } }), group);
  const speakers = speakerCount(doc.words),
    speakerColors = doc.captions.speakerColors ?? SPEAKER_COLORS,
    speakerColor = (speaker: number) => wordColor(doc.captions, { speaker });
  return (
    <aside
      aria-label="Editor tools"
      className="flex min-h-0 w-full shrink-0 flex-col border-l bg-card text-card-foreground lg:w-[360px]"
    >
      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value as InspectorTab)}
        className="min-h-0 flex-1 gap-0"
      >
        <div className="border-b p-2">
          <TabsList className="grid w-full grid-cols-4 group-data-[orientation=horizontal]/tabs:h-auto">
            {TABS.map(([id, label, Icon]) => (
              <TabsTrigger
                key={id}
                value={id}
                className="h-auto flex-col gap-1 py-2 text-xs"
              >
                <Icon />
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <TabsContent value="captions" className="space-y-6 p-4">
            <Section
              title="Captions"
              description="Pick a look. Fine-tune it under Customise."
              action={
                <Switch
                  aria-label="Show captions"
                  checked={doc.captions.enabled}
                  onCheckedChange={(enabled) => caption({ enabled })}
                />
              }
            >
              <div className="grid grid-cols-3 gap-2">
                {PRESETS.map(([name, style]) => {
                  const active = Object.entries(style).every(
                    ([key, value]) =>
                      String(doc.captions[key as keyof CaptionStyle]).toUpperCase() ===
                      String(value).toUpperCase(),
                  );
                  const outline = style.background
                    ? undefined
                    : `${(style.outline ?? 0) / 4}px #101010`;
                  return (
                    <button
                      key={name}
                      aria-label={name}
                      aria-pressed={active}
                      className={cn(
                        "rounded-lg border p-1 text-left transition-colors outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50",
                        active && "border-brand ring-1 ring-brand",
                      )}
                      onClick={() => caption(style)}
                    >
                      <span
                        className="flex h-12 items-center justify-center rounded-md bg-stone-700 text-[15px] leading-none"
                        style={{
                          fontFamily: `"Editor-${style.font}", sans-serif`,
                          color: style.color,
                          textTransform: style.uppercase ? "uppercase" : undefined,
                          WebkitTextStroke: outline,
                          paintOrder: "stroke fill",
                        }}
                      >
                        <span className={cn("px-1 py-0.5", style.background && "bg-[#101010]")}>
                          No <span style={{ color: style.accent }}>way</span>
                        </span>
                      </span>
                      <span className="block px-0.5 pt-1 text-[11px] font-medium">
                        {name}
                      </span>
                    </button>
                  );
                })}
              </div>
            </Section>
            <Separator />
            <Section
              title="Speakers"
              description={
                speakers > 1
                  ? `${speakers} voices in this clip. Pick a caption colour for each.`
                  : "One voice in this clip. To colour someone else, click their first word in the transcript and pick a speaker."
              }
            >
              <div className="grid grid-cols-2 gap-3">
                {Array.from({ length: speakers }, (_, speaker) => (
                  <ColorField
                    key={speaker}
                    label={`Speaker ${speaker + 1}`}
                    inputLabel={`Speaker ${speaker + 1} color`}
                    value={speakerColor(speaker)}
                    onChange={(color) =>
                      caption(
                        speaker
                          ? {
                              speakerColors: speakerColors.map((c, i) =>
                                i === speaker - 1 ? color : c,
                              ),
                            }
                          : { color },
                      )
                    }
                  />
                ))}
              </div>
            </Section>
            <Separator />
            <Section
              title={
                <>
                  Transcript{" "}
                  <span className="font-normal text-muted-foreground">
                    · {doc.words.length} words
                  </span>
                </>
              }
              description="Type over any word. Its timing stays put."
              action={
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-xs"
                  onClick={() => {
                    scriptWords.current = doc.words;
                    setScript(
                      script === null
                        ? doc.words.map((w) => w.text).join(" ")
                        : null,
                    );
                  }}
                >
                  {script === null ? "Edit as text" : "Close"}
                </Button>
              }
            >
              {script !== null && (
                <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
                  <Textarea
                    className="min-h-24 bg-background text-sm"
                    aria-label="Subtitle text"
                    value={script}
                    onChange={(e) => {
                      const text = e.target.value;
                      setScript(text);
                      try {
                        update(
                          (d) => ({
                            ...d,
                            words: replaceWords(
                              scriptWords.current,
                              text,
                              asset.duration,
                            ),
                          }),
                          "script",
                        );
                      } catch (error) {
                        toast.error((error as Error).message);
                      }
                    }}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs text-muted-foreground">
                      Existing words keep their timing. Review the timing of
                      inserted words.
                    </p>
                    <Button
                      size="sm"
                      onClick={() => {
                        try {
                          update((d) => ({
                            ...d,
                            words: replaceWords(
                              scriptWords.current,
                              script,
                              asset.duration,
                            ),
                          }));
                          setScript(null);
                        } catch (e) {
                          toast.error((e as Error).message);
                        }
                      }}
                    >
                      Apply script
                    </Button>
                  </div>
                </div>
              )}
              <div
                role="list"
                className="flex max-h-64 flex-wrap gap-x-0.5 gap-y-1 overflow-y-auto rounded-lg border p-2"
              >
                {doc.words.map((w, i) => (
                  <input
                    key={w.id}
                    role="listitem"
                    aria-label={`Word ${i + 1}`}
                    maxLength={120}
                    value={w.text}
                    size={Math.max(1, w.text.length)}
                    onFocus={() => {
                      setWordId(w.id);
                      seek(w.start);
                    }}
                    onChange={(e) =>
                      word(w.id, { text: e.target.value }, `word-${w.id}`)
                    }
                    style={w.speaker ? { color: speakerColor(w.speaker) } : undefined}
                    className={cn(
                      "h-7 rounded-md bg-transparent px-1 text-sm outline-none [field-sizing:content] hover:bg-accent focus:bg-accent",
                      time >= w.start && time < w.end && "bg-accent",
                      w.highlight && "font-semibold text-brand",
                      w.bleep && "text-red-400 line-through",
                      w.id === wordId && "ring-1 ring-brand",
                    )}
                  />
                ))}
              </div>
              {picked ? (
                <div className="flex flex-wrap items-center gap-1 rounded-lg border bg-muted/40 p-1.5">
                  <Button
                    size="sm"
                    variant={picked.highlight ? "secondary" : "ghost"}
                    className="h-7 px-2 text-xs"
                    aria-label={`Highlight word ${pickedIndex + 1}`}
                    aria-pressed={picked.highlight}
                    onClick={() => word(picked.id, { highlight: !picked.highlight })}
                  >
                    <Highlighter />
                    Highlight
                  </Button>
                  <Button
                    size="sm"
                    variant={picked.bleep ? "secondary" : "ghost"}
                    className="h-7 px-2 text-xs"
                    aria-label={`Bleep word ${pickedIndex + 1}`}
                    aria-pressed={Boolean(picked.bleep)}
                    onClick={() => word(picked.id, { bleep: !picked.bleep })}
                  >
                    <VolumeX />
                    Bleep
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    className="size-7 hover:text-destructive"
                    aria-label={`Delete word ${pickedIndex + 1}`}
                    onClick={() => {
                      update((d) => ({
                        ...d,
                        words: d.words.filter((w) => w.id !== picked.id),
                      }));
                      setWordId(null);
                    }}
                  >
                    <Trash2 />
                  </Button>
                  <span
                    role="group"
                    aria-label="Speaker from this word on"
                    title="Who says this? Applies from this word until the speaker changes."
                    className="flex items-center gap-1 px-1"
                  >
                    {Array.from(
                      { length: Math.min(speakers + 1, SPEAKER_COLORS.length + 1) },
                      (_, speaker) => (
                        <button
                          key={speaker}
                          type="button"
                          aria-label={`Speaker ${speaker + 1} from word ${pickedIndex + 1}`}
                          aria-pressed={(picked.speaker ?? 0) === speaker}
                          onClick={() =>
                            update((d) => ({
                              ...d,
                              words: paintSpeaker(d.words, picked.id, speaker),
                            }))
                          }
                          style={{ background: speakerColor(speaker) }}
                          className={cn(
                            "grid size-5 place-items-center rounded-full text-[10px] font-bold text-black ring-1 ring-border outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            (picked.speaker ?? 0) === speaker &&
                              "ring-2 ring-brand",
                          )}
                        >
                          {speaker + 1}
                        </button>
                      ),
                    )}
                  </span>
                  <span className="ml-auto flex items-center gap-1 text-[11px] tabular-nums text-muted-foreground">
                    {(["start", "end"] as const).map((edge) => (
                      <input
                        key={edge}
                        aria-label={`Word ${pickedIndex + 1} ${edge}`}
                        title={`Word ${edge} (seconds)`}
                        className="w-12 rounded-sm bg-background px-1 py-0.5 outline-none [appearance:textfield] focus:ring-2 focus:ring-ring/50 [&::-webkit-inner-spin-button]:appearance-none"
                        type="number"
                        min={0}
                        max={asset.duration}
                        step="0.01"
                        value={Number(picked[edge].toFixed(2))}
                        onChange={(e) =>
                          word(
                            picked.id,
                            edge === "start"
                              ? {
                                  start: clamp(
                                    Number(e.target.value),
                                    0,
                                    picked.end - 0.01,
                                  ),
                                }
                              : {
                                  end: clamp(
                                    Number(e.target.value),
                                    picked.start + 0.01,
                                    asset.duration,
                                  ),
                                },
                            `timing-${picked.id}`,
                          )
                        }
                      />
                    ))}
                  </span>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Click a word to jump to it, fix it, highlight it or bleep it.
                </p>
              )}
              <Button
                size="sm"
                variant="outline"
                className="w-full"
                onClick={() =>
                  update((d) => ({
                    ...d,
                    words: [
                      ...d.words,
                      {
                        id: uid(),
                        text: "New",
                        start: Math.min(time, asset.duration - 0.1),
                        end: Math.min(asset.duration, time + 0.5),
                        highlight: false,
                      },
                    ].sort((a, b) => a.start - b.start),
                  }))
                }
              >
                <Plus />
                Add word at playhead
              </Button>
            </Section>
            <Separator />
            <Section
              title="Hook title"
              description="Shown at the top in the caption style. Set the time to 0 to keep it up for the whole clip."
            >
              <Input
                aria-label="Hook title"
                placeholder="No title"
                maxLength={80}
                value={doc.title}
                onChange={(e) =>
                  update((d) => ({ ...d, title: e.target.value }), "title")
                }
              />
              {suggestedTitle && doc.title !== suggestedTitle && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-auto w-full justify-start py-1.5 text-left whitespace-normal"
                  onClick={() =>
                    update((d) => ({ ...d, title: suggestedTitle.slice(0, 80) }))
                  }
                >
                  Use “{suggestedTitle}”
                </Button>
              )}
              <Range
                label="Title stays for"
                value={doc.titleSeconds}
                min={0}
                max={30}
                step={0.5}
                unit="s"
                onChange={(titleSeconds) =>
                  update((d) => ({ ...d, titleSeconds }), "titleSeconds")
                }
              />
            </Section>
            <Separator />
            <Field label="Entrance">
              <ToggleGroup
                type="single"
                variant="outline"
                aria-label="Caption entrance"
                className="w-full"
                value={doc.captions.animation ?? "none"}
                onValueChange={(animation) =>
                  animation && caption({ animation: animation as CaptionAnimation })
                }
              >
                {(["none", "pop", "fade", "slide"] as const).map((value) => (
                  <ToggleGroupItem key={value} value={value} className="flex-1 capitalize">
                    {value}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </Field>
            <details className="group space-y-4" open={false}>
              <summary className="cursor-pointer text-sm font-semibold select-none">
                Customise the style
              </summary>
              <div className="space-y-4 pt-4">
              <Field label="Font">
                <Select
                  value={doc.captions.font}
                  onValueChange={(font) =>
                    caption({ font: font as CaptionStyle["font"] })
                  }
                >
                  <SelectTrigger aria-label="Caption font" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(CAPTION_FONTS).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Range
                label="Subtitle size"
                value={doc.captions.size}
                min={20}
                max={100}
                onChange={(size) => caption({ size })}
              />
              <Range
                label="Subtitle vertical position"
                value={doc.captions.y * 100}
                min={10}
                max={90}
                unit="%"
                onChange={(y) => caption({ y: y / 100 })}
              />
              <div className="grid grid-cols-2 gap-3">
                <ColorField
                  label="Text"
                  inputLabel="Caption text color"
                  value={doc.captions.color}
                  onChange={(color) => caption({ color })}
                />
                <ColorField
                  label="Highlight"
                  inputLabel="Highlight color"
                  value={doc.captions.accent}
                  onChange={(accent) => caption({ accent })}
                />
              </div>
              <SwitchRow
                id="caption-active"
                label="Light up the word being spoken"
                checked={doc.captions.active}
                onChange={(active) => caption({ active })}
              />
              <SwitchRow
                id="caption-uppercase"
                label="ALL CAPS"
                checked={doc.captions.uppercase}
                onChange={(uppercase) => caption({ uppercase })}
              />
              {!doc.captions.background && (
                <Range
                  label="Outline"
                  value={doc.captions.outline}
                  min={0}
                  max={12}
                  step={0.5}
                  onChange={(outline) => caption({ outline })}
                />
              )}
              <SwitchRow
                id="caption-background"
                label="Text background"
                checked={doc.captions.background}
                onChange={(background) => caption({ background })}
              />
              <div className="flex items-center justify-between gap-3">
                <Label className="text-sm font-normal">Words per caption</Label>
                <Select
                  value={String(doc.captions.wordsPerLine)}
                  onValueChange={(n) => caption({ wordsPerLine: Number(n) })}
                >
                  <SelectTrigger
                    size="sm"
                    aria-label="Words per caption"
                    className="w-16 tabular-nums"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    try {
                      localStorage.setItem(
                        "localclip-caption-style",
                        JSON.stringify(doc.captions),
                      );
                      toast.success("Caption style saved");
                    } catch {
                      toast.error("Could not save style on this device");
                    }
                  }}
                >
                  <Bookmark />
                  Save style
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    try {
                      const style = JSON.parse(
                        localStorage.getItem("localclip-caption-style") ||
                          "null",
                      );
                      if (style?.font && style?.size) caption(style);
                      else toast.info("Save a style first");
                    } catch {
                      toast.error("Could not load saved style");
                    }
                  }}
                >
                  Load style
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  className="col-span-2"
                  disabled={applying}
                  onClick={async () => {
                    setApplying(true);
                    try {
                      await applyAll(doc.captions);
                    } finally {
                      setApplying(false);
                    }
                  }}
                >
                  {applying ? "Applying…" : "Apply to all clips"}
                </Button>
              </div>
              </div>
            </details>
          </TabsContent>
          <TabsContent value="layout" className="space-y-6 p-4">
            <Section title="Format">
              <ToggleGroup
                type="single"
                variant="outline"
                aria-label="Aspect ratio"
                className="w-full"
                value={doc.framing.aspect}
                onValueChange={(aspect) =>
                  aspect && frame({ aspect: aspect as Framing["aspect"] })
                }
              >
                {(
                  [
                    ["vertical", "9:16", "Vertical"],
                    ["square", "1:1", "Square"],
                    ["original", "Src", "Original"],
                  ] as const
                ).map(([value, ratio, label]) => (
                  <ToggleGroupItem
                    key={value}
                    value={value}
                    aria-label={label}
                    className="h-auto flex-1 flex-col gap-0.5 py-2"
                  >
                    <span className="text-sm font-semibold">{ratio}</span>
                    <span className="text-[11px] font-normal text-muted-foreground">
                      {label}
                    </span>
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </Section>
            {doc.framing.aspect !== "original" && (
              <>
                <Separator />
                <Section
                  title="Layout"
                  description="How your facecam and gameplay share the frame."
                >
                  <div className="grid grid-cols-5 gap-1.5">
                    {LAYOUTS.map(([name, change, art]) => {
                      const active =
                        layout === change.layout &&
                        (!change.fit || doc.framing.fit === change.fit);
                      return (
                        <button
                          key={name}
                          aria-pressed={active}
                          className={cn(
                            "rounded-lg border p-1.5 text-center transition-colors outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50",
                            active && "border-brand ring-1 ring-brand",
                          )}
                          onClick={() => frame(change)}
                        >
                          <span
                            aria-hidden
                            className="relative mx-auto block aspect-[9/16] w-7 overflow-hidden rounded-sm bg-stone-700"
                          >
                            {art}
                          </span>
                          <span className="mt-1 block text-[10px] leading-tight font-medium">
                            {name}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </Section>
              </>
            )}
            {layout !== "crop" && (
              <Section
                title="Facecam"
                description="Drag the blue box over your camera, or drag anywhere else to draw a new one. Tap it to make it bigger."
              >
                <FacecamPicker
                  video={videoRef}
                  time={time}
                  cam={doc.framing.cam}
                  onChange={(cam) => frame({ cam }, "cam")}
                  onTap={() => setCamBig(true)}
                />
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  onClick={() => setCamBig(true)}
                >
                  <Maximize2 />
                  Make it bigger
                </Button>
                <SwitchRow
                  id="sharp-cam"
                  label="Sharpen facecam with AI"
                  checked={!!doc.framing.sharpCam}
                  onChange={(sharpCam) => frame({ sharpCam })}
                />
                {doc.framing.sharpCam && (
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Upscales a small, blurry camera when you export. It is slow
                    (minutes per clip), uses your graphics card, and downloads
                    the upscaler (45 MB) the first time. The preview stays as it is.
                  </p>
                )}
                <Dialog open={camBig} onOpenChange={setCamBig}>
                  {/* As wide as fits while the whole 16:9 frame stays on screen. */}
                  <DialogContent className="w-[min(calc(100vw-2rem),calc((100vh-11rem)*16/9))] max-w-none">
                    <DialogHeader>
                      <DialogTitle>Facecam</DialogTitle>
                      <DialogDescription>
                        Drag the blue box over your camera, or drag anywhere else to draw a
                        new one.
                      </DialogDescription>
                    </DialogHeader>
                    <FacecamPicker
                      video={videoRef}
                      time={time}
                      cam={doc.framing.cam}
                      onChange={(cam) => frame({ cam }, "cam")}
                    />
                    <Button className="justify-self-end" onClick={() => setCamBig(false)}>
                      Done
                    </Button>
                  </DialogContent>
                </Dialog>
              </Section>
            )}
            {layout !== "floating" && (
              <>
                <Separator />
                <Section
                  title={layout === "crop" ? "Position" : "Gameplay"}
                  description="Or just drag the video in the preview."
                >
                  <Range
                    label="Zoom"
                    min={1}
                    max={3}
                    step={0.01}
                    value={doc.framing.zoom}
                    unit="×"
                    onChange={(zoom) => frame({ zoom }, "zoom")}
                  />
                  <Range
                    label="Horizontal position"
                    min={0}
                    max={100}
                    value={doc.framing.x * 100}
                    unit="%"
                    onChange={(x) => frame({ x: x / 100 }, "position")}
                  />
                  <Range
                    label="Vertical position"
                    min={0}
                    max={100}
                    value={doc.framing.y * 100}
                    unit="%"
                    onChange={(y) => frame({ y: y / 100 }, "position")}
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full"
                    onClick={() => frame({ x: 0.5, y: 0.5, zoom: 1 })}
                  >
                    <AlignCenter />
                    Center
                  </Button>
                </Section>
              </>
            )}
          </TabsContent>
          <TabsContent value="audio" className="space-y-6 p-4">
            <Section
              title="Audio"
              description="Audio changes are included in your export."
            >
              {!asset.hasAudio && (
                <Alert>
                  <Info />
                  <AlertDescription>
                    This clip has no audio track.
                  </AlertDescription>
                </Alert>
              )}
              <Range
                label="Volume"
                value={doc.volume * 100}
                min={0}
                max={200}
                unit="%"
                onChange={(volume) =>
                  update((d) => ({ ...d, volume: volume / 100 }), "volume")
                }
              />
              <SwitchRow
                id="mute-export"
                label="Mute export audio"
                checked={doc.muted}
                onChange={(muted) => update((d) => ({ ...d, muted }))}
              />
              <Range
                label="Game and music"
                value={doc.gameVolume * 100}
                min={0}
                max={200}
                unit="%"
                onChange={(volume) =>
                  update((d) => ({ ...d, gameVolume: volume / 100 }), "gameVolume")
                }
              />
              {doc.gameVolume !== 1 && (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Your voice is split from the game and its music, so you can
                  turn them down or off (0% leaves only the voice). You hear it
                  in the exported video, not in the preview.
                </p>
              )}
              <SwitchRow
                id="clean-voice"
                label="Clean up mic noise"
                checked={doc.cleanVoice}
                onChange={(cleanVoice) => update((d) => ({ ...d, cleanVoice }))}
              />
              {doc.cleanVoice && (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Takes out rumble, fan noise and hiss. You hear it in the
                  exported video, not in the preview.
                </p>
              )}
              {doc.volume > 1 && (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Boosting quiet audio can clip loud peaks. Listen through
                  before exporting.
                </p>
              )}
            </Section>
            <Section
              title="Bleep swear words"
              description="Beeps over the word and stars it out in the caption. Click a word in the transcript to bleep just that one."
            >
              <SwitchRow
                id="bleep-swears"
                label={
                  swearCount
                    ? `Bleep ${swearCount} swear word${swearCount === 1 ? "" : "s"}`
                    : "No swear words found"
                }
                checked={allBleeped}
                onChange={(on) =>
                  update((d) => ({
                    ...d,
                    words: d.words.map((w) =>
                      isSwear(w.text) ? { ...w, bleep: on } : w,
                    ),
                  }))
                }
              />
            </Section>
          </TabsContent>
          <TabsContent value="effects" className="space-y-6 p-4">
            <Section
              title="Punch-in zoom"
              description="A quick zoom on the face for the big moment. Slow motion and instant replay are on the timeline toolbar."
            >
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" onClick={() => punch(time)}>
                  <ZoomIn />
                  Punch in here
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!asset.waveform.length}
                  onClick={() => {
                    const at = loudestMoment(doc, asset.waveform, asset.duration);
                    if (at === null) toast.info("Every loud moment already has a punch-in");
                    else {
                      punch(Math.max(0, at - 0.3));
                      seek(at);
                    }
                  }}
                >
                  <Volume2 />
                  Loudest moment
                </Button>
              </div>
              {[...doc.punches]
                .sort((a, b) => a.start - b.start)
                .map((p) => (
                  <div key={p.id} className="flex items-center gap-2 text-xs">
                    <button
                      type="button"
                      className="tabular-nums underline-offset-2 hover:underline"
                      onClick={() => seek(p.start)}
                    >
                      {timecode(p.start)}
                    </button>
                    <div className="min-w-0 flex-1">
                    <Range
                      label="Lasts"
                      value={p.end - p.start}
                      min={0.3}
                      max={5}
                      step={0.1}
                      unit="s"
                      onChange={(length) =>
                        update(
                          (d) => ({
                            ...d,
                            punches: d.punches.map((x) =>
                              x.id === p.id ? { ...x, end: x.start + length } : x,
                            ),
                          }),
                          `punch-${p.id}`,
                        )
                      }
                    />
                    </div>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label="Remove punch-in"
                      className="hover:text-destructive"
                      onClick={() =>
                        update((d) => ({
                          ...d,
                          punches: d.punches.filter((x) => x.id !== p.id),
                        }))
                      }
                    >
                      <Trash2 />
                    </Button>
                  </div>
                ))}
            </Section>
            <Section
              title="Effects"
              description="Effects apply to the video. Captions stay crisp."
              action={
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-xs"
                  onClick={() =>
                    update((d) => ({ ...d, effects: { ...DEFAULT_EFFECTS } }))
                  }
                >
                  <RotateCcw />
                  Reset
                </Button>
              }
            >
              {(
                [
                  ["Brightness", "brightness", 40, 180, 1],
                  ["Contrast", "contrast", 40, 180, 1],
                  ["Saturation", "saturation", 0, 220, 1],
                  ["Blur", "blur", 0, 8, 0.1],
                  ["Hue", "hue", -180, 180, 1],
                ] as const
              ).map(([label, key, min, max, step]) => (
                <Range
                  key={key}
                  label={label}
                  value={doc.effects[key]}
                  min={min}
                  max={max}
                  step={step}
                  onChange={(value) =>
                    update(
                      (d) => ({
                        ...d,
                        effects: { ...d.effects, [key]: value },
                      }),
                      key,
                    )
                  }
                />
              ))}
            </Section>
          </TabsContent>
        </div>
      </Tabs>
    </aside>
  );
}

"use client";
import { Diamond, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { PRESETS } from "@/components/editor/inspector";
import { Field, Range, Section } from "@/components/editor/studio-ui";
import { CAPTION_FONTS, type CaptionStyle } from "@/lib/editor/document";
import {
  clipValues,
  coverScale,
  detachAudio,
  patchClips,
  setKeyframe,
  setLook,
  setSpeed,
  timecode,
  trackOf,
  type Clip,
  type ProjectDocument,
} from "@/lib/project/document";
import type { Engine } from "./engine";
import type { Project } from "./use-project";

const FRAMES: [string, number, number][] = [
  ["1080p", 1920, 1080],
  ["1440p", 2560, 1440],
  ["4K", 3840, 2160],
  ["Vertical", 1080, 1920],
  ["Square", 1080, 1080],
];
const CORNERS: [string, number, number][] = [
  ["Top left", 0.17, 0.2],
  ["Top right", 0.83, 0.2],
  ["Bottom left", 0.17, 0.8],
  ["Bottom right", 0.83, 0.8],
];
const select = "h-8 w-full rounded-md border bg-background px-2 text-sm";

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 text-sm">
      {label}
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  );
}
function Color({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <Field label={label}>
      <input
        type="color"
        aria-label={label}
        className="h-8 w-full cursor-pointer rounded-md border bg-background"
        value={value}
        onChange={(event) => onChange(event.target.value.toUpperCase())}
      />
    </Field>
  );
}

/** What the selected clip looks and sounds like; with nothing selected, the project's frame. */
export function Properties({ project, engine, selected }: { project: Project; engine: Engine | null; selected: ReadonlySet<string> }) {
  const doc = project.doc!,
    { update, assets } = project;
  const clips = doc.clips.filter((c) => selected.has(c.id));
  if (!clips.length) return <ProjectSettings project={project} />;
  const clip = clips[0],
    ids = new Set(clips.map((c) => c.id)),
    asset = clip.asset ? assets[clip.asset] : undefined,
    track = trackOf(doc, clip),
    visual = track.kind !== "audio",
    audible = !!asset && asset.kind !== "image" && asset.hasAudio;
  const time = engine?.time ?? clip.start,
    local = Math.min(Math.max(0, time - clip.start), clip.duration),
    look = clipValues(clip, local);
  const patch = (values: Partial<Clip>, group: string) => update((d) => patchClips(d, ids, values), group);
  const setLookAt = (values: Parameters<typeof setLook>[3], group: string) =>
    update((d) => [...ids].reduce((next, id) => setLook(next, id, time, values), d), group);
  return (
    <div className="space-y-6 p-4">
      <p className="truncate text-xs text-muted-foreground">
        {clips.length > 1 ? `${clips.length} clips selected` : clip.text ? "Text" : (asset?.name ?? "Missing file")} ·{" "}
        {timecode(clip.duration, 30)} long
      </p>
      {clip.text && (
        <Section title="Text">
          <Textarea
            aria-label="Text"
            rows={3}
            value={clip.text.content}
            onChange={(event) => patch({ text: { ...clip.text!, content: event.target.value } }, "text")}
          />
          <Field label="Font">
            <select className={select} value={clip.text.font} onChange={(event) => patch({ text: { ...clip.text!, font: event.target.value } }, "")}>
              {Object.entries(CAPTION_FONTS).map(([value, name]) => (
                <option key={value} value={value}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
          <Range label="Size" value={clip.text.size} min={20} max={300} onChange={(size) => patch({ text: { ...clip.text!, size } }, "size")} />
          <div className="grid grid-cols-2 gap-3">
            <Color label="Colour" value={clip.text.color} onChange={(color) => patch({ text: { ...clip.text!, color } }, "color")} />
            <Field label="Outline">
              <Input
                type="number"
                min={0}
                max={12}
                className="h-8"
                value={clip.text.outline}
                onChange={(event) => patch({ text: { ...clip.text!, outline: Math.min(12, Math.max(0, Number(event.target.value) || 0)) } }, "outline")}
              />
            </Field>
          </div>
          <Toggle label="Box behind the text" checked={clip.text.background} onChange={(background) => patch({ text: { ...clip.text!, background } }, "")} />
          <Toggle label="ALL CAPS" checked={clip.text.uppercase} onChange={(uppercase) => patch({ text: { ...clip.text!, uppercase } }, "")} />
        </Section>
      )}
      {visual && (
        <Section
          title="Picture"
          description={clip.keys.length ? "This clip is animated: changes are recorded at the playhead." : undefined}
        >
          {asset && asset.kind !== "audio" && (
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" variant="outline" onClick={() => patch({ x: 0.5, y: 0.5, scale: 1, opacity: 1, keys: [] }, "")}>
                Fit
              </Button>
              <Button size="sm" variant="outline" onClick={() => patch({ x: 0.5, y: 0.5, scale: coverScale(doc, asset), keys: [] }, "")}>
                Fill
              </Button>
              {CORNERS.map(([name, x, y]) => (
                <Button key={name} size="sm" variant="outline" onClick={() => patch({ x, y, scale: 0.3, keys: [] }, "")}>
                  {name}
                </Button>
              ))}
            </div>
          )}
          <Range label="Size" value={Math.round(look.scale * 100)} min={5} max={400} unit="%" onChange={(v) => setLookAt({ scale: v / 100 }, "scale")} />
          <Range label="Left to right" value={Math.round(look.x * 100)} min={-50} max={150} unit="%" onChange={(v) => setLookAt({ x: v / 100 }, "x")} />
          <Range label="Top to bottom" value={Math.round(look.y * 100)} min={-50} max={150} unit="%" onChange={(v) => setLookAt({ y: v / 100 }, "y")} />
          <Range label="Opacity" value={Math.round(look.opacity * 100)} min={0} max={100} unit="%" onChange={(v) => setLookAt({ opacity: v / 100 }, "opacity")} />
        </Section>
      )}
      {visual && !clip.text && (
        <Section title="Animation" description="Set the picture at two moments and it moves between them. Use it for zoom punch-ins.">
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="outline" onClick={() => update((d) => setKeyframe(d, clip.id, local))}>
              <Diamond /> Keyframe at playhead
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                update((d) => {
                  // Push in by 25% over the first half second, hold, and ease back out at the end.
                  const base = clipValues(clip, 0),
                    zoomed = { scale: base.scale * 1.25 },
                    end = clip.duration;
                  return [
                    [0, {}],
                    [Math.min(0.5, end / 3), zoomed],
                    [Math.max(end - 0.5, (end * 2) / 3), zoomed],
                    [end, {}],
                  ].reduce((next, [t, values]) => setKeyframe(next, clip.id, t as number, { ...base, ...(values as object) }), patchClips(d, ids, { keys: [] }));
                })
              }
            >
              Zoom punch-in
            </Button>
            {clip.keys.length > 0 && (
              <Button size="sm" variant="ghost" onClick={() => patch({ keys: [] }, "")}>
                <Trash2 /> Clear
              </Button>
            )}
          </div>
          {clip.keys.length > 0 && (
            <ul className="space-y-1 text-xs text-muted-foreground">
              {clip.keys.map((key) => (
                <li key={key.t} className="flex items-center gap-2">
                  <button type="button" className="tabular-nums hover:text-foreground" onClick={() => engine?.seek(clip.start + key.t)}>
                    {timecode(key.t, 30)}
                  </button>
                  <span className="flex-1">
                    {Math.round(key.scale * 100)}% · {Math.round(key.opacity * 100)}% opacity
                  </span>
                  <button
                    type="button"
                    aria-label="Remove keyframe"
                    className="hover:text-destructive"
                    onClick={() => patch({ keys: clip.keys.filter((k) => k !== key) }, "")}
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
      {audible && (
        <Section title="Sound">
          <Range label="Volume" value={Math.round(clip.volume * 100)} min={0} max={300} unit="%" onChange={(v) => patch({ volume: v / 100 }, "volume")} />
          <Toggle label="Mute this clip" checked={clip.muted} onChange={(muted) => patch({ muted }, "")} />
          {track.kind === "video" && !clip.muted && (
            <Button size="sm" variant="outline" onClick={() => update((d) => detachAudio(d, clip.id))}>
              Move sound to its own track
            </Button>
          )}
        </Section>
      )}
      <Section title="Fades">
        <Range label="Fade in" value={clip.fadeIn} min={0} max={Math.min(5, clip.duration / 2)} step={0.1} unit=" s" onChange={(fadeIn) => patch({ fadeIn }, "fadeIn")} />
        <Range label="Fade out" value={clip.fadeOut} min={0} max={Math.min(5, clip.duration / 2)} step={0.1} unit=" s" onChange={(fadeOut) => patch({ fadeOut }, "fadeOut")} />
      </Section>
      {asset && asset.kind !== "image" && (
        <Section title="Speed">
          <div className="flex flex-wrap gap-1.5">
            {[0.5, 0.75, 1, 1.25, 1.5, 2, 4].map((speed) => (
              <Button
                key={speed}
                size="sm"
                variant={clip.speed === speed ? "default" : "outline"}
                onClick={() => update((d) => [...ids].reduce((next, id) => setSpeed(next, id, speed), d))}
              >
                {speed}×
              </Button>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function ProjectSettings({ project }: { project: Project }) {
  const doc = project.doc!;
  const set = (values: Partial<ProjectDocument>) => project.update((d) => ({ ...d, ...values }));
  return (
    <div className="space-y-6 p-4">
      <p className="text-xs leading-relaxed text-muted-foreground">Select a clip on the timeline to change it. These settings are for the whole video.</p>
      <Section title="Frame" description={`${doc.width}×${doc.height} at ${Number(doc.fps.toFixed(2))} frames a second. Set from your first video.`}>
        <div className="flex flex-wrap gap-1.5">
          {FRAMES.map(([name, width, height]) => (
            <Button key={name} size="sm" variant={doc.width === width && doc.height === height ? "default" : "outline"} onClick={() => set({ width, height })}>
              {name}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {[24, 30, 60].map((fps) => (
            <Button key={fps} size="sm" variant={Math.round(doc.fps) === fps ? "default" : "outline"} onClick={() => set({ fps })}>
              {fps} fps
            </Button>
          ))}
        </div>
      </Section>
      <Section title="Sound" description="Takes out rumble and hiss and evens out loud and quiet speech. Music on the audio tracks is left alone. You hear it in the exported video, not in the preview.">
        <Toggle label="Clean up voice" checked={!!doc.cleanVoice} onChange={(cleanVoice) => set({ cleanVoice })} />
      </Section>
    </div>
  );
}

/** Caption look for the whole video. */
export function CaptionSettings({ project }: { project: Project }) {
  const style = project.doc!.captions;
  const set = (values: Partial<CaptionStyle>, group = "") => project.update((d) => ({ ...d, captions: { ...d.captions, ...values } }), group);
  return (
    <div className="space-y-6 p-4">
      <Toggle label="Show captions on the video" checked={style.enabled} onChange={(enabled) => set({ enabled })} />
      <Section title="Look">
        <div className="grid grid-cols-3 gap-1.5">
          {PRESETS.map(([name, preset]) => (
            <Button key={name} size="sm" variant={style.font === preset.font && style.background === preset.background ? "default" : "outline"} onClick={() => set(preset)}>
              {name}
            </Button>
          ))}
        </div>
      </Section>
      <Section title="Customise">
        <Field label="Font">
          <select className={select} value={style.font} onChange={(event) => set({ font: event.target.value as CaptionStyle["font"] })}>
            {Object.entries(CAPTION_FONTS).map(([value, name]) => (
              <option key={value} value={value}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        <Range label="Size" value={style.size} min={20} max={100} onChange={(size) => set({ size }, "size")} />
        <Range label="Height on screen" value={Math.round(style.y * 100)} min={10} max={90} unit="%" onChange={(y) => set({ y: y / 100 }, "y")} />
        <Range label="Words per line" value={style.wordsPerLine} min={1} max={8} onChange={(wordsPerLine) => set({ wordsPerLine }, "wpl")} />
        <div className="grid grid-cols-2 gap-3">
          <Color label="Text" value={style.color} onChange={(color) => set({ color }, "color")} />
          <Color label="Highlight" value={style.accent} onChange={(accent) => set({ accent }, "accent")} />
        </div>
        <Range label="Outline" value={style.outline} min={0} max={12} onChange={(outline) => set({ outline }, "outline")} />
        <Toggle label="Box behind the words" checked={style.background} onChange={(background) => set({ background })} />
        <Toggle label="ALL CAPS" checked={style.uppercase} onChange={(uppercase) => set({ uppercase })} />
        <Toggle label="Light up the word being spoken" checked={style.active} onChange={(active) => set({ active })} />
      </Section>
    </div>
  );
}

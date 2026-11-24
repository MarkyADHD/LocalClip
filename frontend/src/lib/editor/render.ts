import {
  captionGroups,
  frameRect,
  censor,
  mapped,
  mappedWords,
  PUNCH_Y,
  PUNCH_ZOOM,
  regionCrop,
  wordColor,
  type CaptionStyle,
  type CaptionWord,
  type EditDocument,
} from "./document";

const groupCache = new WeakMap<EditDocument, CaptionWord[][]>();
const loaded = new Map<string, Promise<void>>();
export function loadEditorFont(name: string) {
  if (!loaded.has(name))
    loaded.set(
      name,
      (async () => {
        const font = new FontFace(
          `Editor-${name}`,
          `url(/api/fonts/${encodeURIComponent(name)})`,
        );
        await font.load();
        document.fonts.add(font);
      })().catch((error) => {
        loaded.delete(name);
        throw error;
      }),
    );
  return loaded.get(name)!;
}
type Rect = ReturnType<typeof frameRect>;
/** Facecam band height in the stacked layouts (same as the stream templates). */
const CAM_SHARE = 0.4;
const even = (value: number) => Math.round(value / 2) * 2;

/** Lays the source frame out on the canvas. `draw` paints the whole frame into a rect. */
function drawLayout(
  ctx: CanvasRenderingContext2D,
  doc: EditDocument,
  sw: number,
  sh: number,
  draw: (rect: Rect) => void,
) {
  const { width, height } = ctx.canvas,
    f = doc.framing,
    fx = doc.effects,
    layout = f.aspect === "original" ? "crop" : f.layout;
  const filter = `brightness(${fx.brightness}%) contrast(${fx.contrast}%) saturate(${fx.saturation}%) blur(${(fx.blur * width) / 1080}px) hue-rotate(${fx.hue}deg)`;
  ctx.filter = filter;
  const pane = (x: number, y: number, w: number, h: number, rect: Rect) => {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    draw({ ...rect, x: x + rect.x, y: y + rect.y });
    ctx.restore();
  };
  const background = () => {
    ctx.filter = `${filter} blur(${width * 0.03}px)`;
    draw(
      frameRect({ ...f, fit: "cover", zoom: 1, x: 0.5, y: 0.5 }, sw, sh, width, height),
    );
    ctx.filter = filter;
  };
  const cam = (x: number, y: number, w: number, h: number) => {
    const crop = regionCrop(f.cam, w / h, sw, sh),
      scale = w / crop.width;
    pane(x, y, w, h, {
      x: -crop.x * scale,
      y: -crop.y * scale,
      width: sw * scale,
      height: sh * scale,
    });
  };
  if (layout === "crop") {
    const rect = frameRect(f, sw, sh, width, height);
    if (rect.width < width || rect.height < height) background();
    draw(rect);
  } else if (layout === "floating") {
    background();
    const band = Math.min(height, even((width * sh) / sw)),
      top = (height - band) / 2,
      cw = even(width * 0.6),
      ch = even((cw * 460) / 648);
    draw({ x: 0, y: top, width, height: band });
    cam((width - cw) / 2, Math.max(0, top - ch - height / 80), cw, ch);
  } else {
    const camHeight = even(height * CAM_SHARE),
      gameHeight = height - camHeight,
      camTop = layout === "cam_top";
    pane(
      0,
      camTop ? camHeight : 0,
      width,
      gameHeight,
      frameRect({ ...f, fit: "cover" }, sw, sh, width, gameHeight),
    );
    cam(0, camTop ? 0 : gameHeight, width, camHeight);
  }
}

/** Centred, wrapped lines of words around `centre` (0..1 of the height). */
export function drawWords(
  ctx: CanvasRenderingContext2D,
  style: Pick<
    CaptionStyle,
    | "size"
    | "font"
    | "uppercase"
    | "background"
    | "outline"
    | "accent"
    | "color"
    | "speakerColors"
  >,
  words: Pick<CaptionWord, "text" | "speaker">[],
  centre: number,
  accent: (index: number) => boolean,
  centreX = 0.5,
) {
  const { width, height } = ctx.canvas,
    size = (style.size * width) / 1080;
  ctx.font = `${size}px "Editor-${style.font}", sans-serif`;
  ctx.textBaseline = "middle";
  const texts = words.map((w) =>
    style.uppercase ? w.text.toUpperCase() : w.text,
  );
  // Fit each phrase in the safe width, using the same font for preview and browser export.
  const space = ctx.measureText(" ").width;
  const lines: number[][] = [];
  let line: number[] = [],
    lineWidth = 0;
  texts.forEach((text, index) => {
    const wordWidth = ctx.measureText(text).width;
    if (line.length && lineWidth + space + wordWidth > width * 0.84) {
      lines.push(line);
      line = [];
      lineWidth = 0;
    }
    line.push(index);
    lineWidth += wordWidth + (line.length > 1 ? space : 0);
  });
  if (line.length) lines.push(line);
  lines.forEach((indexes, row) => {
    const total =
      indexes.reduce((sum, i) => sum + ctx.measureText(texts[i]).width, 0) +
      space * (indexes.length - 1);
    let x = width * centreX - total / 2;
    const y = height * centre + (row - (lines.length - 1) / 2) * size * 1.2;
    if (style.background) {
      ctx.fillStyle = "#101010";
      ctx.fillRect(
        x - size * 0.1,
        y - size * 0.6,
        total + size * 0.2,
        size * 1.2,
      );
    }
    for (const i of indexes) {
      ctx.lineWidth = (size * style.outline) / 50;
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#101010";
      if (!style.background && style.outline) ctx.strokeText(texts[i], x, y);
      ctx.fillStyle = accent(i) ? style.accent : wordColor(style, words[i]);
      ctx.fillText(texts[i], x, y);
      x += ctx.measureText(texts[i]).width + space;
    }
  });
}

export function drawEditorFrame(
  ctx: CanvasRenderingContext2D,
  doc: EditDocument,
  sourceWidth: number,
  sourceHeight: number,
  time: number,
  draw: (rect: Rect) => void,
) {
  const { width, height } = ctx.canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "black";
  ctx.fillRect(0, 0, width, height);
  ctx.save();
  if (doc.punches.length && mapped(doc, doc.punches).some((p) => time >= p.start && time < p.end)) {
    // Snap zoom around the face (same crop as punch_filter in editor_document.py).
    const layout = doc.framing.aspect === "original" ? "crop" : doc.framing.layout,
      x = width / 2,
      y = height * PUNCH_Y[layout];
    ctx.translate(x, y);
    ctx.scale(PUNCH_ZOOM, PUNCH_ZOOM);
    ctx.translate(-x, -y);
  }
  drawLayout(ctx, doc, sourceWidth, sourceHeight, draw);
  ctx.restore();
  if (doc.title.trim() && (!doc.titleSeconds || time < doc.titleSeconds))
    drawWords(
      ctx,
      doc.captions,
      doc.title
        .trim()
        .split(/\s+/)
        .map((text) => ({ text })),
      TITLE_Y,
      () => false,
    );
  if (!doc.captions.enabled) return;
  let groups = groupCache.get(doc);
  if (!groups) {
    groups = captionGroups(
      mappedWords(doc).map((w) =>
        w.bleep ? { ...w, text: censor(w.text) } : w,
      ),
      doc.captions.wordsPerLine,
    );
    groupCache.set(doc, groups);
  }
  const group = groups.find(
    (group) =>
      time >= group[0].start && time < Math.max(...group.map((w) => w.end)),
  );
  if (!group) return;
  // The spoken word stays lit until the next one starts.
  const spoken = doc.captions.active
    ? group.findLastIndex((w) => w.start <= time)
    : -1;
  ctx.save();
  captionEntrance(ctx, doc.captions.animation, (time - group[0].start) / ENTER_SECONDS, doc.captions.y);
  drawWords(
    ctx,
    doc.captions,
    group,
    doc.captions.y,
    (i) => group[i].highlight || i === spoken,
  );
  ctx.restore();
}

/** Length of a caption entrance; ENTER_MS in editor_document.py. */
export const ENTER_SECONDS = 0.15;
/** A sliding caption starts this far below its place (share of the height); SLIDE in editor_document.py. */
const SLIDE = 0.03;

/** Pop size at `progress` 0..1: 60% up to 112%, then back to 100% (the two steps in enter_tags). */
export const popScale = (progress: number) =>
  progress < 0.6 ? 0.6 + (0.52 * progress) / 0.6 : 1.12 - (0.12 * (progress - 0.6)) / 0.4;

/** Transforms the canvas so a caption centred on `y` is drawn part-way through its entrance. */
function captionEntrance(
  ctx: CanvasRenderingContext2D,
  animation: CaptionStyle["animation"],
  progress: number,
  y: number,
) {
  if (!animation || animation === "none" || progress >= 1) return;
  const { width, height } = ctx.canvas,
    p = Math.max(0, progress);
  if (animation === "pop") {
    ctx.translate(width / 2, height * y);
    ctx.scale(popScale(p), popScale(p));
    ctx.translate(-width / 2, -height * y);
    return;
  }
  ctx.globalAlpha = p;
  if (animation === "slide") ctx.translate(0, height * SLIDE * (1 - p));
}
/** Where the hook title sits (0..1 of the height); same in editor_document.py. */
export const TITLE_Y = 0.14;

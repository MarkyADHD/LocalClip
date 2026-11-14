"use client";
import { useEffect, useRef, useState } from "react";
import { Check, Copy, Loader2, SendHorizontal, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { editorRequest } from "@/components/editor/use-editor";
import { applyEdits, timecode, type ProposedEdit } from "@/lib/project/document";
import type { Engine } from "./engine";
import type { Project } from "./use-project";

interface Message {
  role: "user" | "assistant";
  text: string;
  edits?: ProposedEdit[];
  /** Set once the edits were applied or dismissed. */
  done?: string;
}
const IDEAS = [
  "Tighten this up: cut rambling, repeats and dead air",
  "Make chapters",
  "Write a title and description",
  "Find the best moments and tell me where they are",
];
const MCP_COMMAND = "claude mcp add --transport http localclip http://localhost:8000/mcp/";

const label = (edit: ProposedEdit) =>
  edit.kind === "cut"
    ? `Cut ${edit.seconds.toFixed(1)} s`
    : edit.kind === "chapter"
      ? "Chapter"
      : edit.kind === "text"
        ? "On-screen text"
        : edit.kind === "title"
          ? "Title"
          : "Description";

/** A set of proposed edits: tick the ones to keep, then apply them as one undoable change. */
function Edits({
  edits,
  engine,
  onApply,
  onDismiss,
}: {
  edits: ProposedEdit[];
  engine: Engine | null;
  onApply: (edits: ProposedEdit[]) => void;
  onDismiss: () => void;
}) {
  const [off, setOff] = useState<ReadonlySet<number>>(new Set());
  const picked = edits.filter((_, index) => !off.has(index));
  const saved = picked.reduce((sum, e) => sum + (e.kind === "cut" ? e.seconds : 0), 0);
  return (
    <div className="mt-2 rounded-md border bg-background">
      <ul className="max-h-72 divide-y overflow-y-auto">
        {edits.map((edit, index) => (
          <li key={index} className="flex items-start gap-2 p-2 text-xs">
            <Checkbox
              className="mt-0.5"
              aria-label={`Keep: ${label(edit)}`}
              checked={!off.has(index)}
              onCheckedChange={(on) =>
                setOff((old) => {
                  const next = new Set(old);
                  if (on) next.delete(index);
                  else next.add(index);
                  return next;
                })
              }
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className="font-medium text-foreground">{label(edit)}</span>
                {"time" in edit && (
                  <button type="button" className="tabular-nums text-brand hover:underline" onClick={() => engine?.seek(edit.time)}>
                    {timecode(edit.time)}
                  </button>
                )}
                {edit.kind === "cut" && edit.note && <span className="truncate text-muted-foreground">{edit.note}</span>}
              </div>
              {edit.text && (
                <p className={edit.kind === "cut" ? "line-clamp-2 text-muted-foreground line-through decoration-muted-foreground/50" : "line-clamp-4 whitespace-pre-wrap text-muted-foreground"}>
                  {edit.text}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-2 border-t p-2">
        <Button size="sm" className="h-7" disabled={!picked.length} onClick={() => onApply(picked)}>
          <Check /> Apply {picked.length} {picked.length === 1 ? "edit" : "edits"}
        </Button>
        <Button size="sm" variant="ghost" className="h-7" onClick={onDismiss}>
          Dismiss
        </Button>
        {saved > 0 && <span className="ml-auto text-xs text-muted-foreground">Saves {timecode(saved)}</span>}
      </div>
    </div>
  );
}

/** Ask for edits in plain words. Nothing changes until the proposed edits are applied, and Ctrl+Z takes them back. */
export function Assistant({ project, engine }: { project: Project; engine: Engine | null }) {
  const { endpoint, proposals, refresh, update } = project;
  // ponytail: the conversation lives in this tab only and is gone on reload; store it with the project if people miss it.
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages, busy, proposals]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy || !project.doc) return;
    const history = messages.map(({ role, text }) => ({ role, text }));
    setMessages((all) => [...all, { role: "user", text: message }]);
    setInput("");
    setBusy(true);
    try {
      const answer = await editorRequest<{ reply: string; edits: ProposedEdit[] }>(`${endpoint}/assistant`, "POST", {
        message,
        history,
        document: project.doc,
      });
      setMessages((all) => [...all, { role: "assistant", text: answer.reply, edits: answer.edits.length ? answer.edits : undefined }]);
    } catch (error) {
      setMessages((all) => [...all, { role: "assistant", text: error instanceof Error ? error.message : "The AI model could not answer." }]);
    } finally {
      setBusy(false);
    }
  };
  const apply = (edits: ProposedEdit[]) => {
    update((doc) => applyEdits(doc, edits));
    toast.success(`Applied ${edits.length} ${edits.length === 1 ? "edit" : "edits"}. Ctrl+Z undoes them.`);
  };
  const settle = (index: number, done: string) => setMessages((all) => all.map((m, i) => (i === index ? { ...m, done } : m)));
  const clear = (id: string) => editorRequest(`${endpoint}/proposals/${id}`, "DELETE").then(refresh).catch(() => {});

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-sm">
        {!messages.length && !proposals.length && (
          <div className="space-y-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              Say what you want changed. The assistant reads the transcript and proposes edits; you choose which to
              apply. It uses the AI model picked in Settings.
            </p>
            <div className="flex flex-col gap-1.5">
              {IDEAS.map((idea) => (
                <Button key={idea} size="sm" variant="outline" className="h-auto justify-start whitespace-normal py-1.5 text-left text-xs" onClick={() => send(idea)}>
                  <Sparkles /> {idea}
                </Button>
              ))}
            </div>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer hover:text-foreground">Edit from Claude Code or another MCP app</summary>
              <p className="mt-2 leading-relaxed">
                LocalClip is also an MCP server. Add it once, then ask Claude to edit this video; its edits show up
                here for you to accept.
              </p>
              <div className="mt-2 flex items-center gap-1 rounded-md border bg-background p-1.5">
                <code className="min-w-0 flex-1 truncate text-[11px]">{MCP_COMMAND}</code>
                <Button size="icon-sm" variant="ghost" aria-label="Copy command" onClick={() => navigator.clipboard.writeText(MCP_COMMAND).then(() => toast.success("Copied"))}>
                  <Copy />
                </Button>
              </div>
            </details>
          </div>
        )}
        {messages.map((message, index) =>
          message.role === "user" ? (
            <p key={index} className="ml-8 rounded-lg bg-accent px-3 py-2 whitespace-pre-wrap">
              {message.text}
            </p>
          ) : (
            <div key={index}>
              <p className="whitespace-pre-wrap leading-relaxed">{message.text}</p>
              {message.edits &&
                (message.done ? (
                  <p className="mt-1 text-xs text-muted-foreground">{message.done}</p>
                ) : (
                  <Edits
                    edits={message.edits}
                    engine={engine}
                    onApply={(edits) => {
                      apply(edits);
                      settle(index, `Applied ${edits.length} of ${message.edits!.length}.`);
                    }}
                    onDismiss={() => settle(index, "Dismissed.")}
                  />
                ))}
            </div>
          ),
        )}
        {proposals.map((proposal) => (
          <div key={proposal.id}>
            <p className="text-xs text-muted-foreground">Proposed from outside the editor (MCP)</p>
            <p className="whitespace-pre-wrap leading-relaxed">{proposal.reply}</p>
            <Edits
              edits={proposal.edits}
              engine={engine}
              onApply={(edits) => {
                apply(edits);
                void clear(proposal.id);
              }}
              onDismiss={() => void clear(proposal.id)}
            />
          </div>
        ))}
        {busy && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> Reading the transcript…
          </p>
        )}
        <div ref={bottom} />
      </div>
      <form
        className="flex items-end gap-1.5 border-t p-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send(input);
        }}
      >
        <Textarea
          aria-label="Ask the assistant"
          placeholder="Cut the part where I talk about…"
          rows={2}
          className="min-h-0 resize-none text-sm"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send(input);
            }
          }}
        />
        <Button size="icon-sm" type="submit" aria-label="Send" disabled={busy || !input.trim()}>
          <SendHorizontal />
        </Button>
      </form>
    </div>
  );
}

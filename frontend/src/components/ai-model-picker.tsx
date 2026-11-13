"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface LocalModel {
  llm: string;
  label: string;
  source: string;
  base_url: string | null;
  running: boolean;
}

interface LlmChoices {
  current: string;
  models: LocalModel[];
}

/** Picks the LLM that chooses clips from every model the backend found on this PC. */
export function AiModelPicker() {
  const [choices, setChoices] = useState<LlmChoices | null>(null);
  const [scanning, setScanning] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const scan = useCallback(async () => {
    setScanning(true);
    setMessage(null);
    try {
      const response = await fetch("/api/ai-model", { cache: "no-store" });
      if (!response.ok) throw new Error((await response.json()).detail || "Scan failed");
      setChoices(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    void scan();
  }, [scan]);

  const pick = async (llm: string) => {
    const model = choices?.models.find((m) => m.llm === llm);
    setSaving(true);
    setMessage(model && !model.running ? `Starting ${model.source}...` : null);
    try {
      const response = await fetch("/api/ai-model", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ llm, base_url: model?.base_url ?? undefined }),
      });
      if (!response.ok) throw new Error((await response.json()).detail || "Could not save");
      const saved = await response.json();
      setChoices((prev) => (prev ? { ...prev, current: saved.current } : prev));
      setMessage("Saved. New generations use this model.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  const models = choices?.models ?? [];
  const sources = [...new Set(models.map((m) => m.source))];
  const current = choices?.current ?? "";
  const currentKnown = models.some((m) => m.llm === current);

  return (
    <div className="space-y-3">
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1 space-y-2">
          <Label className="text-sm">Model</Label>
          <Select value={current} onValueChange={pick} disabled={scanning || saving || !choices}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder={scanning ? "Scanning this PC..." : "Select a model"} />
            </SelectTrigger>
            <SelectContent>
              {!currentKnown && current && <SelectItem value={current}>{current}</SelectItem>}
              {sources.map((source) => (
                <SelectGroup key={source}>
                  <SelectLabel>{source}</SelectLabel>
                  {models
                    .filter((m) => m.source === source)
                    .map((m) => (
                      <SelectItem key={m.llm} value={m.llm}>
                        {m.label}
                        {!m.running && <span className="text-muted-foreground"> (starts when used)</span>}
                      </SelectItem>
                    ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button variant="outline" onClick={scan} disabled={scanning || saving} aria-label="Rescan this PC for models">
          {scanning || saving ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
          Rescan
        </Button>
      </div>
      <p role="status" className="text-xs text-muted-foreground">
        {message ??
          (scanning
            ? "Looking for Claude Code, Ollama, LM Studio, llama.cpp, Jan, KoboldCpp and other local servers..."
            : `${models.length} models found. Claude Code is the quickest and picks the best clips; local models keep everything on this PC.`)}
      </p>
    </div>
  );
}

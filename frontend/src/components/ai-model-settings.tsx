"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Check, Loader2, RefreshCw } from "lucide-react";

interface LocalServer {
  name: string;
  base_url: string;
  models: string[];
}

const CLAUDE_CODE = "claude-code:sonnet";
const isLocal = (llm: string) => llm.startsWith("local:") || llm.startsWith("ollama:");
const optionValue = (llm: string, baseUrl: string) => JSON.stringify([llm, baseUrl]);

// Picks the model that chooses clips: Claude Code, any model a local AI app on this PC serves, or any provider:model.
export function AiModelSettings() {
  const [servers, setServers] = useState<LocalServer[]>([]);
  const [llm, setLlm] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [allowed, setAllowed] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scan = useCallback(async (resetSelection: boolean) => {
    setScanning(true);
    try {
      const response = await fetch("/api/admin/local-models", { cache: "no-store" });
      if (!response.ok) {
        setAllowed(false);
        return;
      }
      const data: { llm: string; base_url: string; servers: LocalServer[] } = await response.json();
      setServers(data.servers);
      if (resetSelection) {
        setLlm(data.llm);
        setBaseUrl(data.base_url);
        setSaved(optionValue(data.llm, data.base_url));
      }
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    void scan(true);
  }, [scan]);

  if (!allowed) return null;

  const current = optionValue(llm, isLocal(llm) ? baseUrl : "");
  const listed = new Set([
    optionValue(CLAUDE_CODE, ""),
    ...servers.flatMap((s) => s.models.map((m) => optionValue(`local:${m}`, s.base_url))),
  ]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const updates: Record<string, string> = { LLM: llm };
      if (isLocal(llm)) updates.OLLAMA_BASE_URL = baseUrl;
      const response = await fetch("/api/admin/runtime-settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          updates,
          prefer_admin_values: Object.fromEntries(Object.keys(updates).map((key) => [key, true])),
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Couldn't save the AI model");
      }
      setSaved(optionValue(llm, baseUrl));
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the AI model");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label className="text-sm">Model</Label>
        <div className="flex gap-2">
          <Select
            value={current}
            onValueChange={(value) => {
              const [nextLlm, nextBaseUrl] = JSON.parse(value) as [string, string];
              setLlm(nextLlm);
              if (nextBaseUrl) setBaseUrl(nextBaseUrl);
            }}
            disabled={saving || saved === null}
          >
            <SelectTrigger className="w-full"><SelectValue placeholder="Select a model" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={optionValue(CLAUDE_CODE, "")}>Claude Code (Sonnet)</SelectItem>
              {servers.map((server) => (
                <SelectGroup key={server.base_url}>
                  <SelectLabel>{server.name}</SelectLabel>
                  {server.models.map((model) => (
                    <SelectItem key={model} value={optionValue(`local:${model}`, server.base_url)}>{model}</SelectItem>
                  ))}
                </SelectGroup>
              ))}
              {llm && !listed.has(current) && <SelectItem value={current}>{llm}</SelectItem>}
            </SelectContent>
          </Select>
          <Button variant="outline" size="icon" onClick={() => scan(false)} disabled={scanning} aria-label="Scan for local models" title="Scan for local models">
            <RefreshCw className={scanning ? "size-4 animate-spin" : "size-4"} />
          </Button>
        </div>
        {!scanning && servers.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No local AI apps found. Start Ollama, LM Studio, Jan, llama.cpp or another local AI app, then scan again.
          </p>
        )}
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-muted-foreground">Use a model that isn&apos;t listed</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="llm-name" className="text-xs">Model (provider:model)</Label>
            <Input id="llm-name" value={llm} onChange={(e) => setLlm(e.target.value)} placeholder="local:qwen3:8b" className="font-mono text-xs" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="llm-url" className="text-xs">Local server URL (OpenAI-compatible)</Label>
            <Input id="llm-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://localhost:11434/v1" className="font-mono text-xs" />
          </div>
        </div>
      </details>

      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

      <div className="flex items-center justify-end gap-3">
        {success && <span role="status" className="flex items-center gap-1.5 text-sm text-muted-foreground"><Check className="size-4 text-emerald-600" />Saved. New clips use this model.</span>}
        <Button onClick={save} disabled={saving || !llm.trim() || saved === optionValue(llm, baseUrl)}>
          {saving ? <><Loader2 className="size-4 animate-spin" />Saving...</> : "Save model"}
        </Button>
      </div>
    </div>
  );
}

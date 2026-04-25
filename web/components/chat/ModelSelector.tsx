"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Brain, Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { apiUrl } from "@/lib/api";
import {
  activeModelId,
  getActiveProfile,
  selectCatalogModel,
  type Catalog,
  type ModelOption,
} from "@/lib/model-catalog";

type SettingsPayload = {
  catalog: Catalog;
};

type ModelListPayload = {
  models: Array<ModelOption & { premium?: boolean; owned_by?: string }>;
};

function mergeModelOptions(
  catalog: Catalog | null,
  remoteModels: ModelOption[],
): ModelOption[] {
  const byId = new Map<string, ModelOption>();
  for (const model of remoteModels) {
    if (model.id) byId.set(model.id, model);
  }

  if (catalog) {
    const profile = getActiveProfile(catalog, "llm");
    for (const model of profile?.models || []) {
      if (!model.model || byId.has(model.model)) continue;
      byId.set(model.model, {
        id: model.model,
        label: model.name || model.model,
      });
    }
  }

  return Array.from(byId.values()).sort((a, b) => a.id.localeCompare(b.id));
}

export default function ModelSelector({ disabled = false }: { disabled?: boolean }) {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [remoteModels, setRemoteModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");

  const selectedModel = catalog ? activeModelId(catalog, "llm") : "";
  const options = useMemo(
    () => mergeModelOptions(catalog, remoteModels),
    [catalog, remoteModels],
  );

  const loadModels = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const settingsResponse = await fetch(apiUrl("/api/v1/settings"));
      if (!settingsResponse.ok) throw new Error(t("Could not load settings"));
      const settingsPayload = (await settingsResponse.json()) as SettingsPayload;
      setCatalog(settingsPayload.catalog);

      const modelsResponse = await fetch(apiUrl("/api/v1/settings/models/llm"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ catalog: settingsPayload.catalog }),
      });
      if (!modelsResponse.ok) throw new Error(t("Could not load models"));
      const modelsPayload = (await modelsResponse.json()) as ModelListPayload;
      setRemoteModels(modelsPayload.models || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Could not load models"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  const applyModel = async (modelId: string) => {
    if (!catalog || !modelId || modelId === selectedModel) return;
    const option = options.find((item) => item.id === modelId) || {
      id: modelId,
      label: modelId,
    };
    const nextCatalog = selectCatalogModel(catalog, "llm", option);
    setCatalog(nextCatalog);
    setApplying(true);
    setError("");
    try {
      const response = await fetch(apiUrl("/api/v1/settings/apply"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ catalog: nextCatalog }),
      });
      if (!response.ok) throw new Error(t("Could not apply model"));
      const payload = (await response.json()) as SettingsPayload;
      setCatalog(payload.catalog);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Could not apply model"));
      void loadModels();
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="flex min-w-0 items-center gap-1">
      <Brain size={12} strokeWidth={1.7} className="text-[var(--muted-foreground)]" />
      <select
        value={selectedModel}
        onChange={(event) => void applyModel(event.target.value)}
        disabled={disabled || loading || applying || options.length === 0}
        title={error || t("Select model")}
        className="h-[28px] max-w-[220px] appearance-none rounded-full border border-[var(--border)]/40 bg-transparent py-0 pl-2.5 pr-6 text-[11px] text-[var(--muted-foreground)] outline-none transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-45"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
          backgroundRepeat: "no-repeat",
          backgroundPosition: "right 8px center",
        }}
      >
        <option value="">{loading ? t("Loading models") : t("Select model")}</option>
        {options.map((model) => (
          <option key={model.id} value={model.id}>
            {model.label || model.id}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => void loadModels()}
        disabled={loading || applying}
        title={t("Refresh models")}
        aria-label={t("Refresh models")}
        className="inline-flex h-[28px] w-[28px] shrink-0 items-center justify-center rounded-full text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
      >
        {loading || applying ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <RefreshCw size={12} />
        )}
      </button>
    </div>
  );
}

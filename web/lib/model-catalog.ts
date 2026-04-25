export type ServiceName = "llm" | "embedding" | "search";
export type ModelServiceName = Exclude<ServiceName, "search">;

export type CatalogModel = {
  id: string;
  name: string;
  model: string;
  dimension?: string;
  send_dimensions?: boolean;
  context_window?: string;
  context_window_source?: string;
  context_window_detected_at?: string;
};

export type CatalogProfile = {
  id: string;
  name: string;
  binding?: string;
  provider?: string;
  base_url: string;
  api_key: string;
  api_version: string;
  extra_headers?: Record<string, string> | string;
  proxy?: string;
  max_results?: number;
  models: CatalogModel[];
};

export type CatalogService = {
  active_profile_id: string | null;
  active_model_id?: string | null;
  profiles: CatalogProfile[];
};

export type Catalog = {
  version: number;
  services: {
    llm: CatalogService;
    embedding: CatalogService;
    search: CatalogService;
  };
};

export type ModelOption = {
  id: string;
  label?: string;
  dimension?: string;
};

export function cloneCatalog(catalog: Catalog): Catalog {
  return JSON.parse(JSON.stringify(catalog)) as Catalog;
}

export function getActiveProfile(
  catalog: Catalog,
  serviceName: ServiceName,
): CatalogProfile | null {
  const service = catalog.services[serviceName];
  return (
    service.profiles.find(
      (profile) => profile.id === service.active_profile_id,
    ) ??
    service.profiles[0] ??
    null
  );
}

export function getActiveModel(
  catalog: Catalog,
  serviceName: ServiceName,
): CatalogModel | null {
  if (serviceName === "search") return null;
  const service = catalog.services[serviceName];
  const profile = getActiveProfile(catalog, serviceName);
  if (!profile) return null;
  return (
    profile.models.find((model) => model.id === service.active_model_id) ??
    profile.models[0] ??
    null
  );
}

export function activeModelId(
  catalog: Catalog,
  serviceName: ModelServiceName,
): string {
  return getActiveModel(catalog, serviceName)?.model || "";
}

function modelEntryId(serviceName: ModelServiceName, modelId: string): string {
  const slug = modelId
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
  return `${serviceName}-model-${slug || "custom"}`;
}

function uniqueModelEntryId(profile: CatalogProfile, baseId: string): string {
  const used = new Set(profile.models.map((model) => model.id));
  if (!used.has(baseId)) return baseId;
  let index = 2;
  while (used.has(`${baseId}-${index}`)) index += 1;
  return `${baseId}-${index}`;
}

export function selectCatalogModel(
  catalog: Catalog,
  serviceName: ModelServiceName,
  option: ModelOption,
): Catalog {
  const modelId = option.id.trim();
  if (!modelId) return cloneCatalog(catalog);

  const next = cloneCatalog(catalog);
  const service = next.services[serviceName];
  const profile = getActiveProfile(next, serviceName);
  if (!profile) return next;

  const existing = profile.models.find(
    (model) => model.model === modelId || model.id === modelId,
  );
  if (existing) {
    service.active_model_id = existing.id;
    return next;
  }

  const id = uniqueModelEntryId(profile, modelEntryId(serviceName, modelId));
  const model: CatalogModel = {
    id,
    name: option.label || modelId,
    model: modelId,
  };
  if (serviceName === "embedding") {
    model.dimension = option.dimension || "3072";
  }
  profile.models.push(model);
  service.active_model_id = id;
  return next;
}

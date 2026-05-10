import test from "node:test";
import assert from "node:assert/strict";

import {
  getActiveModel,
  selectCatalogModel,
  type Catalog,
} from "../lib/model-catalog";

function baseCatalog(): Catalog {
  return {
    version: 1,
    services: {
      llm: {
        active_profile_id: "llm-profile",
        active_model_id: "gpt-old",
        profiles: [
          {
            id: "llm-profile",
            name: "Navy",
            binding: "navy",
            base_url: "https://api.navy/v1",
            api_key: "",
            api_version: "",
            extra_headers: {},
            models: [
              { id: "gpt-old", name: "gpt-old", model: "gpt-old" },
              { id: "gpt-5.4-mini", name: "gpt-5.4-mini", model: "gpt-5.4-mini" },
            ],
          },
        ],
      },
      embedding: {
        active_profile_id: "embedding-profile",
        active_model_id: "embedding-model",
        profiles: [
          {
            id: "embedding-profile",
            name: "Navy Embeddings",
            binding: "navy",
            base_url: "https://api.navy/v1",
            api_key: "",
            api_version: "",
            extra_headers: {},
            models: [
              {
                id: "embedding-model",
                name: "gemini-embedding-2-preview",
                model: "gemini-embedding-2-preview",
                dimension: "3072",
              },
            ],
          },
        ],
      },
      search: {
        active_profile_id: null,
        profiles: [],
      },
    },
  };
}

test("selectCatalogModel activates an existing model without mutating the input", () => {
  const catalog = baseCatalog();
  const next = selectCatalogModel(catalog, "llm", {
    id: "gpt-5.4-mini",
    label: "GPT 5.4 Mini",
  });

  assert.equal(catalog.services.llm.active_model_id, "gpt-old");
  assert.equal(next.services.llm.active_model_id, "gpt-5.4-mini");
  assert.equal(getActiveModel(next, "llm")?.model, "gpt-5.4-mini");
  assert.equal(next.services.llm.profiles[0].models.length, 2);
});

test("selectCatalogModel adds a fetched model to the active profile", () => {
  const catalog = baseCatalog();
  const next = selectCatalogModel(catalog, "llm", {
    id: "glm-5-venice",
    label: "GLM 5 Venice",
  });
  const active = getActiveModel(next, "llm");

  assert.equal(active?.model, "glm-5-venice");
  assert.equal(active?.name, "GLM 5 Venice");
  assert.equal(next.services.llm.profiles[0].models.length, 3);
});

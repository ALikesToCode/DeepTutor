# Cloudflare Containers Deployment

DeepTutor is a full Docker application: FastAPI on `BACKEND_PORT` and a Next.js
standalone server on `FRONTEND_PORT`. Deploy it to Cloudflare Workers with
Containers, not as a plain Worker-only app.

## Requirements

- Cloudflare Workers Paid plan with Containers enabled.
- Wrangler authenticated for the target account.
- Docker or a Docker-compatible CLI running locally when deploying from this
  checkout.

## Configure Secrets

Set the NavyAI key once in Cloudflare instead of committing it to
`wrangler.jsonc`:

```bash
wrangler secret put NAVY_API_KEY
```

Optional login/search/provider override secrets can be added the same way:

```bash
wrangler secret put DEEPTUTOR_AUTH_PASSWORD
wrangler secret put LLM_API_KEY
wrangler secret put EMBEDDING_API_KEY
wrangler secret put SEARCH_API_KEY
wrangler secret put BRAVE_API_KEY
wrangler secret put TAVILY_API_KEY
wrangler secret put GEMINI_API_KEY
wrangler secret put ANTHROPIC_API_KEY
```

Non-secret defaults live in `wrangler.jsonc`. Change `LLM_MODEL`, `LLM_HOST`,
embedding settings, Navy media model defaults, or search provider there when
needed.

NavyAI is the default all-in-one provider. `NAVY_API_KEY` is reused for chat
(`LLM_BINDING=navy`), embeddings (`EMBEDDING_BINDING=navy`), and the
`media_generation` tool. The default embedding model is
`gemini-embedding-2-preview`, which Navy exposes on `/v1/embeddings`, and
`EMBEDDING_SEND_DIMENSIONS=false` keeps the request compatible with Navy's
OpenAI-compatible endpoint.

## Deploy

Install the Cloudflare Worker dependencies once:

```bash
npm install
```

Deploy with Wrangler:

```bash
npm run cf:deploy
```

The first deploy builds the Docker image from `Dockerfile`, pushes it to
Cloudflare's registry, and then provisions the Container-backed Worker. The
first container start can take several minutes.

## R2 File Storage

Generated public artifacts are served through `/api/outputs/*`. In Cloudflare,
the Worker binds the `deeptutor-files` R2 bucket as `DEEPTUTOR_FILES` and checks
R2 before waking the application container. On a cache miss, it streams the file
from the container and writes the successful response back to R2 under the
`outputs/` prefix.

Create the bucket before deploying to a new account:

```bash
wrangler r2 bucket create deeptutor-files
```

## Check Status

```bash
npm run cf:containers:list
npm run cf:containers:images
npm run cf:tail
```

The Worker exposes `/_worker/health` without waking the application container.
App traffic goes through one container instance:

- `/api/*` routes to FastAPI on `BACKEND_PORT` (`8001` by default).
- All other routes route to the Next.js frontend on `FRONTEND_PORT` (`3782` by
  default).

## Persistence Note

Cloudflare Containers do not provide durable local storage. Per the
[Containers lifecycle documentation](https://developers.cloudflare.com/containers/platform-details/),
container disk is ephemeral: after an instance sleeps, the next start gets a
fresh disk from the image. Treat `data/` as a cache only.

Use Cloudflare managed storage for durable state:

| DeepTutor state | Current local path | Cloudflare target | Notes |
| --- | --- | --- | --- |
| SQLite/session state | `data/user/chat_history.db` and session JSON | [D1](https://developers.cloudflare.com/d1/) or [Durable Objects SQLite](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/) | Use D1 for normal relational tables. Use Durable Objects SQLite when one user/session/book needs strong single-owner coordination. |
| Settings | `data/user/settings/*` | [D1](https://developers.cloudflare.com/d1/), [Workers KV](https://developers.cloudflare.com/kv/), or Durable Objects SQLite | Use D1 for structured per-user settings. KV is acceptable for read-heavy config where eventual consistency is fine. |
| Notebooks | `data/user/workspace/notebook/*` | D1 + [R2](https://developers.cloudflare.com/r2/) | Store notebook metadata/indexes in D1 and larger document bodies or attachments in R2. |
| Books | `data/user/workspace/book/*` | D1 + R2 or Durable Objects SQLite + R2 | Store manifests, progress, spine, and page records in D1/DO SQLite; store assets and exports in R2. |
| Knowledge-base source files | `data/knowledge_bases/*/documents`, images, uploads | R2 | Store original PDFs, Office docs, extracted images, and generated artifacts as objects. |
| Knowledge-base vector/search indexes | `data/knowledge_bases/*/llamaindex_storage` or `rag_storage` | [Vectorize](https://developers.cloudflare.com/vectorize/) + R2/D1 metadata | Store embeddings in Vectorize; keep source text/object keys in R2 and metadata in D1. If keeping LlamaIndex locally, hydrate it from R2 into a temporary cache on container start. |
| Existing external SQL option | Local SQLite today | [Hyperdrive](https://developers.cloudflare.com/hyperdrive/) | If DeepTutor moves to Postgres/MySQL instead of D1, use Hyperdrive to pool and accelerate database access from Cloudflare. |
| Reindex/import jobs | Local process state | [Queues](https://developers.cloudflare.com/queues/) | Use Queues for durable background ingestion, reindexing, and media-processing work that should survive container restarts. |

Do not increase `max_instances` until the write paths above are moved off the
container filesystem or made safe to hydrate from R2/D1/Vectorize.

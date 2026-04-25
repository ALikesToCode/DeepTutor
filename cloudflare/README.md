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

This setup intentionally uses `max_instances: 1` because DeepTutor currently
stores runtime data under local `data/` paths. Cloudflare Container local disk is
not a shared application database. For durable multi-instance production use,
move knowledge bases, user workspace data, and generated outputs to a managed
store such as R2/D1/Postgres before increasing `max_instances`.

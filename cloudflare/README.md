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

Set secrets in Cloudflare instead of committing them to `wrangler.jsonc`:

```bash
wrangler secret put LLM_API_KEY
wrangler secret put EMBEDDING_API_KEY
```

Optional provider/search secrets can be added the same way:

```bash
wrangler secret put DEEPTUTOR_AUTH_PASSWORD
wrangler secret put SEARCH_API_KEY
wrangler secret put BRAVE_API_KEY
wrangler secret put TAVILY_API_KEY
wrangler secret put GEMINI_API_KEY
wrangler secret put ANTHROPIC_API_KEY
wrangler secret put NAVY_API_KEY
```

Non-secret defaults live in `wrangler.jsonc`. Change `LLM_MODEL`, `LLM_HOST`,
embedding settings, Navy media model defaults, or search provider there when
needed.

Gemini embeddings use Google's native batch embedding endpoint by default:
`EMBEDDING_BINDING=gemini`, `EMBEDDING_MODEL=gemini-embedding-2`, and
`EMBEDDING_HOST=https://generativelanguage.googleapis.com/v1beta`. Set either
`EMBEDDING_API_KEY` or `GEMINI_API_KEY` as a Worker secret.

For NavyAI, set `LLM_BINDING=navy`, `LLM_HOST=https://api.navy/v1`, and either
`LLM_API_KEY` or `NAVY_API_KEY`. Embeddings use the same host with
`EMBEDDING_BINDING=navy` and `EMBEDDING_SEND_DIMENSIONS=false`. The
`media_generation` tool uses `NAVY_API_KEY`, `NAVY_API_BASE`, `NAVY_IMAGE_MODEL`,
and `NAVY_VIDEO_MODEL` for image/video assets.

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

# Two services out of one file. Build a target, not the whole thing:
#
#   docker compose up --build
#   docker build --target orchestrator -t searchlight-orchestrator .
#
# Both default to offline: the committed terrain arrays and fixtures are all
# either image needs, so `docker compose up` works with no account anywhere.

# --- the orchestrator ------------------------------------------------------
FROM python:3.12.10-slim AS orchestrator

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SEARCHLIGHT_OFFLINE=1

WORKDIR /app

# requirements.txt is the application only. The geospatial stack that rebuilds
# data/ from source is pipeline/requirements.txt and is deliberately absent:
# the arrays it produces are committed, so nothing in a running container has
# any reason to recompute them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# data/ before the source, because the terrain arrays change far less often
# than the code and this layer is 38 MB.
COPY data/ ./data/
COPY fixtures/ ./fixtures/
COPY worker/ ./worker/
COPY model/ ./model/
COPY orchestrator/ ./orchestrator/

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# No --offline flag: SEARCHLIGHT_OFFLINE above is what decides, so switching
# to the live fleet is one environment variable rather than a different image.
CMD ["python", "orchestrator/server.py"]


# --- the web client --------------------------------------------------------
FROM node:24.19.0-slim AS web-build

WORKDIR /app

# NEXT_PUBLIC_* is inlined at BUILD time, not read at runtime. Setting these
# in compose's `environment:` would do nothing at all -- they have to arrive
# as build args and be present when `next build` runs.
ARG NEXT_PUBLIC_DATA_SOURCE=live
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
ENV NEXT_PUBLIC_DATA_SOURCE=$NEXT_PUBLIC_DATA_SOURCE \
    NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL

# One lockfile at the workspace root, so the install is reproducible from it
# alone and does not invalidate on a source change.
COPY package.json package-lock.json ./
COPY web/package.json ./web/
RUN npm ci

COPY web/ ./web/
RUN npm run build --workspace web


FROM node:24.19.0-slim AS web

ENV NODE_ENV=production
WORKDIR /app

COPY --from=web-build /app/node_modules ./node_modules
COPY --from=web-build /app/package.json ./package.json
COPY --from=web-build /app/web ./web

EXPOSE 3000

# The 1,060 committed terrain tiles are served from web/public/tiles, so the
# map draws with the network unplugged. That is the whole reason they are in
# the repository.
CMD ["npm", "run", "start", "--workspace", "web"]

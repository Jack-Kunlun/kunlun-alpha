FROM node:24.19.0-bookworm-slim AS node-build

ENV PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"

WORKDIR /workspace

RUN corepack enable && corepack prepare pnpm@11.21.0 --activate

COPY . .

RUN pnpm install --frozen-lockfile
RUN pnpm --filter @kunlun/server... run build \
    && pnpm --filter @kunlun/web... run build

FROM node-build AS server

ENV NODE_ENV=production
ENV PORT=3002

EXPOSE 3002

USER node

CMD ["node", "apps/server/dist/main.js"]

FROM node-build AS web

ENV NODE_ENV=production

RUN mkdir -p /workspace/apps/web/node_modules/.vite-temp \
    && chown -R node:node /workspace/apps/web/node_modules/.vite-temp

EXPOSE 4173

USER node

CMD ["pnpm", "--filter", "@kunlun/web", "preview", "--host", "0.0.0.0", "--port", "4173"]

FROM ghcr.io/astral-sh/uv:0.12.3 AS uv-bin
FROM python:3.12.13-slim-bookworm AS sample-engine

COPY --from=uv-bin /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_CACHE=1
ENV UV_NO_DEV=1

WORKDIR /workspace

COPY . .

RUN uv sync --locked --no-dev --package sample-engine
RUN groupadd --gid 10001 kunlun \
    && useradd --create-home --uid 10001 --gid 10001 kunlun

ENV PATH="/workspace/.venv/bin:${PATH}"

EXPOSE 8080

USER kunlun

CMD ["sample-engine"]

FROM python:3.12.13-slim-bookworm AS data-worker-migrate

COPY --from=uv-bin /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_CACHE=1
ENV UV_NO_DEV=1

WORKDIR /workspace

COPY . .

RUN uv sync --locked --no-dev --package data-worker
RUN groupadd --gid 10001 kunlun \
    && useradd --create-home --uid 10001 --gid 10001 kunlun \
    && mkdir -p /workspace/var/market-raw \
    && chown -R 10001:10001 /workspace/var

ENV PATH="/workspace/.venv/bin:${PATH}"

USER kunlun

FROM data-worker-migrate AS data-worker

CMD ["limit-pool-terminal-materialize"]

FROM python:3.12.13-slim-bookworm AS quant-engine

COPY --from=uv-bin /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_CACHE=1
ENV UV_NO_DEV=1

WORKDIR /workspace

COPY . .

RUN uv sync --locked --no-dev --package quant-engine
RUN groupadd --gid 10001 kunlun \
    && useradd --create-home --uid 10001 --gid 10001 kunlun

ENV PATH="/workspace/.venv/bin:${PATH}"

EXPOSE 8081

USER kunlun

CMD ["quant-engine"]

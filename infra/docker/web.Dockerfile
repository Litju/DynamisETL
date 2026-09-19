# DynamisData Performance Laboratory web image.
#
# Builds the React workbench and serves it from nginx, which also proxies /api
# to the analytical API service. Node and pnpm versions match the workspace
# engines; the build is reproducible from the frozen lockfile.
FROM node:24-slim AS build

RUN corepack enable

WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --filter @dynamis/web...

COPY apps/web ./apps/web
RUN pnpm --filter @dynamis/web run build

FROM nginx:1.29-alpine AS runtime

COPY infra/docker/web.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html

EXPOSE 80

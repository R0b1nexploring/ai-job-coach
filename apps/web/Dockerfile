# Build the React SPA, then serve it from Caddy together with the /api proxy.
# Build context is the repository root:
#   docker build -f apps/web/Dockerfile .
FROM node:22-alpine AS build

WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM caddy:2.8-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv/www

EXPOSE 80 443

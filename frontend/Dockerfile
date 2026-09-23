# TRAFFICINTEL AI - Operations Console
#
# Builds the Vite bundle, then serves it from nginx. No Node runtime ships in
# the final image: the console is static files, and a Node process in the
# runtime image would be attack surface serving no purpose.

# ---------------------------------------------------------------------------
# Stage 1: build
# ---------------------------------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /build

# Dependencies are installed from the lockfile before the sources are copied,
# so a source edit does not invalidate the dependency layer.
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# The console calls the API at the relative path /api/v1 and nginx proxies it
# to the backend, so no API URL is baked into the bundle. The same image is
# therefore promotable across environments unchanged - which matters, because
# an image rebuilt per environment is an image that was never the one tested.
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# nginx's own unprivileged image conventions: the worker already drops from
# root, and the cache/run paths below are writable by that user.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/cache/nginx /var/run/nginx.pid /usr/share/nginx/html

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1

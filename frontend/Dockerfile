FROM node:20-slim AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
# Railway passes the deployed commit; telemetry tags every event with it.
ARG RAILWAY_GIT_COMMIT_SHA=local
ENV VITE_RELEASE=$RAILWAY_GIT_COMMIT_SHA
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
# API upstream the SPA proxies /api to. Defaults to the `backend` service from
# docker-compose.yml, so a plain `docker compose up` works out of the box.
# Override both (service/env variables) to point at a hosted or staging API.
# nginx:alpine envsubst's ${VAR} in the template at startup (only env-defined vars).
ENV API_UPSTREAM=http://backend:8111 \
    API_HOST=backend \
    NGINX_RESOLVER="127.0.0.11 ipv6=off"
CMD ["nginx", "-g", "daemon off;"]

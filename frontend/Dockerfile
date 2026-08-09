FROM node:20-slim AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
# API upstream the SPA proxies /api to. Defaults to prod, so the prod build is
# unchanged; preview/staging Railway envs override these (service variables) to
# point at the staging API — keeping previews off prod data. nginx:alpine
# envsubst's ${VAR} in the template at startup (only env-defined vars).
ENV API_UPSTREAM=https://flowty-api-production.up.railway.app \
    API_HOST=flowty-api-production.up.railway.app
CMD ["nginx", "-g", "daemon off;"]

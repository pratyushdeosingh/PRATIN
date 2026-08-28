FROM node:22-alpine
WORKDIR /app
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ .
EXPOSE 5173
CMD ["pnpm","dev","--host","0.0.0.0"]


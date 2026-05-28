# Argus frontend (Next.js 14) — production image. Phase 5 / Week 25 / Day 1.
# Multi-stage: build with the public API URL baked in (NEXT_PUBLIC_* is
# inlined at build time), then run a slim `next start`.

# ---- build ----
FROM node:20-alpine AS builder
WORKDIR /app

# NEXT_PUBLIC_API_URL must be present at BUILD time — Next inlines it.
ARG NEXT_PUBLIC_API_URL=https://app.yourfirm.example
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .
RUN npm run build

# ---- run ----
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

# Copy the built app + production deps.
COPY --from=builder /app/package.json /app/package-lock.json* ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.* ./

EXPOSE 3000
CMD ["npm", "run", "start"]

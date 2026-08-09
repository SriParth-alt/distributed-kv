# Multi-stage: build the React dashboard, then serve it from the Python node.
# The image is self-contained — API + WebSockets + built UI.
#
# Two run modes, chosen by docker-entrypoint.sh:
#   docker compose  → passes --id/--members, so each container is one node
#   Render/Fly/etc. → no args, so the container runs the full cluster on $PORT

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY kvstore/ kvstore/
COPY launch_cluster.py docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh
# node.py serves this directory at / when it exists
COPY --from=web /web/dist web/dist

ENV PORT=8001
EXPOSE 8000 8001
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Multi-stage: build the React dashboard, then serve it from the Python node.
# The resulting image is a single self-contained Helix node — API + UI.

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
COPY launch_cluster.py ./
# node.py serves this directory at / when it exists
COPY --from=web /web/dist web/dist

EXPOSE 8000
# node id / members are supplied by docker-compose
ENTRYPOINT ["python", "-m", "kvstore.node", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn requests

COPY kvstore/ kvstore/

EXPOSE 8000
# node id / members are supplied by docker-compose
ENTRYPOINT ["python", "-m", "kvstore.node", "--host", "0.0.0.0", "--port", "8000"]

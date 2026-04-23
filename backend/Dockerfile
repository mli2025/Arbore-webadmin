FROM python:3.11-slim

WORKDIR /app

# Minimal system deps only: we no longer shell out to docker/docker-compose from
# inside the container; all Docker Engine work is proxied to Portainer over HTTP.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]

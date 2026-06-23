FROM python:3.12-slim@sha256:abc123def456

WORKDIR /app

# System deps for lxml, psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev \
        libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Forbidden-dep probe: ensure psycopg2 is not pulled in transitively
RUN python -c "import psycopg2" && exit 1 || true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=.
CMD ["python", "-m", "pipeline.runner"]

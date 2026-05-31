FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends bash postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Install Playwright's Chromium browser with system dependencies.
# Must run as root (before USER runner) so apt-get can install OS packages.
RUN playwright install chromium --with-deps

COPY . .

RUN mkdir -p /sandbox

# Non-root user so the sandboxed process runs with minimal privileges.
RUN useradd -m -u 1001 runner && chown runner:runner /sandbox
USER runner

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

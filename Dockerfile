# ── Stage 1: Build deps ────────────────────────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime ───────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app

# Install curl for healthcheck (minimal, no cache)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user BEFORE copying files
RUN useradd -m -u 1000 -s /bin/bash breeze

# Copy installed Python packages from builder
COPY --from=builder /root/.local /home/breeze/.local
ENV PATH=/home/breeze/.local/bin:$PATH

# Copy application source (as root, then chown)
COPY . .

# Create writable dirs and transfer ownership
RUN mkdir -p logs data \
    && chown -R breeze:breeze /app

# Switch to non-root user for runtime
USER breeze

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

EXPOSE 8501 8000

CMD ["sh", "-c", \
  "uvicorn app.api.main:app --host 0.0.0.0 --port 8000 & \
   streamlit run app.py --server.port=8501 --server.address=0.0.0.0 \
   --server.headless=true --browser.gatherUsageStats=false"]

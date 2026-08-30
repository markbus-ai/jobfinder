FROM python:3.12-slim AS base

# Install system deps + Typst
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fonts-liberation \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Install Typst
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then TARCH="x86_64"; \
    elif [ "$ARCH" = "arm64" ]; then TARCH="aarch64"; \
    fi && \
    curl -fsSL "https://github.com/typst/typst/releases/download/v0.15.1/typst-x86_64-unknown-linux-musl.tar.xz" -o /tmp/typst.tar.xz && \
    tar -xf /tmp/typst.tar.xz -C /tmp && \
    mv /tmp/typst-x86_64-unknown-linux-musl/typst /usr/local/bin/typst && \
    chmod +x /usr/local/bin/typst && \
    rm -rf /tmp/typst*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create CV output dir
RUN mkdir -p /tmp/jobfinder_cvs

# Expose nothing — this is a long-running worker, not a web server

CMD ["python", "main.py"]

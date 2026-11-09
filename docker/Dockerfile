FROM node:24.9.0-bookworm-slim
LABEL org.harness-bench.managed="true"
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates ripgrep unzip procps && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/data && /opt/data/bin/pip install --no-cache-dir numpy==2.3.4 pandas==2.3.3 scikit-learn==1.7.2
ENV PATH="/opt/data/bin:/root/.bun/bin:${PATH}"
WORKDIR /workspace

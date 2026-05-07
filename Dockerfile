FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY src/ ./src/

ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8080

EXPOSE 8080

CMD ["uvicorn", "src.server:root_app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "4", "--loop", "uvloop", \
     "--log-config", "src/log_config.json"]

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY agent ./agent
COPY apps ./apps
COPY data ./data
COPY evals ./evals
COPY gigsim ./gigsim
COPY mcp_servers ./mcp_servers
COPY rag ./rag
COPY worker ./worker
RUN python -m pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

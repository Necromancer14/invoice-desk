# Stage 1: build the React portal
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Stage 2: the API, serving the built portal. Port 7860 is what Hugging Face Spaces expects.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DEMO_MODE=1
RUN useradd -m -u 1000 app
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e ".[claude]"
COPY data ./data
COPY --from=web /web/dist ./web/dist
USER app
EXPOSE 7860
CMD ["uvicorn", "invoice_desk.api:app", "--host", "0.0.0.0", "--port", "7860"]

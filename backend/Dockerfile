FROM python:3.11-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY backend/pyproject.toml ./
RUN uv pip install --system -r pyproject.toml
COPY backend/ ./
COPY fixtures/ /fixtures/
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

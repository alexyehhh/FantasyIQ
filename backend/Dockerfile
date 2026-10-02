FROM python:3.11-slim

WORKDIR /app

# Install dependencies against empty package stubs so this slow layer is only rebuilt when
# pyproject.toml changes, not on every code edit. The real code is copied in afterwards; the
# editable install points at /app/app and /app/data_pipeline, so it picks the code up.
COPY pyproject.toml .
RUN mkdir -p app data_pipeline && touch app/__init__.py data_pipeline/__init__.py \
    && pip install --no-cache-dir -e ".[dev,ml]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

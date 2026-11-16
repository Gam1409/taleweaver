# Stage 1: Build frontend
FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend

# Copy package files and install dependencies
COPY frontend/package*.json ./
RUN npm ci

# Copy frontend source and build
COPY frontend/ ./
RUN npm run build

# Stage 2: Final image
FROM python:3.12-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

RUN pip install --no-cache-dir "poetry>=2.0.0"

# Install python dependencies
COPY pyproject.toml poetry.lock README.md ./
ARG INSTALL_CONCORDIA=false
RUN case "$INSTALL_CONCORDIA" in \
      true) poetry install --no-root --without dev --extras concordia ;; \
      false) poetry install --no-root --without dev ;; \
      *) echo "INSTALL_CONCORDIA must be true or false" >&2; exit 1 ;; \
    esac


# Copy backend code
COPY backend/ ./backend/
COPY desktop/ ./desktop/
COPY scripts/ ./scripts/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY version.json .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Install project package
RUN poetry install --only-root

# Copy adventures (for automatic import)
COPY adventures/ ./adventures/

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend_dist
COPY frontend/src/assets/svg/ ./frontend/src/assets/svg/

# Expose backend port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=data

# Run migrations then start the application
ENTRYPOINT ["./entrypoint.sh"]

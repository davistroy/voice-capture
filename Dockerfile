# Voice Capture to Notion Pipeline
# Multi-stage build for smaller final image

# =============================================================================
# Build stage - install dependencies
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
# Use requirements.lock for reproducible production builds with pinned versions
COPY requirements.lock .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock

# =============================================================================
# Runtime stage - minimal image
# =============================================================================
FROM python:3.11-slim as runtime

# Labels for container metadata
LABEL maintainer="Troy Davis <troy@stratfieldconsulting.com>"
LABEL description="Voice Capture to Notion Pipeline"
LABEL version="0.1.0"

# Create non-root user for security
RUN groupadd -r voicecapture && useradd -r -g voicecapture voicecapture

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories for data, logs, and processing
RUN mkdir -p /app/data /app/logs /app/inbox /app/processing /app/failed && \
    chown -R voicecapture:voicecapture /app

# Switch to non-root user
USER voicecapture

# Environment variables with defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VOICE_CAPTURE_INBOX_PATH=/app/inbox \
    VOICE_CAPTURE_PROCESSING_PATH=/app/processing \
    VOICE_CAPTURE_FAILED_PATH=/app/failed \
    VOICE_CAPTURE_DB_PATH=/app/data/voice_capture.db \
    VOICE_CAPTURE_LOG_PATH=/app/logs \
    VOICE_CAPTURE_LOG_LEVEL=INFO

# Health check - verify Python and key module are available
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from src.config.settings import get_settings; print('OK')" || exit 1

# Default command - run the main application
CMD ["python", "-m", "src.main"]

FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
COPY backend/ backend/
RUN pip install --no-cache-dir -e .

# Copy entry point
COPY run.py .

# Create data directory for SQLite
RUN mkdir -p data

EXPOSE 8111

CMD ["python", "run.py"]

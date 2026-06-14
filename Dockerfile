FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
COPY backend/ backend/
RUN pip install --no-cache-dir -e .

# Copy entry point
COPY run.py .
COPY scripts/ scripts/

# AP-157: workspace-default agent templates. App code (versioned with
# the repo), not user data — ships in the image.
COPY templates/ templates/

# Create data directory for SQLite
RUN mkdir -p data

EXPOSE 8111

# Seed the DB (idempotent: tables + migrations + default roles/statuses/admin
# + agent templates) before serving, so a fresh Postgres on Railway is usable
# on first boot. Mirrors the dev compose command.
CMD ["sh", "-c", "python scripts/bootstrap_db.py && python run.py"]

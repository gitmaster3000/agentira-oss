FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies from the lock (exact, reproducible versions),
# then the app itself without re-resolving.
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ backend/
RUN pip install --no-cache-dir --no-deps -e .

# Bake agentira-cli wheel into the image for customer install/update.
COPY agentira-cli/ agentira-cli/
COPY scripts/write_cli_manifest.py scripts/write_cli_manifest.py
RUN pip install --no-cache-dir build \
    && python -m build agentira-cli/ -o /tmp/cli-dist \
    && mkdir -p backend/static/cli/wheels \
    && cp /tmp/cli-dist/*.whl backend/static/cli/wheels/ \
    && python scripts/write_cli_manifest.py

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

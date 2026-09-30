FROM python:3.12-slim

ARG OPENWORKER_REF=c34615de73e97f7df899f471a6c12caa45b44b83

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "git+https://github.com/andrewyng/openworker@${OPENWORKER_REF}"

RUN useradd -m -u 1000 agent
USER agent
ENV COWORKER_STATE_DIR=/home/agent/state
RUN mkdir -p /home/agent/state /home/agent/work
WORKDIR /home/agent/work

EXPOSE 8765
# COWORKER_API_TOKEN must be supplied at `docker run` time; without it the server has no auth.
CMD ["openworker-server", "--host", "0.0.0.0", "--port", "8765", "--cwd", "/home/agent/work", "--mode", "auto"]

# Quickstart

`agentira.yml` runs Agentira from published images. No build, no clone.

```bash
curl -fsSL https://raw.githubusercontent.com/gitmaster3000/agentira-oss/main/quickstart/agentira.yml -o agentira.yml
docker compose -f agentira.yml up -d
docker compose -f agentira.yml logs backend | grep "Admin password:"
```

Open http://localhost:3111 and sign in as `admin`.

Most people should use the installer instead, which does the above plus the
daemon: see the quickstart guide in the documentation.

## Before exposing this to a network

Every port binds to `127.0.0.1`. If you change that, first:

- Set `JWT_SECRET` to a generated value: `openssl rand -hex 32`
- Set `POSTGRES_PASSWORD` to something other than `agentira-local`
- Change the admin password in the interface
- Put TLS in front of it

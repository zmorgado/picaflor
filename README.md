# Picaflor

Telegram bot that finds unusually cheap European trips for a small friend group.
Powered by [`fast-flights`](https://aweird.me/flights/).

See [CLAUDE.md](CLAUDE.md) for project goals, version roadmap, and architecture.

## v0.1 — Open-Jaw Nomad MVP

Single-user Telegram bot running on a DigitalOcean droplet. Scrapes Google
Flights via `fast-flights`. No AWS, no LLM, no web UI.

### Run locally

```
cp .env.example .env       # fill TG_BOT_TOKEN
docker compose up bot      # start the long-poll bot
docker compose run --rm scanner   # one-shot scan
```

### Edit what gets scanned

See [config/README.md](config/README.md).

# State Layout

This directory exists to make AI Radio state explicit and portable.

## Bind-mounted targets

- `state/postgres/`
  PostgreSQL data directory for the `postgres` service when using `docker-compose.bind.yml`
- `state/storage/`
  AI Radio runtime storage mounted at `/var/lib/ai-radio`

## Why this exists

The default stack uses named Docker volumes. That works, but it hides the actual
data locations and makes migration, backup, and inspection harder than needed.

Using `docker-compose.bind.yml` moves state into the project tree so you can:

- back it up with `tar` or `rsync`
- inspect storage without `docker volume inspect`
- move the project to another host with fewer hidden dependencies

## Migrate existing named volumes

Run:

```bash
./scripts/migrate_docker_volumes_to_state.sh
```

Then start the stack with:

```bash
docker compose -f docker-compose.yml -f docker-compose.bind.yml up -d --build
```

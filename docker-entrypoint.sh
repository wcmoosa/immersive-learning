#!/bin/sh
set -e

# Seed the database on first boot (idempotent — leaves existing data alone).
python -m app.seed ensure

exec "$@"

#!/usr/bin/env bash
set -e

# echo "▶️  Starte MariaDB …"
# docker start some-mariadb

# echo "▶️  Starte Redis …"
# docker start redis

echo "▶️  Starte Jaeger …"
docker start jaeger

echo "▶️  Starte ngrok …"
docker run -d --rm \
  --name ngrok \
  --env-file .env \
  ngrok-container
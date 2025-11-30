#!/bin/sh
set -e

echo "🟢 ngrok Authtoken wird gesetzt..."
ngrok config add-authtoken "$NGROK_AUTHTOKEN"

echo "🚀 Starte ngrok mit URL: $NGROK_URL und Port: $NGROK_PORT"
exec ngrok http --url="$NGROK_URL" "$NGROK_PORT"
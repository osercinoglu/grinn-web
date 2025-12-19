#!/bin/bash

REMOTE_USER="root"
REMOTE_HOST=
SSH_KEY=

# Build port forwarding arguments
PORTS="-R 8081:localhost:8051"      # Frontend
PORTS="$PORTS -R 5000:localhost:5000"  # Backend API

# Dashboard ports (8100-8109)
for port in $(seq 8100 8109); do
    PORTS="$PORTS -R ${port}:localhost:${port}"
done

exec /usr/bin/ssh -i "$SSH_KEY" \
    -o ServerAliveInterval=60 \
    -o ExitOnForwardFailure=yes \
    -gnNT \
    $PORTS \
    ${REMOTE_USER}@${REMOTE_HOST}
#!/bin/bash

# Set default port values if not already set
MCP_SERVER_PORT=${MCP_SERVER_PORT:-8000}
MCPO_SERVER_PORT=${MCPO_SERVER_PORT:-8001}
QDRANT_URL=${QDRANT_URL:-http://localhost:6333}

# Wait for Qdrant to be ready
echo "Waiting for Qdrant server to start at ${QDRANT_URL}..."
while ! curl -s --fail ${QDRANT_URL}/readyz > /dev/null; do
    sleep 1
done
echo "Qdrant server started."

# Define a function to handle graceful shutdown
_shutdown() {
  echo "Caught signal! Shutting down gracefully..."
  # Send SIGTERM to all background processes
  kill -TERM "$uvicorn_app_pid" "$uvx_mcpo_pid"
  # Wait for all background processes to terminate
  wait "$uvicorn_app_pid" "$uvx_mcpo_pid"
  echo "All background servers shut down."
}

# Trap SIGTERM and SIGINT signals and call the shutdown function
trap _shutdown SIGTERM SIGINT

# Start the uvicorn server for app:app on port 8000 in the background
echo "Starting uvicorn server for app:app on port 8000..."
uvicorn app:app --host 0.0.0.0 --port ${MCP_SERVER_PORT} --timeout-keep-alive 300 &
uvicorn_app_pid=$!

# Wait for all servers to be up and running
echo "Waiting for uvicorn server on port ${MCP_SERVER_PORT} to start..."
while ! curl -s --fail http://localhost:${MCP_SERVER_PORT}/api/health > /dev/null; do
    sleep 1
done
echo "Uvicorn server on port 8000 started."

# Start the uvx mcpo server on port 8001 in the background
echo "Starting uvx mcpo server on port 8001..."
uvx mcpo --port ${MCPO_SERVER_PORT} --server-type "streamable-http" -- "http://localhost:${MCP_SERVER_PORT}/mcp" &
uvx_mcpo_pid=$!

# Wait for uvx mcpo server to be up and running
echo "Waiting for uvx mcpo server on port ${MCPO_SERVER_PORT} to start..."
while ! (</dev/tcp/localhost/${MCPO_SERVER_PORT}) &>/dev/null; do
    sleep 1
done
echo "uvx mcpo server on port 8001 started." 
# Start the proxy server in the foreground
echo "Starting proxy server on port 3000..."
uvicorn proxy:app --host 0.0.0.0 --port 3000 --timeout-keep-alive 300

# The script will wait here until the proxy uvicorn command exits or a signal is caught.
# The 'wait' command in _shutdown ensures that the background processes are handled.
wait "$uvicorn_app_pid" "$uvx_mcpo_pid"

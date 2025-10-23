#!/bin/bash

# Set default port values if not already set
MCP_SERVER_PORT=${MCP_SERVER_PORT:-8000}
MCPO_SERVER_PORT=${MCPO_SERVER_PORT:-8001}
WEB_SERVER_PORT=${WEB_SERVER_PORT:-8002}

# Define a function to handle graceful shutdown
_shutdown() {
  echo "Caught signal! Shutting down gracefully..."
  # Send SIGTERM to all background processes
  kill -TERM "$uvicorn_app_pid" "$uvx_mcpo_pid" "$vanna_web_app_pid"
  # Wait for all background processes to terminate
  wait "$uvicorn_app_pid" "$uvx_mcpo_pid" "$vanna_web_app_pid"
  echo "All background servers shut down."
}

# Trap SIGTERM and SIGINT signals and call the shutdown function
trap _shutdown SIGTERM SIGINT

# Start the uvicorn server for app:app on port 8000 in the background
echo "Starting uvicorn server for app:app on port 8000..."
uvicorn app:app --host 0.0.0.0 --port ${MCP_SERVER_PORT} --timeout-keep-alive 300 &
uvicorn_app_pid=$!

# Start the uvx mcpo server on port 8001 in the background
echo "Starting uvx mcpo server on port 8001..."
uvx mcpo --port ${MCPO_SERVER_PORT} --server-type "streamable-http" -- "http://localhost:${MCP_SERVER_PORT}/mcp" &
uvx_mcpo_pid=$!

# Start the Vanna web app on port 8002 in the background
echo "Starting Vanna web app on port 8002..."
uvicorn vanna_web_app:app --host 0.0.0.0 --port ${WEB_SERVER_PORT} --timeout-keep-alive 300 &
vanna_web_app_pid=$!

# Wait for all servers to be up and running
echo "Waiting for uvicorn server on port ${MCP_SERVER_PORT} to start..."
while ! curl -s --fail http://localhost:${MCP_SERVER_PORT}/health > /dev/null; do
    sleep 1
done
echo "Uvicorn server on port 8000 started."

echo "Waiting for uvx mcpo server on port ${MCPO_SERVER_PORT} to start..."
while ! nc -z localhost ${MCPO_SERVER_PORT}; do
    sleep 1
done
echo "uvx mcpo server on port 8001 started."

echo "Waiting for Vanna web app on port ${WEB_SERVER_PORT} to start..."
while ! nc -z localhost ${WEB_SERVER_PORT}; do
    sleep 1
done
echo "Vanna web app on port 8002 started."

# Start the proxy server in the foreground
echo "Starting proxy server on port 3000..."
uvicorn proxy:app --host 0.0.0.0 --port 3000 --timeout-keep-alive 300

# The script will wait here until the proxy uvicorn command exits or a signal is caught.
# The 'wait' command in _shutdown ensures that the background processes are handled.
wait "$uvicorn_app_pid" "$uvx_mcpo_pid" "$vanna_web_app_pid"

#!/bin/bash

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

# Start the uvicorn server for app:app in the background
echo "Starting uvicorn server for app:app on port 8000..."
uvicorn app:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 300 &
uvicorn_app_pid=$!

# Start the uvx mcpo server in the background
echo "Starting uvx mcpo server on port 8001..."
uvx mcpo --port 8001 --server-type "streamable-http" -- "http://localhost:8000/mcp" &
uvx_mcpo_pid=$!

# Wait for both servers to be up and running
echo "Waiting for uvicorn server on port 8000 to start..."
while ! curl -s --fail http://localhost:8000/health > /dev/null; do
    sleep 1
done
echo "Uvicorn server on port 8000 started."

echo "Waiting for uvx mcpo server on port 8001 to start..."
# Assuming mcpo also has a health endpoint or just waits for it to be listening
# For now, we'll just check if the port is open. A proper health check would be better.
while ! nc -z localhost 8001; do
    sleep 1
done
echo "uvx mcpo server on port 8001 started."

# Start the proxy server in the foreground
echo "Starting proxy server on port 3000..."
uvicorn proxy:app --host 0.0.0.0 --port 3000 --timeout-keep-alive 300

# The script will wait here until the proxy uvicorn command exits or a signal is caught.
# The 'wait' command in _shutdown ensures that the background processes are handled.
wait "$uvicorn_app_pid" "$uvx_mcpo_pid"

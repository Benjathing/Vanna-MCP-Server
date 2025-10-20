#!/bin/bash

# Define a function to handle graceful shutdown
_shutdown() {
  echo "Caught signal! Shutting down gracefully..."
  # Send SIGTERM to the uvicorn process
  kill -TERM "$uvicorn_pid"
  # Wait for the uvicorn process to terminate
  wait "$uvicorn_pid"
  echo "Uvicorn shut down."
}

# Trap SIGTERM and SIGINT signals and call the shutdown function
trap _shutdown SIGTERM SIGINT

# Start the uvicorn server in the background
echo "Starting uvicorn server..."
uvicorn app:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 300 &
# Store its PID
uvicorn_pid=$!

# Wait for the server to be up and running by polling the /health endpoint
echo "Waiting for uvicorn server to start..."
while ! curl -s --fail http://localhost:8000/health > /dev/null; do
    sleep 1
done
echo "Uvicorn server started."

# Start the uvx mcpo server in the foreground
# This will keep the script running and will be terminated when the script exits
echo "Starting uvx mcpo server..."
uvx mcpo --port 8001 --server-type "streamable-http" -- "http://localhost:8000/mcp"

# The script will wait here until the uvx command exits or a signal is caught.
# The 'wait' command ensures that the script waits for the background process 
# to finish if it hasn't already, which is handled by our trap.
wait "$uvicorn_pid"

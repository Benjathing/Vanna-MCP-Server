# Session Summary: Vanna AI MCP Server Setup

This document summarizes the key steps and resolutions from a session focused on setting up and connecting to the Vanna AI MCP Server.

## Project State at Session End:

*   **Operating System:** Windows
*   **Project Directory:** `C:\docker\VannaMCP\vanna-mcp-server`
*   **Package Manager:** `uv` (used for `pip sync` and `pip install`)

## Key Changes & Resolutions:

1.  **`app.py` Modification:**
    The `app.py` file was modified to expose the ASGI application correctly for `uvicorn`. The following line was added permanently before the `if __name__ == '__main__':` block:
    ```python
asgi_app = mcp.streamable_http_app()
    ```

2.  **`README.md` Update:**
    The `README.md` file was updated with the new, correct server startup and inspector connection instructions.

## How to Run the Server:

To start the Vanna AI MCP Server in the background, run the following command from the project root directory:

```sh
start /b C:\docker\VannaMCP\vanna-mcp-server\.venv\Scripts\python.exe -m uvicorn app:asgi_app --host 127.0.0.1 --port 8000
```

## How to Connect with `mcp-inspector`:

1.  **Start `mcp-inspector`:** Open a **new terminal** in a **different directory** (one that does not contain a `.env` file) and run:
    ```sh
mcp-inspector
    ```

2.  **Configure Connection in UI:** In the `mcp-inspector` UI that opens in your browser:
    *   Set **Transport Type** to `streamable-http`.
    *   Set the **URL** to `http://127.0.0.1:8000/mcp`.
    *   Click **Connect**.

## Debugging Insights:

*   `uvicorn` requires a callable ASGI application object. The `FastMCP` instance itself is not directly callable.
*   The `mcp.streamable_http_app()` method returns the actual ASGI application.
*   `mcp-inspector`'s `--url` argument is not for direct server connection; it's configured via the UI.
*   The `sse` transport in `mcp-inspector` is deprecated; `streamable-http` should be used.
*   The `FastMCP` server exposes its endpoint at `/mcp` when using `streamable_http_app()`.
*   Dependency issues (`chromadb`, `pywintypes`) were resolved by explicit `uv pip install` commands.

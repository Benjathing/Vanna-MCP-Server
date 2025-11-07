from fastapi import FastAPI, Request, WebSocket
from fastapi.routing import APIRouter
from fastapi_proxy_lib.core.http import ReverseHttpProxy
from fastapi_proxy_lib.core.websocket import ReverseWebSocketProxy
import httpx

TARGET_MCPO_HOST = "http://localhost:8001/"
TARGET_DEFAULT_HOST = "http://localhost:8000/"

app = FastAPI()

# Create a single httpx.AsyncClient instance to be reused
shared_client = httpx.AsyncClient(follow_redirects=True)

# Proxy for MCPO (HTTP and WebSocket)
mcpo_proxy_app = FastAPI()
mcpo_http_proxy = ReverseHttpProxy(client=shared_client, base_url=TARGET_MCPO_HOST)
mcpo_ws_proxy = ReverseWebSocketProxy(client=shared_client, base_url=TARGET_MCPO_HOST.replace("http", "ws"))

@mcpo_proxy_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_mcpo_http(request: Request, path: str):
    return await mcpo_http_proxy.proxy(request=request, path=path)

@mcpo_proxy_app.websocket("/{path:path}")
async def proxy_mcpo_ws(websocket: WebSocket, path: str):
    await mcpo_ws_proxy.proxy(websocket=websocket, path=path)

app.mount("/mcpo", mcpo_proxy_app)

# Proxy for MCP (HTTP)
mcp_proxy_app = FastAPI()
mcp_http_proxy = ReverseHttpProxy(client=shared_client, base_url=TARGET_DEFAULT_HOST)

@mcp_proxy_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_mcp_http(request: Request, path: str):
    return await mcp_http_proxy.proxy(request=request, path=f"/mcp/{path}")

app.mount("/mcp", mcp_proxy_app)

# Proxy for SSE (WebSocket)
sse_proxy_app = FastAPI()
sse_ws_proxy = ReverseWebSocketProxy(client=shared_client, base_url=TARGET_DEFAULT_HOST.replace("http", "ws"))

@sse_proxy_app.websocket("/{path:path}")
async def proxy_sse_ws(websocket: WebSocket, path: str):
    await sse_ws_proxy.proxy(websocket=websocket, path=f"/sse/{path}")

app.mount("/sse", sse_proxy_app)

# Proxy for all other requests (HTTP and WebSocket)
http_proxy = ReverseHttpProxy(client=shared_client, base_url=TARGET_DEFAULT_HOST)
ws_proxy = ReverseWebSocketProxy(client=shared_client, base_url=TARGET_DEFAULT_HOST.replace("http", "ws"))

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_http(request: Request, path: str):
    return await http_proxy.proxy(request=request, path=path)

@app.websocket("/{path:path}")
async def proxy_ws(websocket: WebSocket, path: str):
    await ws_proxy.proxy(websocket=websocket, path=path)
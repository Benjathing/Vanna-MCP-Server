import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse, Response
from starlette.background import BackgroundTask
import asyncio

TARGET_MCPO_HOST = "http://localhost:8001"
TARGET_DEFAULT_HOST = "http://localhost:8000"
TARGET_WEB_HOST = "http://localhost:8002"

client = httpx.AsyncClient()

async def _proxy(request: Request):
    path = request.url.path
    if path.startswith("/mcpo"):
        target_host = TARGET_MCPO_HOST
        # Strip /mcpo prefix when forwarding to the mcpo server
        url = httpx.URL(path=path[5:], query=request.url.query.encode("utf-8"))
    # elif path.startswith("/web"):
    #     target_host = TARGET_WEB_HOST
    #     # Strip /web prefix when forwarding to the web server
    #     url = httpx.URL(path=path[4:], query=request.url.query.encode("utf-8"))
    else:
        target_host = TARGET_DEFAULT_HOST
        url = httpx.URL(path=path, query=request.url.query.encode("utf-8"))

    # Prepare the request to be forwarded
    headers = dict(request.headers)
    # httpx uses 'host' header to connect, which might not be what we want
    headers.pop("host", None)
    
    rp_req = client.build_request(
        request.method,
        headers=headers,
        content=request.stream(),
        url=f"{target_host}{url.path}?{url.query.decode('utf-8')}"
    )
    
    # Forward the request and stream the response back
    try:
        rp_resp = await client.send(rp_req, stream=True)
    except httpx.ConnectError as e:
        return Response(f"Connection to {target_host} failed: {e}", status_code=502)

    return StreamingResponse(
        rp_resp.aiter_raw(),
        status_code=rp_resp.status_code,
        headers=rp_resp.headers,
        background=BackgroundTask(rp_resp.aclose),
    )

app = Starlette()
app.add_route("/{path:path}", _proxy, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])

import os
from dotenv import load_dotenv
load_dotenv()

from vanna_instance import MyVanna # Import MyVanna from your new vanna_instance.py
from vanna.flask import VannaFlaskApp
import logging
from a2wsgi import WSGIMiddleware

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LOCK_FILE = "/tmp/vanna_mcp_server.lock"

class VannaWebApp:
    def __init__(self, vn: MyVanna):
        self.vn = vn
        # Create the Vanna Flask app
        vanna_flask_app_container = VannaFlaskApp(self.vn, allow_llm_to_see_data=True)

        # Wrap the Flask app with WSGIMiddleware to make it an ASGI app
        self.app = WSGIMiddleware(vanna_flask_app_container.flask_app)

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)
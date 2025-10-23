import os
from dotenv import load_dotenv
load_dotenv()

from app import MyVanna # Import MyVanna from your existing app.py
from vanna.flask import VannaFlaskApp
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration for MyVanna
config = {
    "url": os.getenv("QDRANT_URL")
}

odbc_conn_str = os.getenv("ODBC_CONN_STR")

# Instantiate MyVanna
vn = MyVanna(config=config)
logging.info("🔗 Connecting Vanna Web App to SQL database...")
try:
    vn.connect_to_mssql(odbc_conn_str)
    logging.info("✅ Vanna Web App database connection successful.")
except Exception as e:
    logging.error(f"💥 VANNA WEB APP DATABASE CONNECTION FAILED: {e}", exc_info=True)
    raise

# Create and run the Vanna Flask app
app = VannaFlaskApp(vn, allow_llm_to_see_data=True)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

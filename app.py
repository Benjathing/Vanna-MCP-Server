from dotenv import load_dotenv
load_dotenv()

import os
import json
from typing import Literal, Any, Annotated, Dict, List, Callable, Coroutine
from fastapi import FastAPI, Request, HTTPException
from fastapi.routing import APIRouter
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
import inspect
from pydantic import Field
import pandas as pd
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import time
from openpyxl import load_workbook
from sqlalchemy import event

from vanna_instance import MyVanna
from vanna_web_app import VannaWebApp
# Import MCP and anyio components
from mcp.server.fastmcp import FastMCP, Context
import anyio

# Import and configure the logging module
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import signal
import sys

LOCK_FILE = "/tmp/vanna_mcp_server.lock"

def shutdown_handler(signum, frame):
    logging.info("Received shutdown signal. Cleaning up MCP server...")
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        sys.exit(0)
    except Exception as e:
        logging.error(f"Error during shutdown: {e}")
        sys.exit(1)

# Register signal handlers
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# Load environment variables from .env file
load_dotenv()

class Thingy:
    def __init__(self, name: str):
        self.name = name
        
    def greet(self) -> str:
        return f"Hello, I am {self.name}!"

@dataclass
class AppState:
    vn: MyVanna
    mcp_server: FastMCP
    th: Thingy

@dataclass
class MCPLifeSpanContext:
    vn: MyVanna
    th: Thingy

# Create the router that will hold the dynamic MCPO endpoints
mcpo_router = APIRouter()
# Create the FastMCP instance
mcp_instructions = "A server that uses Vanna AI to answer questions about a {}".format(os.getenv("DB_DESCRIPTION", "financial database"))
# Define the lifespan for the MCP server itself
@asynccontextmanager
async def mcp_vanna_lifespan(mcp_instance: FastMCP) -> AsyncIterator[MCPLifeSpanContext]:
    logging.info("🚀 Vanna AI instance starting up (MCP internal lifespan)...")
    config = {
        "url": os.getenv("QDRANT_URL")
    }
    
    odbc_conn_str = os.getenv("ODBC_CONN_STRING")
    
    vn = MyVanna(config=config)
    th = Thingy(name="Vanna MCP Thingy")
    logging.info("🔗 Connecting to SQL database...")
    try:
        vn.connect_to_mssql(odbc_conn_str)
        logging.info("✅ Database connection successful.")
    except Exception as e:
        logging.error(f"💥 DATABASE CONNECTION FAILED: {e}", exc_info=True)
        # In a containerized environment, you might want to exit here
        # to make the container crash explicitly, which makes debugging easier.
        raise
    logging.info("✅ Vanna AI is ready. Server is online.")
    yield MCPLifeSpanContext(vn=vn, th=th) # This 'vn' will be available as lifespan_context in MCP tools
    logging.info("🔌 Vanna AI instance shutting down (MCP internal lifespan)...")

# Create the FastMCP instance, passing the custom lifespan
mcp_server = FastMCP(
    name="Vanna RAG-to-DB MCP Server for {}".format(os.getenv("DB_DESCRIPTION", "financial database")),
    instructions=mcp_instructions,
    sse_path="/",  # Set internal SSE path to root
    streamable_http_path="/", # Set internal Streamable HTTP path to root
    lifespan=mcp_vanna_lifespan # Pass the custom lifespan here
)

@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncIterator[None]: # FastAPI lifespan yields None
    logging.info("🚀 FastAPI app starting up...")
    
    # The mcp_server's internal lifespan (mcp_vanna_lifespan) will be managed by FastMCP itself
    # We just need to ensure the session manager is run.
    mcp_http_app = mcp_server.streamable_http_app()
    sse_app = mcp_server.sse_app()
    """
    mcp_lifespan_ctx = mcp_vanna_lifespan(mcp_server)
    mcp_context = await mcp_lifespan_ctx.__aenter__()  # yields MCPLifeSpanContext
    try:
        vn_instance = mcp_context.vn
        vanna_web_app = VannaWebApp(vn=vn_instance)
        async with mcp_server.session_manager.run():
            app.mount("/mcp", mcp_http_app)
            app.mount("/sse", sse_app)
            # Create and mount the Vanna Web App at the root
            app.mount("/", vanna_web_app)

            # The AppState is now just for FastAPI's state, not for MCP's lifespan context
            app.state.app_state = AppState(vn=vn_instance, mcp_server=mcp_server)

            yield # FastAPI lifespan yields nothing, or a simple object if needed for FastAPI's state
    finally:
        await mcp_lifespan_ctx.__aexit__(None, None, None)
    """
    mcp_lifespan_ctx = mcp_vanna_lifespan(mcp_server)
    mcp_context = await mcp_lifespan_ctx.__aenter__()  # yields MCPLifeSpanContext
    try:
        thingy = mcp_context.th
        async with mcp_server.session_manager.run():
            app.mount("/mcp", mcp_http_app)
            app.mount("/sse", sse_app)
            app.state.app_state = AppState(th=thingy, mcp_server=mcp_server, vn=mcp_context.vn)
            yield
    finally:
        await mcp_lifespan_ctx.__aexit__(None, None, None)
    logging.info("🔌 FastAPI app shutting down...")

# Excel logging utility
LOG_FILE = "query_log.xlsx"
LOG_COLUMNS = [
    "question", "prompt", "llm_input_tokens", "llm_output_tokens", "llm_cost", "sql_gen_time", "sql_query", "fetch_time", "fetch_result", "fetch_error"
]

def append_log_to_excel(row_dict):
    if not os.path.exists(LOG_FILE):
        df = pd.DataFrame([row_dict], columns=LOG_COLUMNS)
        df.to_excel(LOG_FILE, index=False)
    else:
        wb = load_workbook(LOG_FILE)
        ws = wb.active
        ws.append([row_dict.get(col, "") for col in LOG_COLUMNS])
        wb.save(LOG_FILE)

def calculate_cost(input_tokens, output_tokens):
    if input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * 0.0000015 + output_tokens * 0.000006) * 0.000001

# Tool implementations with decorators
@mcp_server.tool(
    name="ask_sql",
    title="Ask a question, get a SQL query",
    description="Takes a plain English question and returns a SQL query from {}.".format(os.getenv("DB_DESCRIPTION", "financial database")),
)
async def ask_sql(question: str, ctx: Context[Any, MCPLifeSpanContext, Any]) -> str:
    vn_instance = ctx.request_context.lifespan_context.vn
    logging.info(f"Received question for SQL generation: '{question}'")
    log_row = {"question": question}

    def generate_sql_with_full_context(vn: MyVanna, q: str):
        question_sql_list = vn.get_similar_question_sql(q)
        prompt = vn.get_sql_prompt(
            initial_prompt=vn.config.get("initial_prompt", None) if hasattr(vn, "config") else None,
            question=q,
            question_sql_list=question_sql_list,
            ddl_list=vn.get_related_ddl(q),
            doc_list=vn.get_related_documentation(q)
        )
        logging.info(f"Prompt: {prompt}")
        llm_start = time.time()
        sql, input_tokens, output_tokens = vn.submit_prompt(prompt)
        llm_cost = calculate_cost(input_tokens, output_tokens)
        llm_time = time.time() - llm_start
        return sql, prompt, input_tokens, output_tokens, llm_cost, llm_time

    sql_query, prompt, input_tokens, output_tokens, llm_cost, llm_time = await anyio.to_thread.run_sync(
        generate_sql_with_full_context, vn_instance, question
    )
    logging.info(f"Generated SQL: {sql_query}")
    prompt_str = "\n".join([f"({msg.type}) {msg.content}" for msg in prompt])
    log_row.update({
        "prompt": prompt_str,
        "llm_input_tokens": input_tokens,
        "llm_output_tokens": output_tokens,
        "llm_cost": llm_cost,
        "sql_gen_time": llm_time,
        "sql_query": sql_query
    })
    append_log_to_excel(log_row)
    return sql_query or "Could not generate a valid SQL query."

@mcp_server.tool(
    name="run_sql",
    title="Run a SQL query",
    description="Takes a SQL query against {} and returns the result as a JSON string.".format(os.getenv("DB_DESCRIPTION", "financial database")),
)
async def run_sql(sql_query: str, ctx: Context[Any, MCPLifeSpanContext, Any]) -> str:
    vn_instance = ctx.request_context.lifespan_context.vn
    logging.info(f"Executing SQL query: {sql_query}")
    fetch_start = time.time()
    fetch_error = None
    try:
        df = await anyio.to_thread.run_sync(vn_instance.run_sql, sql_query)
        if df is not None:
            fetch_result = df.to_json(orient='records')
        else:
            fetch_result = "Query executed, but no results were returned."
    except Exception as e:
        fetch_result = "Error executing SQL query."
        fetch_error = "; ".join(e.args)
     
    fetch_time = time.time() - fetch_start
    try:
        if os.path.exists(LOG_FILE):
            wb = load_workbook(LOG_FILE)
            ws = wb.active
            last_row = ws.max_row
            ws.cell(row=last_row, column=LOG_COLUMNS.index("fetch_time")+1, value=fetch_time)
            ws.cell(row=last_row, column=LOG_COLUMNS.index("fetch_result")+1, value=fetch_result)
            ws.cell(row=last_row, column=LOG_COLUMNS.index("fetch_error")+1, value=fetch_error)
            wb.save(LOG_FILE)
    except Exception as e:
        logging.error(f"Error updating fetch log in Excel: {e}")
    return fetch_result

@mcp_server.tool(
    name="ask_and_run",
    title="Ask a question and run the SQL",
    description="Takes a plain English question, generates a SQL query, runs it against {}, and returns the result as a JSON string.".format(os.getenv("DB_DESCRIPTION", "financial database"))
)
async def ask_and_run(question: str, ctx: Context[Any, MCPLifeSpanContext, Any]) -> str:
    vn_instance = ctx.request_context.lifespan_context.vn
    sql_query = await ask_sql(question, ctx)
    if sql_query.startswith("Could not generate"):
        return sql_query
    result = await run_sql(sql_query, ctx)
    return result

@mcp_server.tool(
    name="add_training",
    title="Add training data",
    description="Adds new training data to the vector store.",
)
async def add_training(
    collection: Annotated[str, Field(description="Collection to add training data to", examples=["documentation", "ddl", "sql"])], 
    content: Annotated[str, Field(description="Content to add to the training data")], 
    question: Annotated[str | None, Field(default=None, description="Optional question for SQL training. Required if collection is 'sql'.")],
    ctx: Context[Any, MCPLifeSpanContext, Any]
) -> str:
    vn_instance: MyVanna = ctx.request_context.lifespan_context.vn
    if collection == "documentation":
        await anyio.to_thread.run_sync(vn_instance.add_documentation, content)
        return "Documentation added successfully."
    elif collection == "ddl":
        await anyio.to_thread.run_sync(vn_instance.add_ddl, content)
        return "DDL added successfully."
    elif collection == "sql":
        if question is None:
            return "Error: 'question' parameter is required when adding SQL."
        await anyio.to_thread.run_sync(vn_instance.add_question_sql, question, content)
        return "Question-SQL pair added successfully."
    else:
        return f"Error: Unknown collection type '{collection}'."

@mcp_server.tool(
    name="run_train_plan",
    title="Run the training plan",
    description="Executes the Vanna AI training plan.",
)
async def run_train_plan(ctx: Context[Any, MCPLifeSpanContext, Any]) -> str:
    vn_instance: MyVanna = ctx.request_context.lifespan_context.vn
    await anyio.to_thread.run_sync(vn_instance.run_training_plan)
    return "Training plan executed successfully."

@mcp_server.tool(
    name="get_training",
    title="Get training data",
    description="Retrieves and displays all training data from the vector store.",
)
async def get_training(ctx: Context[Any, MCPLifeSpanContext, Any]) -> str:
    vn_instance: MyVanna = ctx.request_context.lifespan_context.vn
    data_frame: pd.DataFrame = await anyio.to_thread.run_sync(vn_instance.get_training_data)
    summary = data_frame.to_markdown()
    return summary

@mcp_server.tool(
    name="clear_training",
    title="Clear training data",
    description="Removes all training data from the vector store.",
)
async def clear_training(ctx: Context[Any, MCPLifeSpanContext, Any], collection: Literal['documentation', 'ddl', 'sql', 'all'] = 'all') -> str:
    vn_instance: MyVanna = ctx.request_context.lifespan_context.vn
    await anyio.to_thread.run_sync(vn_instance.clear_training_data, collection)
    return "All training data cleared successfully."

@mcp_server.tool(
    name="health_check",
    title="Health Check",
    description="Checks the status of the database and vector store connections.",
)
async def health_check(ctx: Context[Any, MCPLifeSpanContext, Any]) -> str:
    vn_instance: MyVanna = ctx.request_context.lifespan_context.vn
    status_report = f""
    try:
        df = await anyio.to_thread.run_sync(vn_instance.run_sql, "SELECT 1")
        if df is not None:
            status_report += "\nDatabase query executed successfully."
        else:
            status_report += "\nDatabase query did not return results."
    except Exception as e:
        status_report += f"\nDatabase query failed: {e}"
    return status_report

@mcp_server.tool(
    name="get_latest_logs",
    title="Get latest logs",
    description="Retrieves the latest n log entries from the query log file.",
)
async def get_latest_logs(n: int, ctx: Context) -> str:
    if not os.path.exists(LOG_FILE):
        return "Log file does not exist."
    df = pd.read_excel(LOG_FILE)
    latest_logs = df.tail(n)
    return latest_logs.to_json(orient='records')


# Create the main FastAPI app with the dynamic lifespan manager
app = FastAPI(
    title="Vanna AI MCP Server",
    description="A server that uses Vanna AI to answer questions and serves multiple MCP endpoints.",
    version="1.0.0",
    lifespan=app_lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/greet")
async def greet(request: Request):
    app_state: AppState = request.app.state.app_state
    greeting = app_state.th.greet()
    return {"greeting": greeting}

@app.get("/api/dbhealth")
async def dbhealth(request: Request):
    app_state: AppState = request.app.state.app_state
    vn_instance = app_state.vn
    try:
        df = await anyio.to_thread.run_sync(vn_instance.run_sql, "SELECT 1")
        if df is not None:
            return {"database_status": "ok"}
        else:
            return {"database_status": "query returned no results"}
    except Exception as e:
        return {"database_status": f"error: {e}"}

@app.post("/api/initialise_training")
async def initialise_training_api(request: Request):
    app_state: AppState = request.app.state.app_state
    vn_instance = app_state.vn
    try:
        await anyio.to_thread.run_sync(vn_instance.run_training_plan)
        return {"status": "Training initialized successfully."}
    except Exception as e:
        return {"status": f"Error initializing training: {e}"}
    
@app.put("/api/add_training/{collection}")
async def add_training_api(collection: str, request: Request):
    app_state: AppState = request.app.state.app_state
    vn_instance = app_state.vn
    data = await request.json()
    content = data.get("content")
    question = data.get("question", None)
    
    if not content:
        raise HTTPException(status_code=400, detail="Content is required.")
    
    try:
        if collection == "documentation":
            await anyio.to_thread.run_sync(vn_instance.add_documentation, content)
            return "Documentation added successfully."
        elif collection == "ddl":
            await anyio.to_thread.run_sync(vn_instance.add_ddl, content)
            return "DDL added successfully."
        elif collection == "sql":
            if question is None:
                return "Error: 'question' parameter is required when adding SQL."
            await anyio.to_thread.run_sync(vn_instance.add_question_sql, question, content)
            return "Question-SQL pair added successfully."
        else:
            return f"Error: Unknown collection type '{collection}'."
    except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/get_training")
async def get_training_api(request: Request):
    app_state: AppState = request.app.state.app_state
    vn_instance = app_state.vn
    try:
        data_frame: pd.DataFrame = await anyio.to_thread.run_sync(vn_instance.get_training_data)
        summary = data_frame.to_markdown()
        return {"training_data": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.delete("/api/clear_training/{collection}")
async def clear_training_api(collection: str, request: Request):
    app_state: AppState = request.app.state.app_state
    vn_instance = app_state.vn
    try:
        await anyio.to_thread.run_sync(vn_instance.clear_training_data, collection)
        return {"status": "All training data cleared successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
if __name__ == '__main__':
    import uvicorn
    logging.info("Starting Vanna AI MCP Server with multi-protocol support...")
    uvicorn.run(app, host="127.0.0.1", port=8000)

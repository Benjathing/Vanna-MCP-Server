import struct
from dotenv import load_dotenv
load_dotenv()

import os
import json
from typing import Literal, Any, Dict, List, Callable, Coroutine
from fastapi import FastAPI, Request, HTTPException
from fastapi.routing import APIRouter
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
import inspect

#import weaviate
from vanna.chromadb import ChromaDB_VectorStore
import pandas as pd
#from vanna.weaviate.weaviate_vector import WeaviateDatabase
from vanna.base import VannaBase
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import time
from openpyxl import load_workbook
from sqlalchemy import event

from azure.identity import DefaultAzureCredential
SQL_COPT_SS_ACCESS_TOKEN = 1256  # This connection option is defined by microsoft in msodbcsql.h
TOKEN_URL = "https://database.windows.net/.default"  # The token URL for any Azure SQL database

# Import MCP and anyio components
from mcp.server.fastmcp import FastMCP, Context
import anyio

# Import and configure the logging module
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import signal
import sys

class DependencyError(Exception):
    """Raise for missing dependencies."""

    pass

def shutdown_handler(signum, frame):
    logging.info("Received shutdown signal. Cleaning up MCP server...")
    try:
        sys.exit(0)
    except Exception as e:
        logging.error(f"Error during shutdown: {e}")
        sys.exit(1)

# Register signal handlers
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# Load environment variables from .env file
load_dotenv()

class LangChainAzureChat(VannaBase):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.llm = AzureChatOpenAI(
            azure_deployment="gpt-4.1",
            api_version="2024-02-15-preview",
            temperature=0.0,
            max_tokens=1000,
            api_key=os.getenv("OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        )

    def system_message(self, message: str) -> SystemMessage:
        return SystemMessage(content=message)

    def user_message(self, message: str) -> HumanMessage:
        return HumanMessage(content=message)

    def assistant_message(self, message: str) -> AIMessage:
        return AIMessage(content=message)

    def submit_prompt(self, prompt, **kwargs) -> str:
        response = self.llm.invoke(prompt)
        logging.info(f"Response: {response}")
        input_tokens = response.usage_metadata.get('input_tokens')
        output_tokens = response.usage_metadata.get('output_tokens')
        return response.content, input_tokens, output_tokens

class MyVanna(ChromaDB_VectorStore, LangChainAzureChat):
    azure_credentials: DefaultAzureCredential|None = None
    
    def __init__(self, config=None):
        self.config = config or {}
        ChromaDB_VectorStore.__init__(self, config=config)
        LangChainAzureChat.__init__(self, config=config)
        
    def run_training_plan(self):
        VannaTraining_Information_schema = "SELECT * FROM INFORMATION_SCHEMA.COLUMNS"
        try:
            df_information_schema = self.run_sql(VannaTraining_Information_schema)
            plan = self.get_training_plan_generic(df_information_schema)
            self.train(plan=plan)
        except Exception as e:
            logging.error(f"Error running training plan: {e}", exc_info=True)
            raise
        
    def clear_training_data(self, collection: Literal["documentation", "ddl", "sql", "all"] = "all"):
        if collection == "all":
            doc = self.remove_collection('documentation')
            ddl = self.remove_collection('ddl')
            sql = self.remove_collection('sql')
            return doc and ddl and sql
        else:
            return self.remove_collection(collection)
    
    def connect_to_mssql(self, odbc_conn_str, **kwargs):
        """
        Connect to a Microsoft SQL Server database. This is just a helper function to set [`vn.run_sql`][vanna.base.base.VannaBase.run_sql]
        (From Vanna)
        
        Args:
            odbc_conn_str (str): The ODBC connection string.

        Returns:
            None
        """
        try:
            import pyodbc
        except ImportError:
            raise DependencyError(
                "You need to install required dependencies to execute this method,"
                " run command: pip install pyodbc"
            )

        try:
            import sqlalchemy as sa
            from sqlalchemy.engine import URL
        except ImportError:
            raise DependencyError(
                "You need to install required dependencies to execute this method,"
                " run command: pip install sqlalchemy"
            )
        if "uid" not in odbc_conn_str and "pwd" not in odbc_conn_str:
            self.azure_credentials = DefaultAzureCredential(exclude_environment_credential=True, exclude_shared_token_cache_credential=True)

        connection_url = URL.create(
            "mssql+pyodbc", query={"odbc_connect": odbc_conn_str}
        )
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        
        engine = create_engine(connection_url, **kwargs)
        
        @event.listens_for(engine, "do_connect")
        def provide_token(dialect, conn_rec, cargs, cparams):
            if not self.azure_credentials:
                return
            """
                Called before the engine creates a new connection. Injects an EntraID token into the connection parameters.
            """
            logging.info('creating new token')
            cargs[0] = cargs[0].replace(";Trusted_Connection=Yes", "")

            token_bytes = self.azure_credentials.get_token(TOKEN_URL).token.encode("UTF-16-LE")
            token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
            
            cparams["attrs_before"] = {SQL_COPT_SS_ACCESS_TOKEN: token_struct}
        
        def run_sql_mssql(sql: str):
            # Execute the SQL statement and return the result as a pandas DataFrame
            with engine.begin() as conn:
                df = pd.read_sql_query(sa.text(sql), conn)
                conn.close()
                return df

            raise Exception("Couldn't run sql")
        
        class _session():
            def __init__(self) -> None:
                self.session = Session(engine)
                self.session.expire_on_commit = False
            def __enter__(self):
                return self.session
            
            def __exit__(self, *args):
                self.session.close()
        self.dialect = "T-SQL / Microsoft SQL Server"
        self.run_sql = run_sql_mssql
        self.session = _session
        self.connect = engine.connect
        self.run_sql_is_set = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.info("\nConnection closed successfully.")

# --- MCP Server Integration ---

@dataclass
class AppState:
    vn: MyVanna
    mcp_server: FastMCP

@dataclass
class MCPLifeSpanContext:
    vn: MyVanna

# Create the router that will hold the dynamic MCPO endpoints
mcpo_router = APIRouter()
# Create the FastMCP instance
mcp_instructions = "A server that uses Vanna AI to answer questions about a {}".format(os.getenv("DB_DESCRIPTION", "financial database"))
# Define the lifespan for the MCP server itself
@asynccontextmanager
async def mcp_vanna_lifespan(mcp_instance: FastMCP) -> AsyncIterator[MCPLifeSpanContext]:
    logging.info("🚀 Vanna AI instance starting up (MCP internal lifespan)...")
    config = {
        "qdrant_url": os.getenv("QDRANT_URL"),
        "qdrant_api_key": os.getenv("QDRANT_API_KEY"),
    }
    
    odbc_conn_str = os.getenv("ODBC_CONN_STR")
    
    vn = MyVanna(config=config)
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
    yield MCPLifeSpanContext(vn=vn) # This 'vn' will be available as lifespan_context in MCP tools
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

    async with mcp_server.session_manager.run():
        app.mount("/mcp", mcp_http_app)
        app.mount("/sse", sse_app)

        # The AppState is now just for FastAPI's state, not for MCP's lifespan context
        app.state.app_state = AppState(vn=None, mcp_server=mcp_server) # vn is not directly in app.state.app_state anymore

        yield # FastAPI lifespan yields nothing, or a simple object if needed for FastAPI's state
    
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
    name="add_training",
    title="Add training data",
    description="Adds new training data to the vector store.",
)
async def add_training(collection: str, content: str, question: str | None, ctx: Context[Any, MCPLifeSpanContext, Any]) -> str:
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

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == '__main__':
    import uvicorn
    logging.info("Starting Vanna AI MCP Server with multi-protocol support...")
    uvicorn.run(app, host="127.0.0.1", port=8000)

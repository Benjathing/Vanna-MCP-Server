import os
import struct
import httpx
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from vanna.base import VannaBase
from vanna.qdrant import Qdrant_VectorStore
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
import logging

load_dotenv()

SQL_COPT_SS_ACCESS_TOKEN = 1256
TOKEN_URL = "https://database.windows.net/.default"

class DependencyError(Exception):
    """Raise for missing dependencies."""
    pass

class LangChainAzureChat(VannaBase):
    def __init__(self, config=None):
        super().__init__(config=config)
        # Create a custom httpx client with a longer timeout
        custom_client = httpx.Client(timeout=120.0)
        custom_async_client = httpx.AsyncClient(timeout=120.0)

        self.llm = AzureChatOpenAI(
            azure_deployment="gpt-4.1",
            api_version="2024-02-15-preview",
            temperature=0.0,
            max_tokens=1000,
            api_key=os.getenv("OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            http_client=custom_client, # Pass the custom client
            http_async_client=custom_async_client # Pass the custom async client
        )

    def system_message(self, message: str) -> SystemMessage:
        return SystemMessage(content=message)

    def user_message(self, message: str) -> HumanMessage:
        return HumanMessage(content=message)

    def assistant_message(self, message: str) -> AIMessage:
        return AIMessage(content=message)

    def submit_prompt(self, prompt, **kwargs) -> str:
        response = self.llm.invoke(prompt)
        logging.info(f"Response content: {response.content}")
        input_tokens = response.usage_metadata.get('input_tokens')
        output_tokens = response.usage_metadata.get('output_tokens')
        return response.content, input_tokens, output_tokens

class MyVanna(Qdrant_VectorStore, LangChainAzureChat):
    azure_credentials: DefaultAzureCredential|None = None
    
    def __init__(self, config=None):
        Qdrant_VectorStore.__init__(self, config=config)
        LangChainAzureChat.__init__(self, config=config)
        self._setup_collections()

    def _setup_collections(self):
        if not os.path.exists("/tmp/vanna_mcp_server.lock"):
            super()._setup_collections()
            with open("/tmp/vanna_mcp_server.lock", "w") as f:
                f.write("locked")

    def run_training_plan(self):
        VannaTraining_Information_schema = "SELECT * FROM INFORMATION_SCHEMA.COLUMNS"
        try:
            df_information_schema = self.run_sql(VannaTraining_Information_schema)
            plan = self.get_training_plan_generic(df_information_schema)
            self.train(plan=plan)
        except Exception as e:
            logging.error(f"Error running training plan: {e}", exc_info=True)
            raise
        
    def clear_training_data(self, collection: str = "all"):
        if collection == "all":
            doc = self.remove_collection('documentation')
            ddl = self.remove_collection('ddl')
            sql = self.remove_collection('sql')
            return doc and ddl and sql
        else:
            return self.remove_collection(collection)
    
    def connect_to_mssql(self, odbc_conn_str, **kwargs):
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
            self.azure_credentials = DefaultAzureCredential(exclude_shared_token_cache_credential=True)

        connection_url = URL.create(
            "mssql+pyodbc", query={"odbc_connect": odbc_conn_str}
        )
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import Session
        
        engine = create_engine(connection_url, **kwargs)
        
        @event.listens_for(engine, "do_connect")
        def provide_token(dialect, conn_rec, cargs, cparams):
            if not self.azure_credentials:
                return
            logging.info('creating new token')
            cargs[0] = cargs[0].replace(";Trusted_Connection=Yes", "")

            token_bytes = self.azure_credentials.get_token(TOKEN_URL).token.encode("UTF-16-LE")
            token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
            
            cparams["attrs_before"] = {SQL_COPT_SS_ACCESS_TOKEN: token_struct}
        
        def run_sql_mssql(sql: str):
            import pandas as pd
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

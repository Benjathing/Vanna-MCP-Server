# Vanna AI MCP Server

This project implements a Model Context Protocol (MCP) server using Vanna AI for natural language to SQL translation and SQL execution over a configurable database. It features:

- **Natural language to SQL generation** using Vanna AI and Azure OpenAI
- **SQL execution** against a Microsoft SQL Server database
- **Dynamic training** of the model via MCP tools
- **Excel logging** of all queries, prompts, LLM token usage, cost, timing, and results
- **Hot reload workflow** for rapid development
- **Graceful shutdown** and robust error handling

## Features

- **ask_sql**: Converts a natural language question to a SQL query using the LLM, logs all details to `query_log.xlsx`.
- **run_sql**: Executes a SQL query and logs execution time and results to Excel.
- **LLM token/cost tracking**: Logs input/output tokens and estimated cost for each LLM call.
- **Dynamic Training**: Use MCP tools like `add_training` and `run_train_plan` to train the model on your database schema, documentation, and sample questions.
- **Signal handling**: Clean shutdown on Ctrl+C or kill.
- **Hot reload**: Easily restart both server and Inspector for rapid iteration.

## Setup

### 1. Clone the repository
```sh
git clone <your-repo-url>
cd <your-repo-directory>
```

### 2. Install Python dependencies
```sh
pip install -r requirements.txt
```

### 3. Install Node.js Inspector (optional, for UI)
```sh
npm install -g @modelcontextprotocol/inspector
```

### 4. Set up environment variables
Create a `.env` file with your credentials:
```
OPENAI_API_KEY=your-openai-key
AZURE_OPENAI_ENDPOINT=your-azure-endpoint
ODBC_CONN_STR="your-mssql-connection-string"
DB_DESCRIPTION="a description of your database"
QDRANT_URL="your-qdrant-url"
QDRANT_API_KEY="your-qdrant-api-key"
```

## Usage

### 1. Start the MCP Server

To run the server, you first need to ensure the `app.py` file is ready for `uvicorn`. The following line should be present at the end of the file, before the `if __name__ == '__main__':` block:

```python
asgi_app = mcp.streamable_http_app()
```

Once the file is set up, run the following command from your project directory to start the server in the background:

```sh
start /b C:\docker\VannaMCP\vanna-mcp-server\.venv\Scripts\python.exe -m uvicorn app:asgi_app --host 127.0.0.1 --port 8000
```

### 2. Start the MCP Inspector (UI)

To connect to the running server, open a **new terminal** in a **different directory** (one that does not contain a `.env` file) and run:

```sh
mcp-inspector
```

### 3. Connect the Inspector

In the `mcp-inspector` UI that opens in your browser:

1.  Set **Transport Type** to `streamable-http`.
2.  Set the **URL** to `http://127.0.0.1:8000/mcp`.
3.  Click **Connect**.

## Training

The Vanna AI model is trained dynamically through the MCP server itself. You can use the MCP Inspector UI or a client to call the following tools:

- **`add_training`**: Add DDL statements, documentation, or question-SQL pairs to the training data.
- **`run_train_plan`**: Run the training plan to populate the vector store.
- **`get_training`**: Retrieve a summary of the current training data.
- **`clear_training`**: Clear all training data.

## Logging
- All queries, prompts, LLM token usage, cost, timing, and results are logged to `query_log.xlsx`.
- Each new query appends a row; SQL execution updates the last row with fetch time and result.

## Graceful Shutdown
- The server handles SIGINT/SIGTERM for clean shutdown and port release.

## Customization
- Adjust LLM cost calculation in `calculate_cost()` as needed.
- Use the `DB_DESCRIPTION` environment variable to customize the description of your database.

## Troubleshooting
- If you see "Not connected" errors in the Inspector, restart both the server and Inspector.
- Ensure all environment variables are set.

## License
MIT

## Dockerization with Azure Managed Identity

For a more secure and portable deployment, you can containerize this application using Docker and authenticate to Azure SQL using a Managed Identity. This method avoids storing database credentials in environment variables.

### 1. The Dockerfile
A `Dockerfile` is included in this repository. It is configured to:
- Use a standard Python 3.11 base image.
- Install all necessary system dependencies, including the Microsoft ODBC Driver 18 for SQL Server, which is required for Azure AD authentication methods.
- Install all Python packages from `requirements.txt`.
- Expose port 8000 and run the application with `uvicorn`.

### 2. Azure Managed Identity Connection String
When deploying to an Azure service (like an App Service or Container Instance), you must update the `ODBC_CONN_STR` environment variable to use Managed Identity. The driver uses the identity of the hosting service to authenticate.

For a **System-Assigned Managed Identity**, the format is:
```
ODBC_CONN_STR="Driver={ODBC Driver 18 for SQL Server};Server=tcp:your_server_name.database.windows.net,1433;Database=your_database;Authentication=ActiveDirectoryMsi;Encrypt=yes;TrustServerCertificate=no;"
```
Replace `your_server_name` and `your_database` with your specific details.

### 3. Azure Configuration
Before deploying, you must configure your Azure resources:

1.  **Enable Managed Identity**: In the Azure portal, navigate to your hosting resource (e.g., App Service). Under **Settings**, select **Identity** and enable the **System-assigned** identity.

2.  **Grant Database Permissions**: Connect to your Azure SQL database with an admin account and run the following SQL to create a database user for your service's identity and grant it permissions.

    ```sql
    -- Replace 'Your-Azure-Service-Name' with the name of your App Service, ACI, or VM
    CREATE USER [Your-Azure-Service-Name] FROM EXTERNAL PROVIDER;

    -- Grant the necessary permissions
    ALTER ROLE db_datareader ADD MEMBER [Your-Azure-Service-Name];
    ALTER ROLE db_datawriter ADD MEMBER [Your-Azure-Service-Name];
    ```

### 4. Build and Deploy the Image

1.  **Build the Docker image:**
    ```sh
    docker build -t vanna-mcp-server .
    ```

2.  **Push to a container registry** (e.g., Azure Container Registry):
    ```sh
    docker tag vanna-mcp-server yourregistry.azurecr.io/vanna-mcp-server:latest
    docker push yourregistry.azurecr.io/vanna-mcp-server:latest
    ```

3.  **Deploy** the container image to your configured Azure service, ensuring the `ODBC_CONN_STR` environment variable is set to the Managed Identity format.

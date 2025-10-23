# Docker Deployment

This directory contains the necessary files for deploying the Vanna MCP Server using Docker Compose.

## Getting Started

### 1. Environment Variables (`.env`)

Before running Docker Compose, you need to create a `.env` file in this directory (`./docker/.env`). This file will store sensitive environment variables and configuration specific to your deployment.

**DO NOT commit `docker/.env` to Git.** It should be excluded by your `.gitignore` file (which is already configured in the project root).

Here's an example of the `.env` file content. You should replace the placeholder values with your actual configuration:

```
DOCKER_REPOSITORY=crbdllmprodase01.azurecr.io
VANNA_IMAGE=vanna-mcp-server:latest
QDRANT_PORT=6333
MCP_SERVER_PORT=8000
MCPO_SERVER_PORT=8001
WEB_SERVER_PORT=8002
AZURE_OPENAI_ENDPOINT=https://your-azure-openai-endpoint/
AZURE_OPENAI_API_KEY=your-azure-openai-api-key
ODBC_DRIVER={ODBC Driver 18 for SQL Server}
DB_SERVER=your-database-server.database.windows.net
DB_NAME=your-database-name

# For local testing with Azure AD Service Principal (if not using Managed Identity)
# AZURE_TENANT_ID=<your-service-principal-tenant-id>
# AZURE_CLIENT_ID=<your-service-principal-client-id>
# AZURE_CLIENT_SECRET=<your-service-principal-client-secret>

# Optional: Database credentials if not using Managed Identity or Service Principal
# DB_USERNAME=your-db-username
# DB_PASSWORD=your-db-password

QDRANT_VOLUME=qdrant_data
```

**Explanation of variables:**

*   `DOCKER_REPOSITORY`: The Docker repository where your Vanna MCP Server image is hosted.
*   `VANNA_IMAGE`: The name and tag of your Vanna MCP Server Docker image.
*   `QDRANT_PORT`: The port on which the Qdrant vector database will run.
*   `MCP_SERVER_PORT`: The internal port for the main Vanna MCP application.
*   `MCPO_SERVER_PORT`: The internal port for the MCPO server.
*   `WEB_SERVER_PORT`: The internal port for the Vanna web app.
*   `AZURE_OPENAI_ENDPOINT`: Your Azure OpenAI service endpoint.
*   `AZURE_OPENAI_API_KEY`: Your Azure OpenAI API key. This will be used as `OPENAI_API_KEY` inside the container.
*   `ODBC_DRIVER`: The ODBC driver string for your database connection.
*   `DB_SERVER`: The hostname of your database server.
*   `DB_NAME`: The name of your database.
*   `AZURE_TENANT_ID` (Optional, for local SP testing): The tenant ID of your Azure AD Service Principal.
*   `AZURE_CLIENT_ID` (Optional, for local SP testing): The client ID of your Azure AD Service Principal.
*   `AZURE_CLIENT_SECRET` (Optional, for local SP testing): The client secret of your Azure AD Service Principal.
*   `DB_USERNAME` (Optional): Database username if not using Managed Identity or Service Principal.
*   `DB_PASSWORD` (Optional): Database password if not using Managed Identity or Service Principal.
*   `QDRANT_VOLUME`: The name of the Docker volume used to persist Qdrant data.

### 2. Running the Services

Once your `.env` file is configured, you can start the services using Docker Compose from this directory:

```bash
docker-compose up --build -d
```

*   `up`: Starts the services defined in `docker-compose.yml`.
*   `--build`: Rebuilds the `vanna-mcp-server` image (useful if you've made changes to the application code or `Dockerfile`).
*   `-d`: Runs the services in detached mode (in the background).

### 3. Accessing the Application

The Vanna MCP Server and Web App will be accessible through the proxy on port `3000` of your host machine.

*   **Main Application:** `http://localhost:3000/` (proxies to internal port 8000)
*   **MCPO Server:** `http://localhost:3000/mcpo` (proxies to internal port 8001)
*   **Vanna Web App:** `http://localhost:3000/web` (proxies to internal port 8002)

### 4. Stopping the Services

To stop and remove the running containers, networks, and volumes (if not explicitly defined as external):

```bash
docker-compose down
```

To stop the services without removing them:

```bash
docker-compose stop
```

### 5. Building and Publishing Docker Images

This directory contains a PowerShell script (`build_and_publish.ps1`) that can be used to build and publish the main application's Docker image to your Azure Container Registry (ACR).

**Important Considerations:**

*   **Execution Environment:** This script is designed to be run *inside* a Docker container that has PowerShell Core, Azure CLI, and Docker CLI installed. Your `Dockerfile` for the `vanna-mcp-server` image would need to be modified to include these tools.
*   **Authentication:** The script uses `az acr login` to authenticate with your ACR. This requires Azure CLI to be configured for authentication (e.g., via `az login` on the host, or a Service Principal in a CI/CD pipeline).
*   **Dockerfile Location:** The script assumes the main `Dockerfile` is located in the parent directory (`../Dockerfile`) relative to where `build_and_publish.ps1` is executed.
*   **`.env` Updates:** The script *cannot* automatically update the `docker/.env` file on your host machine. You will need to manually update the `VANNA_IMAGE` variable in your `docker/.env` file with the new tag after a successful publish.

**Usage:**

To run the script from within the container (assuming the container has the necessary tools and permissions):

```powershell
./build_and_publish.ps1 -Increment <major|minor|build> [-Alpha]
```

**Parameters:**

*   `-Increment <major|minor|build>`: Specifies which part of the version number to increment. Defaults to `build`.
*   `-Alpha`: (Optional) If present, the `-alpha` suffix will be added to the new image tag.

**Example:**

To increment the minor version and add the `-alpha` suffix:

```powershell
./build_and_publish.ps1 -Increment minor -Alpha
```

To increment the build version:

```powershell
./build_and_publish.ps1 -Increment build
```
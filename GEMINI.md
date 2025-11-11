# Project: Multi-Container Vanna App Deployment

This document summarizes the work done to create a robust deployment solution for the Vanna application on Azure.

## Objective

The primary goal was to consolidate several disparate deployment scripts (`docker-compose.yml`, PowerShell scripts, YAML files) into a single, parameterized Bicep template for deploying a multi-container Vanna application to Azure Container Apps.

## Key Activities & Outcomes

1.  **Initial Analysis:** The project was analyzed to understand its architecture. It consists of two main services deployed as containers:
    *   `vanna-mcp-server`: The main application container.
    *   `qdrant`: A vector database requiring persistent storage.

2.  **Bicep Refactoring:**
    *   The `main.bicep` file was heavily modified from a single-container template to a multi-container template capable of deploying both services into a single Azure Container App.
    *   Key configurations such as container images, secrets (OpenAI API key, ACR credentials, ODBC string), and resource allocations (CPU/RAM) were parameterized for flexibility.

3.  **Storage Integration:**
    *   To provide persistent storage for the `qdrant` container, the logic from `storage-share.bicep` was integrated directly into `main.bicep`.
    *   This involved creating a `Microsoft.App/managedEnvironments/storages` resource to formally attach an Azure File Share to the Container App Environment.
    *   The `azuredeploy.parameters.json` file was updated to include new parameters for the storage account name, share name, and access key.

4.  **Parameter & Linter Corrections:**
    *   The `storageShareName` parameter was explicitly set to `vanna-qdrant-mcp03` to align with previous deployment configurations.
    *   A Bicep linter issue with non-integer CPU allocations (e.g., `0.5`) was resolved by changing the parameter types to `int` and updating the default values to `1` in both `main.bicep` and `azuredeploy.parameters.json`.

## Final Result

The result of this work is a comprehensive Infrastructure as Code (IaC) solution for the project:

*   **`main.bicep`**: A single, parameterized template that defines the entire Azure deployment, including the Container App Environment, the multi-container app, secrets, and the storage volume attachment.
*   **`azuredeploy.parameters.json`**: A corresponding parameters file for providing all necessary values for a deployment.

This solution enables repeatable, consistent deployments of the Vanna application to Azure.

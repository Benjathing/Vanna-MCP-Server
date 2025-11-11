// Bicep file to deploy the full application stack to Azure Container Apps.

// --- Secret Parameters ---
@description('Azure OpenAI API Key')
@secure()
param openAiApiKey string

@description('ODBC Connection String for the database')
@secure()
param odbcConnString string

@description('ACR username for pulling images')
@secure()
param acrUsername string

@description('ACR password for pulling images')
@secure()
param acrPassword string

@description('Primary account key for storage account')
@secure()
param primaryAccountKey string

// --- Configuration Parameters ---

@description('ACR server for pulling images')
param acrServer string

@description('Vanna container image name and tag')
param vannaContainerImage string

@description('Qdrant container image name and tag')
param qdrantContainerImage string = 'qdrant/qdrant:latest'

@description('Location for all resources')
param location string = resourceGroup().location

@description('Name of the Container App Environment')
param containerAppEnvironmentName string

@description('Name of the Vanna Container App')
param containerAppName string

@description('External ingress port for the Container App')
param containerAppHttpPort int = 3000

@description('CPU allocation for the Vanna container')
param vannaCpuProvisioning int = 1

@description('Memory allocation for the Vanna container')
param vannaRamProvisioning string = '2.0Gi'

@description('CPU allocation for the Qdrant container')
param qdrantCpuProvisioning int = 1

@description('Memory allocation for the Qdrant container')
param qdrantRamProvisioning string = '2.0Gi'

@description('The resource ID of the infrastructure subnet for the Container App Environment.')
param infrastructureSubnetId string

@description('Storage account name for Qdrant data')
param storageAccountName string

@description('Storage share name for Qdrant data')
param storageShareName string

@description('Environment storage name (the name of the volume mount)')
param environmentStorageName string = 'qdrant-data' // Default to qdrant-data as used in volumes

@description('Access mode for the file share')
@allowed([
  'ReadOnly'
  'ReadWrite'
])
param accessMode string = 'ReadWrite' // Qdrant needs ReadWrite access

@description('Azure OpenAI endpoint URL')
param azureOpenAiEndpoint string

@description('Port for the MCP server')
param mcpServerPort string = '8000'

@description('Port for the MCPO server')
param mcpoServerPort string = '8001'

@description('Description for the database')
param dbDescription string = 'Project descriptions, budgets, and start dates for different Clients'


// --- Resources ---

// A Container App Environment provides the virtual network and logging for a group of container apps.
resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvironmentName
  location: location
  properties: {
    workloadProfiles: [
      {
        workloadProfileType: 'Consumption'
      }
    ]
    vnetConfiguration: {
      infrastructureSubnetId: infrastructureSubnetId
      internal: true
    }
  }
}

// This resource attaches an existing Azure File Share to the Container App Environment
module storageModule 'storage-share.bicep' = {
  name: 'qdrant-storage'
  params: {
    storageAccountName: storageAccountName
    storageShareName: storageShareName
    environmentStorageName: environmentStorageName
    containerAppEnvironmentName: containerAppEnvironment.name
    primaryAccountKey: primaryAccountKey
    accessMode: accessMode
  }
}

// The main Container App resource, configured for a multi-container setup.
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  properties: {
    managedEnvironmentId: containerAppEnvironment.id
    configuration: {
      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
        }
        {
          name: 'openai-api-key'
          value: openAiApiKey
        }
      ]
      registries: [
        {
          server: acrServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]
      ingress: {
        external: true
        allowInsecure: false
        targetPort: containerAppHttpPort
        transport: 'http'
        clientCertificateMode: 'accept'
        corsPolicy: {
          allowedOrigins: [ '*' ]
          allowedHeaders: [
            'Authorization'
            'Content-Type'
          ]
          exposeHeaders: [ 'X-Custom-Header' ]
          maxAge: 3600
          allowCredentials: false
        }
      }
    }
    template: {
      containers: [
        {
          name: 'vanna-mcp-server'
          image: '${acrServer}/${vannaContainerImage}'
          resources: {
            cpu: vannaCpuProvisioning
            memory: vannaRamProvisioning
          }
          volumeMounts: [
            {
              mountPath: '/app/logs'
              volumeName: 'logs-volume'
            }
          ]
          env: [
            {
              name: 'OPENAI_API_KEY'
              secretRef: 'openai-api-key'
            }
            {
              name: 'ODBC_CONN_STRING'
              value: odbcConnString
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'QDRANT_URL'
              value: 'http://localhost:6333' // In a container app, sidecars are on localhost
            }
            {
              name: 'MCP_SERVER_PORT'
              value: mcpServerPort
            }
            {
              name: 'MCPO_SERVER_PORT'
              value: mcpoServerPort
            }
            {
              name: 'DB_DESCRIPTION'
              value: dbDescription
            }
            {
              name: 'ANONYMIZED_TELEMETERY'
              value: 'False'
            }
            {
              name: 'EXCEL_LOG_PATH'
              value: '/app/logs/excel_log.xlsx'
            }
          ]
        }
        {
          name: 'qdrant'
          image: qdrantContainerImage
          resources: {
            cpu: qdrantCpuProvisioning
            memory: qdrantRamProvisioning
          }
          volumeMounts: [
            {
              mountPath: '/qdrant/storage'
              volumeName: 'qdrant-data'
            }
          ]
          env: [
            {
              name: 'QDRANT__SERVICE__GRPC_PORT'
              value: '6334'
            }
            {
              name: 'QDRANT__SERVICE__HTTP_PORT'
              value: '6333'
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'logs-volume'
          storageType: 'EmptyDir'
        }
        {
          name: 'qdrant-data'
          storageType: 'AzureFile'
          storageName: storageModule.outputs.environmentStorageName
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

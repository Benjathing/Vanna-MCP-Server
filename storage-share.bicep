@description('Storage account name')
param storageAccountName string

@description('Storage share name')
param storageShareName string

@description('Environment storage name (the name of the volume mount)')
param environmentStorageName string

@description('Container app environment name')
param containerAppEnvironmentName string

@description('Primary account key for storage account')
@secure()
param primaryAccountKey string

@description('Access mode for the file share')
@allowed([
  'ReadOnly'
  'ReadWrite'
])
param accessMode string

// Reference to the existing Container App Environment
resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' existing = {
  name: containerAppEnvironmentName
}
 
// This resource attaches an existing Azure File Share to the Container App Environment
resource containerAppEnvironmentStorage 'Microsoft.App/managedEnvironments/storages@2023-05-01' = {
  name: environmentStorageName
  parent: containerAppEnvironment
  properties: {
    azureFile: {
      accountName: storageAccountName
      shareName: storageShareName
      accountKey: primaryAccountKey
      accessMode: accessMode
    }
  }
}

output environmentStorageName string = environmentStorageName
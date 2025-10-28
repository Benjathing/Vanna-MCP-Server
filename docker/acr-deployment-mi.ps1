<#
.SYNOPSIS
    Creates or updates an Azure Container App with a managed identity, grants it AcrPull permissions, and configures it to use an image from a private ACR.

.DESCRIPTION
    This script automates the deployment of an Azure Container App that uses an image from a private Azure Container Registry (ACR).
    It first creates the container app with a temporary public image to establish a managed identity.
    Then, it assigns the 'AcrPull' role to this managed identity for the specified ACR.
    Finally, it updates the container app to use the intended private image from the ACR.

.PARAMETER ContainerAppYamlPath
    The path to the containerapp.yaml file.

.PARAMETER ContainerAppName
    The name of the container app.

.PARAMETER ResourceGroupName
    The name of the resource group for the container app.

.PARAMETER EnvironmentName
    The name of the container app environment.

.PARAMETER AcrName
    The name of the Azure Container Registry.

.PARAMETER AcrResourceGroupName
    The name of the resource group for the ACR. Defaults to the value of ResourceGroupName if not provided.

.PARAMETER AcrSubscriptionId
    The subscription ID for the ACR. Defaults to the currently logged in subscription if not provided.
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$ContainerAppYamlPath,

    [Parameter(Mandatory=$true)]
    [string]$ContainerAppName,

    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$true)]
    [string]$EnvironmentName,

    [Parameter(Mandatory=$true)]
    [string]$AcrName,

    [string]$AcrResourceGroupName,

    [string]$AcrSubscriptionId
)

try {
    # Default AcrResourceGroupName to ResourceGroupName if not provided
    if (-not $AcrResourceGroupName) {
        $AcrResourceGroupName = $ResourceGroupName
    }

    # Guard clause to check for required permissions
    Write-Host "Checking for required permissions..."
    $userId = az ad signed-in-user show --query objectId -o tsv
    $roles = az role assignment list --assignee $userId --resource-group $AcrResourceGroupName --query "[].roleDefinitionName" -o tsv
    if (($roles -notcontains "Owner") -and ($roles -notcontains "User Access Administrator")) {
        throw "You do not have the required 'Owner' or 'User Access Administrator' role on the ACR resource group '$AcrResourceGroupName' to assign roles. Please get the required permissions and try again."
    }

    # 1. Create a temporary YAML file with a public image
    Write-Host "Creating a temporary YAML file with a public image..."
    $originalYaml = Get-Content -Path $ContainerAppYamlPath -Raw
    $tempYamlPath = [System.IO.Path]::GetTempFileName()
    ($originalYaml -replace '(image:.*)', 'image: mcr.microsoft.com/azuredocs/containerapps-helloworld:latest') | Set-Content -Path $tempYamlPath

    # 2. Create the Container App with the temporary YAML
    Write-Host "Creating container app '$ContainerAppName' with a temporary public image..."
    az containerapp create --name $ContainerAppName --resource-group $ResourceGroupName --environment $EnvironmentName --yaml $tempYamlPath | Out-Null

    # 3. Get the Managed Identity of the new container app
    Write-Host "Getting the managed identity of the container app..."
    $principalId = az containerapp show --name $ContainerAppName --resource-group $ResourceGroupName --query "identity.principalId" -o tsv

    if (-not $principalId) {
        throw "Failed to get the principal ID of the container app's managed identity."
    }

    # 4. Assign the AcrPull role to the Managed Identity
    Write-Host "Assigning 'AcrPull' role to the managed identity..."
    $acrIdCommand = "az acr show --name $AcrName --resource-group $AcrResourceGroupName --query id -o tsv"
    if ($AcrSubscriptionId) {
        $acrIdCommand += " --subscription $AcrSubscriptionId"
    }
    $acrId = Invoke-Expression -Command $acrIdCommand

    az role assignment create --assignee $principalId --role "AcrPull" --scope $acrId | Out-Null

    # 5. Update the Container App with the original YAML
    Write-Host "Updating the container app to use the private image..."
    az containerapp update --name $ContainerAppName --resource-group $ResourceGroupName --yaml $ContainerAppYamlPath | Out-Null

    Write-Host "Deployment successful!"

}
catch {
    Write-Error "An error occurred during deployment: $_"
}
finally {
    # 6. Clean up the temporary file
    if (Test-Path $tempYamlPath) {
        Write-Host "Cleaning up temporary files..."
        Remove-Item -Path $tempYamlPath
    }
}

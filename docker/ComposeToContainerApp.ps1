param (
    [string]$dockerComposeYamlPath = "docker-compose.yml",
    [string]$outputPath = "containerapp.yaml",
    [string]$subscriptionId,
    [string]$acrSubscriptionId,
    [Parameter(Mandatory = $true)]
    [string]$envResourceGroup,
    [Parameter(Mandatory = $true)]
    [string]$envName,
    [string]$location = "australiaeast",
    [Parameter(Mandatory = $true)]
    [string[]]$registries,
    [switch]$DryRun
)

if (-not $subscriptionId) {
    $subscriptionId = az account show --query id -o tsv   
}

if ($acrSubscriptionId) {
    az account set --subscription $acrSubscriptionId
}
$acrCreds = az acr credential show --name ($registries[0] -split "\.")[0] | ConvertFrom-Json
if ($acrSubscriptionId) {
    az account set --subscription $subscriptionId
}

$acrCreds

# Ensure powershell-yaml is installed
if (-not (Get-Module -ListAvailable -Name powershell-yaml)) {
    Install-Module powershell-yaml -Scope CurrentUser -Force
}
Import-Module powershell-yaml

# Run docker-compose config to resolve .env variables
$resolvedYamlLines = docker-compose -f $dockerComposeYamlPath config
$resolvedYaml = $resolvedYamlLines -join "`n"
Write-Output $resolvedYaml
$compose = ConvertFrom-Yaml -Yaml $resolvedYaml

# Build dependency graph
$dependsOnMap = @{}
$reverseDeps = @{}

foreach ($svcName in $compose.services.Keys) {
    $svc = $compose.services[$svcName]
    $dependsOnMap[$svcName] = @()
    if ($svc.depends_on) {
        foreach ($dep in $svc.depends_on.Keys) {
            $dependsOnMap[$svcName] += $dep
            if (-not $reverseDeps.ContainsKey($dep)) {
                $reverseDeps[$dep] = @()
            }
            $reverseDeps[$dep] += $svcName
        }
    }
}

# Detect circular dependencies
function Test-CircularDependency {
    param ([hashtable]$dependsOnMap)

    $visited = @{}
    $stack = @{}

    function Visit($node) {
        if ($stack[$node]) {
            throw "❌ Circular dependency detected at '$node'"
        }
        if ($visited[$node]) {
            return
        }

        $visited[$node] = $true
        $stack[$node] = $true

        foreach ($dep in $dependsOnMap[$node]) {
            Visit $dep
        }

        $stack.Remove($node)
    }

    foreach ($svc in $dependsOnMap.Keys) {
        Visit $svc
    }
}
Test-CircularDependency -dependsOnMap $dependsOnMap

# Find leaf node (not depended on by any other)
$leafCandidates = $compose.services.Keys | Where-Object { -not $reverseDeps.ContainsKey($_) }
$mainContainerName = $leafCandidates | Sort-Object { $dependsOnMap[$_].Count } -Descending | Select-Object -First 1
$mainContainer = $compose.services[$mainContainerName]

# Extract ingress port from main container
$ingressPort = $null
if ($mainContainer.ports) {
    foreach ($port in $mainContainer.ports) {
        if ($port.published) {
            $ingressPort = $port.published
            break
        }
    }
}
if (-not $ingressPort) {
    throw "❌ No published port found for main container '$mainContainerName'"
}

function Format-VolumeName {
    param ([string]$rawName)

    # Convert to lowercase
    $name = $rawName.ToLower()

    # Remove leading non-alphanumeric characters
    $name = $name -replace '^[^a-z0-9]+', ''

    # Replace remaining non-alphanumeric characters with hyphens
    $name = $name -replace '[^a-z0-9]', '-'

    # Trim trailing hyphens (optional but tidy)
    $name = $name -replace '-+$', ''

    return $name
}

function ConvertTo-Slug {
    param ([string]$name)
    return ($name.ToLower() -replace '[^a-z0-9\-]', '-') -replace '(^-+|-+$)', ''
}

# Build containers array
$containers = @()
$secrets = @()
$volumes = @()
$envHeuristics = 'KEY$|SECRET$|TOKEN$|PASSWORD$|CONNECTION_STRING|API_KEY|ACCESS_TOKEN|PRIVATE_KEY|CLIENT_SECRET'
foreach ($svcName in $compose.services.Keys) {
    $svc = $compose.services[$svcName]
    $container = @{
        name = $svcName
        image = $svc.image
        resources = @{
            cpu = 0.5
            memory = "1.0Gi"
        }
        env = @()
        volumeMounts = @()
    }

    if ($svc.environment) {
        foreach ($key in $svc.environment.Keys) {
            $value = $svc.environment[$key]
            if ($value -ne "") {
                $isSecret = $key -match $envHeuristics
                if ($isSecret) {
                    $secretName = ConvertTo-Slug -name $key
                    $secrets += @{ name = $secretName; value = $value }
                    $container.env += @{ name = $key; secretRef = $secretName }
                } else {
                    $container.env += @{ name = $key; value = $value }
                }

            }
        }
    }

    if ($svc.volumes) {
        foreach ($vol in $svc.volumes) {
            $volName = Format-VolumeName $vol.source
            $container.volumeMounts += @{ mountPath = $vol.target; volumeName = $volName }
            if (-not ($volumes | Where-Object { $_.name -eq $volName })) {
                $volumes += @{ name = $volName; storageType = "EmptyDir" }
            }
        }
    }

    $containers += $container
}

$secrets += @{ name = "acr-password"; value = $acrCreds.passwords[0].value }

# Final container app YAML structure
$containerApp = [ordered]@{
    type = "Microsoft.App/containerApps"
    location = $location
    identity = @{
        type = "SystemAssigned"
    }
    properties = [ordered]@{
        environmentId = "/subscriptions/$subscriptionId/resourceGroups/$envResourceGroup/providers/Microsoft.App/managedEnvironments/$envName"
        configuration = [ordered]@{
            registries = @($registries | ForEach-Object { 
                @{ 
                    server = $_
                    username = $acrCreds.username
                    passwordSecretRef = "acr-password"
                } 
            })
            secrets = $secrets
            ingress = @{
                external = $true
                targetPort = [int]$ingressPort
                allowInsecure = $false
                clientCertificateMode = "accept"
                corsPolicy = @{
                    allowedOrigins = @("*")
                    allowedHeaders = @("Authorization", "Content-Type")
                    exposeHeaders  = @("X-Custom-Header")
                    maxAge = 3600
                    allowCredentials = $false
                }
            }
        }
        template = [ordered]@{
            containers = $containers
            volumes = $volumes
            scale = @{
                minReplicas = 1
                maxReplicas = 3
            }
        }
    }
}

# Output YAML
$yamlOut = ConvertTo-Yaml $containerApp
if ($DryRun) {
    Write-Host "`n📦 Preview of generated containerapp.yaml:`n"
    Write-Output $yamlOut
    Write-Host "`n🟡 Dry run complete — no file was written."
} else {
    Set-Content -Path $outputPath -Value $yamlOut
    Write-Host "✅ Converted to $outputPath using '$mainContainerName' as main container with ingress on port $ingressPort"
}

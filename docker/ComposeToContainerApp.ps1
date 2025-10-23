param (
    [string]$dockerComposeYamlPath = "docker-compose.yml",
    [string]$outputPath = "containerapp.yaml",
    [switch]$DryRun
)

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

# Build containers array
$containers = @()
$secrets = @()
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
                $isSecret = $key -match 'KEY$|SECRET$|TOKEN$|PASSWORD$|CONNECTION_STRING$|API_KEY|ACCESS_TOKEN|PRIVATE_KEY|CLIENT_SECRET'
                if ($isSecret) {
                    $secrets += @{ name = $key; value = $value }
                    $container.env += @{ name = $key; secretRef = $key }
                } else {
                    $container.env += @{ name = $key; value = $value }
                }

            }
        }
    }

    if ($svc.volumes) {
        foreach ($vol in $svc.volumes) {
            $mountPath = $vol.target
            $volName = ($vol.source -replace '[^a-zA-Z0-9]', '_')
            $container.volumeMounts += @{
                volumeName = $volName
                mountPath = $mountPath
            }
        }
    }

    $containers += $container
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
# Build volume definitions
$volumes = @()
foreach ($volName in $compose.volumes.Keys) {
    $volumes += @{
        name = Format-VolumeName $volName
        storageType = "EmptyDir"
    }
}

# Final container app YAML structure
$containerApp = @{
    properties = @{
        containers = $containers
        ingress = @{
            external = $true
            targetPort = [int]$ingressPort
        }
        scale = @{
            minReplicas = 1
            maxReplicas = 3
        }
        volumes = $volumes
        secrets = $secrets
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

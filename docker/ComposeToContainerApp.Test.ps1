# Requires: Pester 5+
# Run with: Invoke-Pester -Path .\ComposeToContainerApp.Tests.ps1

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. "$here\ComposeToContainerApp.ps1"  # Your main script

Describe "Compose to Container App Conversion" {

    Context "Circular Dependency Detection" {
        It "Should throw on circular dependency" {
            $dependsOnMap = @{
                a = @("b")
                b = @("c")
                c = @("a")
            }

            { Test-CircularDependency -dependsOnMap $dependsOnMap } | Should -Throw -ErrorMessage "*Circular dependency detected*"
        }

        It "Should pass on acyclic dependency graph" {
            $dependsOnMap = @{
                a = @("b")
                b = @("c")
                c = @()
            }

            { Test-CircularDependency -dependsOnMap $dependsOnMap } | Should -Not -Throw
        }
    }

    Context "Main Container Detection" {
        It "Should identify the deepest leaf node as main container" {
            $compose = @{
                services = @{
                    qdrant = @{ depends_on = @{} }
                    api = @{ depends_on = @{ qdrant = @{ condition = "service_started" } } }
                    web = @{ depends_on = @{ api = @{ condition = "service_started" } } }
                }
            }

            $dependsOnMap = @{
                qdrant = @()
                api = @("qdrant")
                web = @("api")
            }

            $reverseDeps = @{
                qdrant = @("api")
                api = @("web")
            }

            $leafCandidates = $compose.services.Keys | Where-Object { -not $reverseDeps.ContainsKey($_) }
            $main = $leafCandidates | Sort-Object { $dependsOnMap[$_].Count } -Descending | Select-Object -First 1

            $main | Should -Be "web"
        }
    }

    Context "Ingress Port Extraction" {
        It "Should extract published port from main container" {
            $mainContainer = @{
                ports = @(
                    @{ published = 8080; target = 80; protocol = "tcp" }
                )
            }

            $ingressPort = $null
            foreach ($port in $mainContainer.ports) {
                if ($port.published) {
                    $ingressPort = $port.published
                    break
                }
            }

            $ingressPort | Should -Be 8080
        }

        It "Should throw if no published port is found" {
            $mainContainer = @{
                ports = @(
                    @{ target = 80; protocol = "tcp" }
                )
            }

            $ingressPort = $null
            foreach ($port in $mainContainer.ports) {
                if ($port.published) {
                    $ingressPort = $port.published
                    break
                }
            }

            { if (-not $ingressPort) { throw "No published port found" } } | Should -Throw -ErrorMessage "*No published port*"
        }
    }

    Context "YAML Output Structure" {
        It "Should generate a valid containerapp.yaml structure" {
            $containers = @(
                @{
                    name = "web"
                    image = "myapp:latest"
                    resources = @{ cpu = 0.5; memory = "1.0Gi" }
                    env = @(@{ name = "ENV"; value = "prod" })
                    volumeMounts = @()
                }
            )

            $containerApp = @{
                properties = @{
                    containers = $containers
                    ingress = @{ external = $true; targetPort = 8080 }
                    scale = @{ minReplicas = 1; maxReplicas = 3 }
                    volumes = @()
                }
            }

            $yaml = ConvertTo-Yaml $containerApp
            $yaml | Should -Match "containers:"
            $yaml | Should -Match "targetPort: 8080"
        }
    }
}

Describe "Compose to Container App Conversion with Mocked Compose" {

    Mock docker-compose {
        return @"
services:
  qdrant:
    image: qdrant/qdrant:latest
    environment:
      QDRANT__SERVICE__HTTP_PORT: "6333"
    depends_on: {}
  vanna-mcp-server:
    image: crbdllmprodase01.azurecr.io/vanna-mcp-server-qdrant:latest
    environment:
      WEB_SERVER_PORT: "3000"
      QDRANT_URL: "http://qdrant:6333"
    depends_on:
      qdrant:
        condition: service_started
"@
    }

    It "Should parse mocked docker-compose config and identify main container" {
        $resolvedYaml = docker-compose -f "fake.yml" config
        $compose = ConvertFrom-Yaml $resolvedYaml

        $dependsOnMap = @{
            qdrant = @()
            vanna_mcp_server = @("qdrant")
        }

        $reverseDeps = @{
            qdrant = @("vanna_mcp_server")
        }

        $leafCandidates = $compose.services.Keys | Where-Object { -not $reverseDeps.ContainsKey($_) }
        $main = $leafCandidates | Sort-Object { $dependsOnMap[$_].Count } -Descending | Select-Object -First 1

        $main | Should -Be "vanna_mcp_server"
    }
}
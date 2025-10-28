$acrsub = "6bcaf637-f26d-43d3-8e74-5e3753f7bde9"
$containersub = "a62cf7f5-1856-4cac-9748-fd26fee7c27d"
az account set --subscription $acrsub
$acrCreds = az acr credential show -n crbdllmprodase01 | ConvertFrom-Json  
az account set --subscription $containersub
az containerapp create `
    --name aca-is-vanna-dev-ae-04 `
    --resource-group rg-is-gpt-dev-aue `
    --environment acae-is-gpt-dev-aue-03 `
    --yaml containerapp.yaml `
    --registry-server crbdllmprodase01.azurecr.io `
    --registry-username $acrCreds.username `
    --registry-password $acrCreds.passwords[0].value
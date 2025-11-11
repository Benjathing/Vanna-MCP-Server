what have I done?

- used GEMINI to port the template-app-deploy files `main.bicep` & `azuredeploy.parameters.json` to this project (see GEMINI.md)
- adapted values as per RG (`rg-is-aihub-ae-01`), acr (`acraihubpocae01`) and storage account(`staihubpocae02`)
- used `storage-share.bicep` supplied by Pradeep
- imported the vanna-mcp image from the IS acr (`acriscommon`) to AI Hub acr (`acraihubpocae01`) using the commands:

```
# login to source subscription (IS)
$ az login
# set context to target subscription (AI Hub)
$ az account set --subscription ffc7ce20-1533-4547-abf8-71d5d651ebaf
# import container app (password left out)
$ az acr import --name acraihubpocae01 --resource-group rg-aihub-poc-ae-01 --source acriscommon.azurecr.io/vanna-mcp-server-qdrant:latest --username acriscommon --password <>
```

- create the fileshare vanna-data-mcp03 in the storage account staihubpocae02
(this is an empty fileshare, you need SAS keys and different roles than contributor to use something like `azcopy` which i tried)

- run the deployment script with the command:
`$ az deployment group create --resource-group rg-aihub-poc-ae-01 --template-file main.bicep --parameters @azuredeploy.parameters.json`



this doesn't work:

`azcopy copy 'https://saisollamadevaue03.file.core.windows.net/vanna-data-mcp03?sv=2024-11-04&ss=bfqt&srt=sco&sp=rwdlacupiytfx&se=2025-11-11T18:16:20Z&st=2025-11-11T10:01:20Z&spr=https&sig=denAy8RE7xfYWA8j%2FqQDQe3%2F%2FP%2BoiIZElFe42iwOWU%3D' 'https://staihubpocae02.file.core.windows.net/vanna-qdrant-mcp03?sv=2024-11-04&ss=bfqt&srt=sco&sp=rwdlacupiytfx&se=2025-11-11T18:14:01Z&st=2025-11-11T09:59:01Z&spr=https&sig=1A0ALtZAYf2CRsVq2QUA9SfGCJCsEKZJNqZhVSPS3dg%3D' --recursive=true`
param(
    [string]$Increment = "build", # major, minor, build
    [switch]$Alpha = $false,
    [string]$EnvFilePath = "./.env"
)

# --- 1. Load .env file ---
$envContent = @{}
Get-Content $EnvFilePath | ForEach-Object {
    $line = $_.Trim()
    if (-not [string]::IsNullOrEmpty($line) -and -not $line.StartsWith("#")) {
        $parts = $line.Split("=", 2)
        if ($parts.Length -eq 2) {
            $key = $parts[0].Trim()
            $value = $parts[1].Trim()
            # Remove quotes if present
            if ($value.StartsWith('"') -and $value.EndsWith('"')) {
                $value = $value.Substring(1, $value.Length - 2)
            } elseif ($value.StartsWith('''') -and $value.EndsWith('''')) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $envContent[$key] = $value
        }
    }
}

$DOCKER_REPOSITORY = $envContent["DOCKER_REPOSITORY"]
$VANNA_IMAGE_FULL = $envContent["VANNA_IMAGE"]

$imageName = $VANNA_IMAGE_FULL.Split(":")[0]

if (-not $DOCKER_REPOSITORY) {
    Write-Error "DOCKER_REPOSITORY not found in .env file."
    exit 1
}
if (-not $VANNA_IMAGE_FULL) {
    Write-Error "VANNA_IMAGE not found in .env file."
    exit 1
}

# --- 2. Get latest semantic tag from ACR ---
Write-Host "Querying all image tags for $imageName from $DOCKER_REPOSITORY..."
$versionToParse = "0.0.0" # Initialize with default
try {
    $allTags = az acr repository show-tags --name $DOCKER_REPOSITORY --repository $imageName --query "[]" --output tsv | Sort-Object -Descending

    $semanticTags = @($allTags | Where-Object { $_ -match "^\d+\.\d+\.\d+(-alpha)?$" })


    if ($semanticTags.Count -eq 0) {
        Write-Host "No semantic version tags found for $imageName. Starting with 0.0.0."
        # $versionToParse is already "0.0.0" from initialization
    } else {
        # Sort semantic tags to find the highest version
        # This requires a custom sort for semantic versioning
        $sortedSemanticTags = @($semanticTags | Sort-Object {
            $parts = $_.Replace("-alpha", "").Split(".")
            [version]"$($parts[0]).$($parts[1]).$($parts[2])"
        } -Descending)

        $latestSemanticTag = $sortedSemanticTags[0]
        Write-Host "Latest semantic tag found: $latestSemanticTag"
        # Remove -alpha suffix here, after selecting the latest tag
        $versionToParse = $latestSemanticTag.Replace("-alpha", "")
    }
} catch {
    Write-Error "Failed to query ACR for tags. Ensure Azure CLI is installed and you are logged in, and the repository exists."
    exit 1
}

# Split version into major, minor, build
$versionParts = $versionToParse.Split(".")
if ($versionParts.Length -lt 3) {
    Write-Error "Parsed version '$versionToParse' is not in a valid X.Y.Z format. Please ensure tags follow semantic versioning."
    exit 1
}
$major = [int]$versionParts[0]
$minor = [int]$versionParts[1]
$build = [int]$versionParts[2]

# --- 3. Increment version ---
switch ($Increment) {
    "major" {
        $major++
        $minor = 0
        $build = 0
    }
    "minor" {
        $minor++
        $build = 0
    }
    "build" {
        $build++
    }
    default {
        Write-Error "Invalid increment type: $Increment. Must be 'major', 'minor', or 'build'."
        exit 1
    }
}

$newTag = "$major.$minor.$build"
if ($Alpha) {
    $newTag += "-alpha"
}

Write-Host "Building new image with tag: $newTag"

# --- 4. Authenticate to ACR ---
Write-Host "Logging into Azure Container Registry: $DOCKER_REPOSITORY"
try {
    az acr login --name $DOCKER_REPOSITORY
} catch {
    Write-Error "Failed to log into Azure Container Registry. Ensure Azure CLI is installed and you are logged in." # This error message is for the host, not the container
    exit 1
}

# --- 5. Build Docker image ---
$fullImageName = "$DOCKER_REPOSITORY/$($imageName):$newTag"
Write-Host "Building Docker image: $fullImageName"
try {
    # Assuming Dockerfile is in the parent directory (../) relative to this script
    docker build -t $fullImageName -f ../Dockerfile ..
} catch {
    Write-Error "Failed to build Docker image."
    exit 1
}

# --- 6. Push Docker image (new versioned tag) ---
Write-Host "Pushing Docker image: $fullImageName"
try {
    docker push $fullImageName
} catch {
    Write-Error "Failed to push Docker image with versioned tag."
    exit 1
}

# --- 7. Retag as :latest and push ---
$latestFullImageName = "$DOCKER_REPOSITORY/$($imageName):latest"
Write-Host "Retagging $fullImageName as $latestFullImageName and pushing..."
try {
    docker tag $fullImageName $latestFullImageName
    docker push $latestFullImageName
} catch {
    Write-Error "Failed to retag and push Docker image as :latest."
    exit 1
}

Write-Host "Successfully built and pushed $fullImageName and $latestFullImageName"

# --- 8. Update .env with new image tag ---
Write-Host "New VANNA_IMAGE tag: $($imageName):$newTag"
Write-Host "Please update your .env file manually if you wish to use this new tag: VANNA_IMAGE=$($imageName):$newTag"

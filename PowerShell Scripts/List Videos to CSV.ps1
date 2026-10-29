# Source drive
$sourceDrive = "D:\"

# Output files
$videoCsv = "D:\VideoFiles.csv"
$imageCsv = "D:\ImageFiles.csv"

# Extensions
$videoExtensions = @(
    "*.mp4","*.mkv","*.avi","*.mov","*.wmv",
    "*.flv","*.webm","*.m4v","*.mpg","*.mpeg","*.3gp"
)

$imageExtensions = @(
    "*.jpg","*.jpeg","*.png","*.gif","*.bmp",
    "*.tif","*.tiff","*.webp","*.heic","*.heif"
)

# Videos
Get-ChildItem -Path $sourceDrive -Recurse -File -Include $videoExtensions -ErrorAction SilentlyContinue |
Select-Object `
    Name,
    FullName,
    Extension,
    @{Name='SizeMB';Expression={[Math]::Round($_.Length / 1MB, 2)}} |
Export-Csv -Path $videoCsv -NoTypeInformation -Encoding UTF8

# Images
Get-ChildItem -Path $sourceDrive -Recurse -File -Include $imageExtensions -ErrorAction SilentlyContinue |
Select-Object `
    Name,
    FullName,
    Extension,
    @{Name='SizeMB';Expression={[Math]::Round($_.Length / 1MB, 2)}} |
Export-Csv -Path $imageCsv -NoTypeInformation -Encoding UTF8

Write-Host "Video CSV: $videoCsv"
Write-Host "Image CSV: $imageCsv"
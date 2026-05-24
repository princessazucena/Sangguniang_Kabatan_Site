Add-Type -AssemblyName System.Drawing
Get-ChildItem static\images -Filter *.jpg | ForEach-Object {
    $img = [System.Drawing.Image]::FromFile($_.FullName)
    [pscustomobject]@{
        Name   = $_.Name
        Width  = $img.Width
        Height = $img.Height
        Ratio  = [math]::Round($img.Width / $img.Height, 2)
    }
    $img.Dispose()
} | Format-Table -AutoSize

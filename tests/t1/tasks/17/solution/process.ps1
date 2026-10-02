$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$inputPath = Join-Path $root '资料\输入.txt'
$outputPath = Join-Path $root '结果\处理结果.txt'
$lines = [System.IO.File]::ReadAllLines($inputPath, [System.Text.Encoding]::UTF8)
[System.IO.Directory]::CreateDirectory((Split-Path -Parent $outputPath)) | Out-Null
$content = ($lines -join "`r`n") + "`r`n"
[System.IO.File]::WriteAllText($outputPath, $content, [System.Text.UTF8Encoding]::new($false))

# Create desktop + Start menu shortcuts that start Atlas from this checkout (source mode).
$root = Split-Path -Parent $PSScriptRoot
$shell = New-Object -ComObject WScript.Shell
$targets = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Atlas.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'Atlas.lnk')
)
foreach ($path in $targets) {
  $link = $shell.CreateShortcut($path)
  $link.TargetPath = "$env:WINDIR\System32\wscript.exe"
  $link.Arguments = '"' + (Join-Path $root 'scripts\Atlas.vbs') + '"'
  $link.WorkingDirectory = $root
  $link.IconLocation = (Join-Path $root 'frontend\assets\icon\icon.ico') + ',0'
  $link.Description = 'Atlas (runs from ' + $root + ')'
  $link.Save()
  "shortcut: $path"
}

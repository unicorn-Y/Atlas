param(
  [Parameter(Mandatory = $true)][string]$Exe,
  [string]$ArgumentList = '',
  [string]$WorkingDirectory = '',
  [int]$WaitSeconds = 10,
  [string]$ErrorDialogTitle = '',
  [int]$CloseTimeoutSeconds = 20
)
$ErrorActionPreference = 'Continue'
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Exe
$psi.UseShellExecute = $false
if ($ArgumentList -ne '') { $psi.Arguments = $ArgumentList }
if ($WorkingDirectory -ne '') { $psi.WorkingDirectory = $WorkingDirectory }
$p = [System.Diagnostics.Process]::Start($psi)
Start-Sleep -Seconds $WaitSeconds
$alive = -not $p.HasExited
$title = ''
if ($alive) {
  $proc = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
  if ($proc) { $title = $proc.MainWindowTitle }
}
$children = @()
try {
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" | Select-Object -ExpandProperty Name
} catch {}
Write-Output "PID=$($p.Id)"
Write-Output "ALIVE_AFTER_${WaitSeconds}s=$alive"
Write-Output "MAIN_WINDOW_TITLE=$title"
Write-Output "CHILDREN=$($children -join ',')"

if ($ErrorDialogTitle -ne '') {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  $root = [System.Windows.Automation.AutomationElement]::RootElement
  $condition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $p.Id)
  $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)
  Write-Output "UIA_WINDOW_COUNT=$($windows.Count)"
  $dialog = $null
  foreach ($window in $windows) {
    Write-Output "UIA_WINDOW_NAME=$($window.Current.Name)"
    if ($window.Current.Name -eq $ErrorDialogTitle) { $dialog = $window }
  }
  if ($dialog -ne $null) {
    $textCondition = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Text)
    $texts = $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, $textCondition)
    foreach ($text in $texts) {
      $value = $text.Current.Name
      if ([string]::IsNullOrEmpty($value)) {
        try { $value = $text.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch {}
      }
      Write-Output "ERROR_DIALOG_TEXT=$($value -replace "`r?`n", ' | ')"
    }
    $closePattern = $null
    if ($dialog.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern, [ref]$closePattern)) {
      $closePattern.Close()
    }
  }
}

if (-not $p.HasExited) {
  $proc = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
  if ($proc) { [void]$proc.CloseMainWindow() }
}
$exited = $p.WaitForExit($CloseTimeoutSeconds * 1000)
if (-not $exited) {
  Write-Output "GRACEFUL_EXIT=false"
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  $p.WaitForExit(5000) | Out-Null
} else {
  Write-Output "GRACEFUL_EXIT=true"
}
Write-Output "EXIT_CODE=$($p.ExitCode)"
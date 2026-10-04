# 环境自检脚本：输出运行环境信息（任务需要读取这些输出）。
Write-Output "ENV-NAME=atlas-live-pwsh"
Write-Output "PS-VERSION=$($PSVersionTable.PSVersion.ToString())"
Write-Output "HOSTNAME=$env:COMPUTERNAME"

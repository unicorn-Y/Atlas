# Codex 逆向图鉴 — 一键打开
# 用法：右键 -> 使用 PowerShell 运行；或在 PowerShell 里执行 .\start-viewer.ps1

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path   # ...\codex\viewer
$root = Split-Path -Parent $here                          # ...\codex

Write-Host "启动本地静态服务器 (http://127.0.0.1:8848) ..." -ForegroundColor Cyan
Write-Host "根目录: $root"

# 优先用 python（自带 http.server），退回 node
$py = (Get-Command python -ErrorAction SilentlyContinue)
$node = (Get-Command node -ErrorAction SilentlyContinue)

if ($py) {
    # 以 codex 根目录为站点根，这样 viewer 可以访问 ../ui/screenshots 与 data.json
    Start-Process -WindowStyle Hidden -FilePath $py.Source `
        -ArgumentList '-m','http.server','8848','--bind','127.0.0.1','--directory',$root
} elseif ($node) {
    $srv = Join-Path $env:TEMP 'codex-viewer-server.js'
    @"
const http=require('http'),fs=require('fs'),path=require('path');
const root=process.argv[2];
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml','.md':'text/markdown'};
http.createServer((req,res)=>{
  let p=decodeURIComponent(req.url.split('?')[0]);
  if(p==='/')p='/viewer/index.html';
  const f=path.join(root,p);
  fs.readFile(f,(e,d)=>{
    if(e){res.writeHead(404);res.end('not found');return;}
    res.writeHead(200,{'Content-Type':types[path.extname(f)]||'application/octet-stream'});
    res.end(d);
  });
}).listen(8848,'127.0.0.1');
"@ | Set-Content -Encoding UTF8 $srv
    Start-Process -WindowStyle Hidden -FilePath $node.Source -ArgumentList $srv,$root
} else {
    throw "需要 python 或 node 才能启动本地服务器"
}

Start-Sleep -Seconds 2
Start-Process 'http://127.0.0.1:8848/viewer/index.html'
Write-Host "已打开： http://127.0.0.1:8848/viewer/index.html" -ForegroundColor Green
Write-Host "关闭服务器： Get-Process python,node | Where-Object {`$_.StartTime -gt (Get-Date).AddMinutes(-1) } | Stop-Process"

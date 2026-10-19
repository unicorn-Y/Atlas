param(
  [string]$Prefix = 'http://127.0.0.1:49375/',
  [string]$RequestLog = 'D:\temp\opencode-g4\provider-requests.jsonl',
  [string]$ToolPath = 'D:\temp\opencode-g4\workspace\proof.txt',
  [ValidateSet('read', 'subagent')][string]$Mode = 'read'
)

$ErrorActionPreference = 'Stop'
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add($Prefix)
$listener.Start()
$count = 0
while ($listener.IsListening) {
  $context = $listener.GetContext()
  $reader = [System.IO.StreamReader]::new($context.Request.InputStream, $context.Request.ContentEncoding)
  $body = $reader.ReadToEnd()
  $reader.Dispose()
  $count++
  $model = try { ($body | ConvertFrom-Json).model } catch { $null }
  $record = [ordered]@{
    request = $count
    method = $context.Request.HttpMethod
    path = $context.Request.Url.AbsolutePath
    model = $model
    bytes = [System.Text.Encoding]::UTF8.GetByteCount($body)
  }
  Add-Content -LiteralPath $RequestLog -Value ($record | ConvertTo-Json -Compress)
  $context.Response.StatusCode = 200
  $context.Response.ContentType = 'text/event-stream'
  $context.Response.Headers['Cache-Control'] = 'no-cache'
  $context.Response.SendChunked = $true
  $writer = [System.IO.StreamWriter]::new($context.Response.OutputStream, [System.Text.UTF8Encoding]::new($false))
  $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  if ($Mode -eq 'subagent' -and $count -eq 1) {
    $toolArgs = @{
      agent='explore'
      description='Read scratch proof'
      prompt="Read $ToolPath with the read tool and return its exact contents. Do not change files."
      background=$false
    } | ConvertTo-Json -Compress
    $chunks = @(
      @{id='chatcmpl-synthetic-subagent-1';object='chat.completion.chunk';created=$now;model='dummy';choices=@(@{index=0;delta=@{role='assistant';tool_calls=@(@{index=0;id='call_synthetic_subagent';type='function';function=@{name='subagent';arguments=$toolArgs}})};finish_reason=$null})},
      @{id='chatcmpl-synthetic-subagent-1';object='chat.completion.chunk';created=$now;model='dummy';choices=@(@{index=0;delta=@{};finish_reason='tool_calls'})}
    )
  } elseif ($Mode -eq 'read' -and $count -eq 1 -or $Mode -eq 'subagent' -and $count -eq 2) {
    $toolArgs = @{path=$ToolPath} | ConvertTo-Json -Compress
    $chunks = @(
      @{id='chatcmpl-synthetic-1';object='chat.completion.chunk';created=$now;model='dummy';choices=@(@{index=0;delta=@{role='assistant';tool_calls=@(@{index=0;id='call_synthetic_read';type='function';function=@{name='read';arguments=$toolArgs}})};finish_reason=$null})},
      @{id='chatcmpl-synthetic-1';object='chat.completion.chunk';created=$now;model='dummy';choices=@(@{index=0;delta=@{};finish_reason='tool_calls'})}
    )
  } else {
    $chunks = @(
      @{id='chatcmpl-synthetic-2';object='chat.completion.chunk';created=$now;model='dummy';choices=@(@{index=0;delta=@{role='assistant';content='SYNTHETIC-TOOL-CHAIN-OK'};finish_reason=$null})},
      @{id='chatcmpl-synthetic-2';object='chat.completion.chunk';created=$now;model='dummy';choices=@(@{index=0;delta=@{};finish_reason='stop'})}
    )
  }
  foreach ($chunk in $chunks) {
    $writer.Write("data: $($chunk | ConvertTo-Json -Depth 12 -Compress)`n`n")
    $writer.Flush()
  }
  $writer.Write("data: [DONE]`n`n")
  $writer.Flush()
  $context.Response.Close()
}

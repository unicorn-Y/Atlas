param([Parameter(Mandatory = $true)][string]$Root)

$ErrorActionPreference = 'Stop'
$paths = @((ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())))
$rows = [System.Collections.Generic.List[object]]::new()

function Get-Sha256([string]$Value) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $hash = [System.Security.Cryptography.SHA256]::HashData($bytes)
    return [Convert]::ToHexString($hash).ToLowerInvariant()
}

foreach ($relative in $paths) {
    $absolute = Join-Path $Root ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $absolute, [ref]$tokens, [ref]$parseErrors
    )
    $diagnostics = @($parseErrors | ForEach-Object {
        [ordered]@{
            error_id = $_.ErrorId
            line = $_.Extent.StartLineNumber
            column = $_.Extent.StartColumnNumber
        }
    })
    $contracts = [System.Collections.Generic.List[object]]::new()
    $functions = $ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true)
    foreach ($function in $functions) {
        $parameters = [System.Collections.Generic.List[object]]::new()
        if ($function.Body.ParamBlock) {
            foreach ($parameter in $function.Body.ParamBlock.Parameters) {
                $name = '$' + $parameter.Name.VariablePath.UserPath
                $defaultDigest = $null
                if ($parameter.DefaultValue) {
                    $defaultDigest = Get-Sha256 $parameter.DefaultValue.Extent.Text
                }
                $parameters.Add([ordered]@{
                    name = $name
                    default_digest = $defaultDigest
                })
            }
        }
        $exceptions = [System.Collections.Generic.List[object]]::new()
        foreach ($item in $function.Body.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.ThrowStatementAst]
        }, $true)) {
            $exceptions.Add([ordered]@{ kind = 'throw'; line = $item.Extent.StartLineNumber })
        }
        foreach ($item in $function.Body.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.CatchClauseAst]
        }, $true)) {
            $exceptions.Add([ordered]@{ kind = 'catch'; line = $item.Extent.StartLineNumber })
        }
        foreach ($item in $function.Body.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.TryStatementAst] -and $null -ne $node.Finally
        }, $true)) {
            $exceptions.Add([ordered]@{ kind = 'finally'; line = $item.Finally.Extent.StartLineNumber })
        }
        $platformBranches = [System.Collections.Generic.List[object]]::new()
        foreach ($item in $function.Body.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.IfStatementAst]
        }, $true)) {
            foreach ($clause in $item.Clauses) {
                $condition = $clause.Item1.Extent.Text
                if ($condition -match '(?i)IsWindows|IsMacOS|IsLinux|OperatingSystem|Platform') {
                    $platformBranches.Add([ordered]@{
                        line = $clause.Item1.Extent.StartLineNumber
                        expression_digest = Get-Sha256 $condition
                    })
                }
            }
        }
        $stateTransitions = [System.Collections.Generic.List[object]]::new()
        foreach ($item in $function.Body.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.AssignmentStatementAst]
        }, $true)) {
            $target = $item.Left.Extent.Text
            if ($target -match '(?i)^\$(state|status|phase)$') {
                $stateTransitions.Add([ordered]@{
                    target = $target
                    line = $item.Extent.StartLineNumber
                    value_digest = Get-Sha256 $item.Right.Extent.Text
                })
            }
        }
        $contracts.Add([ordered]@{
            kind = 'powershell_function'
            qualname = $function.Name
            source_span = [ordered]@{
                start_line = $function.Extent.StartLineNumber
                end_line = $function.Extent.EndLineNumber
            }
            parameters = @($parameters)
            obligations = [ordered]@{
                exceptions = @($exceptions | Sort-Object line, kind)
                platform_branches = @($platformBranches | Sort-Object line)
                state_transitions = @($stateTransitions | Sort-Object line, target)
            }
        })
    }
    $rows.Add([ordered]@{
        path = $relative
        contracts = @($contracts)
        parse_diagnostics = $diagnostics
    })
}

ConvertTo-Json -InputObject @($rows) -Depth 20 -Compress

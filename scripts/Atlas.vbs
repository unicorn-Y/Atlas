' Launch Atlas from this checkout without a console window (builds once if needed).
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
CreateObject("WScript.Shell").Run "node """ & root & "\scripts\atlas-update.mjs"" --launch-only", 0, False

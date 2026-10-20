"""Utility to create a Windows Desktop shortcut for KuroCompress with its custom icon."""

import os
import subprocess
import sys


def create_desktop_shortcut() -> bool:
    """Create a Windows desktop shortcut pointing to KuroCompress with the custom icon."""
    if sys.platform != "win32":
        print("Desktop shortcut creation is only supported on Windows.")
        return False

    script_dir = os.path.dirname(os.path.abspath(__file__))
    app_py = os.path.join(script_dir, "app.py")
    ico_path = os.path.join(script_dir, "assets", "icon.ico")

    ps_script = f"""
$Desktop = [Environment]::GetFolderPath('Desktop')
$WshShell = New-Object -ComObject WScript.Shell
$LnkPath = Join-Path $Desktop "KuroCompress.lnk"

# Locate pythonw for background launch without black terminal window
$PythonCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $PythonCmd) {{
    $PythonCmd = Get-Command python.exe
}}

$Shortcut = $WshShell.CreateShortcut($LnkPath)
$Shortcut.TargetPath = $PythonCmd.Source
$Shortcut.Arguments = '"{app_py}"'
$Shortcut.WorkingDirectory = '{script_dir}'
$Shortcut.IconLocation = '{ico_path}'
$Shortcut.Description = 'KuroCompress — Modern Video Compressor'
$Shortcut.Save()

if (Test-Path $LnkPath) {{
    Write-Output "SUCCESS: $LnkPath"
}} else {{
    Write-Error "FAILED"
}}
"""

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=True,
        )
        if "SUCCESS" in res.stdout:
            print("✓ Desktop shortcut created successfully with custom icon!")
            return True
        else:
            print(f"Failed to create shortcut: {res.stderr}")
            return False
    except Exception as e:
        print(f"Error creating shortcut: {e}")
        return False


if __name__ == "__main__":
    create_desktop_shortcut()


@echo off
rem hullcheck wrapper for Windows. Finds Blender, passes every argument through.
rem Override the Blender path with: set HULLCHECK_BLENDER=C:\path\to\blender.exe
setlocal

set "SCRIPT=%~dp0hullcheck.py"

if defined HULLCHECK_BLENDER (
  set "BLENDER=%HULLCHECK_BLENDER%"
) else (
  set "BLENDER="
  for /d %%V in ("C:\Program Files\Blender Foundation\Blender*") do (
    if exist "%%~fV\blender.exe" set "BLENDER=%%~fV\blender.exe"
  )
)

if not defined BLENDER (
  echo hullcheck: Blender not found. Install Blender or set HULLCHECK_BLENDER to blender.exe
  exit /b 2
)

"%BLENDER%" --background --factory-startup --python "%SCRIPT%" -- %*
exit /b %ERRORLEVEL%

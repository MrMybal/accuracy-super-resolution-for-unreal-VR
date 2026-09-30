@echo off
setlocal
rem Arm ASR VR engine patch - apply / revert / status.
rem Usage: ArmASR_EnginePatch.bat [status|apply|revert|dryrun] [EngineRoot]
set "SCRIPT=%~dp0armasr_engine_patch.py"
set "ENGINE=%~2"
if "%ENGINE%"=="" set "ENGINE=J:\_AtlasXRInc\Unreality"

where python >nul 2>nul || (echo Python 3 is required and was not found in PATH. & pause & exit /b 1)

set "CMD=%~1"
if not "%CMD%"=="" goto run

:menu
echo.
echo  Arm ASR VR engine patch
echo  Engine: %ENGINE%
echo.
echo   1. Status
echo   2. Dry run (check that the patch can be applied)
echo   3. Apply
echo   4. Revert (restore the original files)
echo   5. Quit
echo.
set /p CHOICE="Choice: "
if "%CHOICE%"=="1" set "CMD=status"
if "%CHOICE%"=="2" set "CMD=dryrun"
if "%CHOICE%"=="3" set "CMD=apply"
if "%CHOICE%"=="4" set "CMD=revert"
if "%CHOICE%"=="5" exit /b 0
if "%CMD%"=="" goto menu

:run
if /i "%CMD%"=="dryrun" (
    python "%SCRIPT%" apply --dry-run --engine "%ENGINE%"
) else (
    python "%SCRIPT%" %CMD% --engine "%ENGINE%"
)
set "RESULT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RESULT%

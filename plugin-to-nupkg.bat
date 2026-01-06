@echo off
REM Disable command echoing for a cleaner output
echo.
echo --- Starting NuGet Package Builder ---

REM --- Initialization and Search Paths ---
set nugetexe=
set nuspecFile=plugin.nuspec

REM 1. Try to find nuget.exe using the system PATH (which works on your machine)
WHERE nuget.exe >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    set "nugetexe=nuget.exe"
    echo Found nuget.exe via system PATH.
)

REM --- Execute the Pack Command ---
IF DEFINED nugetexe (

    REM Optional: Set restore variable
    set EnableNugetPackageRestore=true

    echo.
    echo Attempting to package using spec file: %nuspecFile%

    REM The core NuGet command: pack the .nuspec file
    "%nugetexe%" pack "%nuspecFile%" -ExcludeEmptyDirectories

    REM Check the return code of the previous command
    IF %ERRORLEVEL% NEQ 0 (
        echo.
        echo ERROR: NuGet package creation failed! Check the output above for details.
    ) ELSE (
        echo.
        echo SUCCES: NuGet package created successfully! Look for the .nupkg file in this directory.
    )

) ELSE (
    echo.
    echo FATAL ERROR: nuget.exe could not be located on your system.
)

echo.
pause
REM The 'pause' command keeps the console window open until a key is pressed.
@echo off
REM Usage: chat.bat <init | post | show | connect> <args>
setlocal enabledelayedexpansion

REM Get function name
set "func=%~1"
shift

REM Call function
if "%func%"=="init" goto :init
if "%func%"=="post" goto :post
if "%func%"=="show" goto :show
if "%func%"=="connect" goto :connect
echo Unknown command: %func%
exit /b 1

:init
REM Arguments: %1 = username
set "name=%~1"
mkdir "%name%"
cd /d "%name%"

git init -b "%name%"
git config --local user.name "%name%"
git config --local user.email "%name%@example.com"

for /f %%A in ('echo. ^| git mktree') do set "emptyTree=%%A"

set "commitMsg=%name% joined the chatroom"
for /f %%C in ('echo %commitMsg% ^| git commit-tree %emptyTree%') do set "commitHash=%%C"

git update-ref refs/heads/%name% %commitHash%
git symbolic-ref HEAD refs/heads/%name%
exit /b 0

:post
REM Arguments: %1 = message
set "message=%~1"

REM Try to find a Git repo if not in one
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    for /d %%D in (*) do (
        if exist "%%D\.git" (
            cd /d "%%D"
            goto :post_continue
        )
    )
)

:post_continue
git fetch --all

for /f %%B in ('git symbolic-ref --short HEAD') do set "branch=%%B"

set "parents="
for /f %%R in ('git for-each-ref --format="%%(refname)"') do (
    for /f %%C in ('git rev-parse %%R 2^>nul') do (
        set "parents=!parents! -p %%C"
    )
)

for /f %%E in ('echo. ^| git mktree') do set "empty_tree=%%E"
for /f %%N in ('echo %message% ^| git commit-tree %empty_tree% !parents!') do set "new_commit=%%N"

git update-ref refs/heads/%branch% %new_commit%
exit /b 0

:show
REM Show log
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    for /d %%D in (*) do (
        if exist "%%D\.git" (
            cd /d "%%D"
            goto :show_continue
        )
    )
)

:show_continue
git log --all --topo-order --pretty=format:"%%an (%%ad): %%s" --date=local
exit /b 0

:connect
REM Arguments: %1 = remote_repo
set "remote_repo=%~1"

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    for /d %%D in (*) do (
        if exist "%%D\.git" (
            if /i not "%%D"=="%~nx1" (
                cd /d "%%D"
                goto :connect_continue
            )
        )
    )
)

:connect_continue
for %%R in (%remote_repo%) do set "remote_name=%%~nR"
git remote add %remote_name% "%remote_repo%"
git fetch %remote_name%
git branch --track %remote_name% %remote_name%/%remote_name%
exit /b 0

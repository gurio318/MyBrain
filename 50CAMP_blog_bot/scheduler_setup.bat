@echo off
chcp 65001 > nul

REM ============================================================
REM  Windowsタスクスケジューラ 自動登録スクリプト
REM  毎朝10:00 に1記事生成＆下書き保存するタスクを登録します
REM ============================================================

set TASK_NAME=50CAMP_Blog_Auto
set SCRIPT_DIR=%~dp0
set PYTHON_SCRIPT=%SCRIPT_DIR%generate_and_post.py

echo ========================================
echo  タスクスケジューラへの登録
echo ========================================
echo.
echo タスク名: %TASK_NAME%
echo 実行時刻: 毎朝 10:00
echo 実行内容: 1記事生成 → WordPress下書き保存
echo.

REM 既存タスクがあれば削除
schtasks /delete /tn "%TASK_NAME%" /f > nul 2>&1

REM タスク登録
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "python \"%PYTHON_SCRIPT%\"" ^
  /sc DAILY ^
  /st 10:00 ^
  /ru "%USERNAME%" ^
  /f

if errorlevel 1 (
    echo [ERROR] タスクの登録に失敗しました。
    echo         管理者として実行してください（右クリック→管理者として実行）
    pause
    exit /b 1
)

echo.
echo [SUCCESS] タスクを登録しました！
echo           毎朝10:00に自動で記事が生成されます。
echo.
echo タスクの確認: タスクスケジューラ を開いて「%TASK_NAME%」を探してください。
echo タスクの停止: schtasks /delete /tn "%TASK_NAME%" /f
echo.
pause

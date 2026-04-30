@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo   50CAMP ブログ自動化ボット
echo ========================================
echo.

REM Pythonの確認
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python が見つかりません。
    echo         https://www.python.org/ からインストールしてください。
    pause
    exit /b 1
)

REM anthropicライブラリの確認・インストール
python -c "import anthropic" > nul 2>&1
if errorlevel 1 (
    echo [INFO] anthropic ライブラリをインストールします...
    pip install anthropic --quiet
)

echo [START] 記事生成を開始します...
echo         1記事生成して 下書き保存 します。
echo.

python generate_and_post.py

echo.
echo [DONE] 処理が完了しました。
echo        WordPressの下書きを確認してください。
echo.
pause

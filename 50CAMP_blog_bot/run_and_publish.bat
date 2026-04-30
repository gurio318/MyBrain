@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo   50CAMP ブログ自動化ボット（即時公開）
echo ========================================
echo.
echo [警告] このバッチは記事を即時公開します！
echo.

python generate_and_post.py --publish

echo.
echo [DONE] 公開完了！WordPress で確認してください。
pause

@echo off
echo ========================================
echo Webull Portfolio Rebalancer Bot
echo ========================================
echo.

REM 仮想環境のアクティベート
if exist .venv\Scripts\activate.bat (
    echo 仮想環境をアクティベート中...
    call .venv\Scripts\activate.bat
) else (
    echo 仮想環境が見つかりません。通常のPythonを使用します。
)

REM 依存関係の確認
echo 依存関係を確認中...
python -c "import webull" 2>nul
if errorlevel 1 (
    echo Webullライブラリがインストールされていません。インストール中...
    pip install -r requirements.txt
)

echo.
echo リバランシングを開始します...
echo.

REM リバランシングの実行
python run_rebalancing.py --live

echo.
echo リバランシングが完了しました。
pause

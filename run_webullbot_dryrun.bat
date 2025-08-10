@echo off
echo ========================================
echo Webull Portfolio Rebalancer Bot (DRY RUN)
echo ========================================
echo.

REM 仮想環境のアクティベート
if exist .venv\Scripts\activate.bat (
    echo 仮想環境をアクティベート中...
    call .venv\Scripts\activate.bat
) else (
    echo 仮想環境が見つかりません。通常のPythonを使用します。
)

REM 依存関係の確認（公式OpenAPI SDK群）
echo 依存関係を確認中...
python -c "import importlib,importlib.util,sys;mods=['webullsdkcore','webullsdktrade','webullsdkmdata','webullsdktradeeventscore'];missing=[m for m in mods if importlib.util.find_spec(m) is None];sys.exit(1 if missing else 0)" 2>nul
if errorlevel 1 (
    echo SDKが見つかりません。インストール中...
    pip install -r requirements.txt
)

echo.
echo ドライランでリバランシングを開始します...
echo.

REM ドライランでリバランシングの実行
python webull_bot_unified.py

echo.
echo ドライランが完了しました。
pause 
@echo off
echo ========================================
echo Webull Portfolio Rebalancer Bot Setup
echo ========================================
echo.

REM Pythonの確認
python --version
if errorlevel 1 (
    echo Pythonがインストールされていません。
    echo Python 3.8以上をインストールしてください。
    pause
    exit /b 1
)

echo.
echo 仮想環境を作成中...
python -m venv .venv

echo.
echo 仮想環境をアクティベート中...
call .venv\Scripts\activate.bat

echo.
echo 依存関係をインストール中...
pip install -r requirements.txt

echo.
echo セットアップが完了しました！
echo.
echo 使用方法:
echo   run_webullbot_dryrun.bat - ドライランでテスト
echo   run_webullbot.bat - 実際の取引を実行
echo.
pause 
#!/bin/bash

echo "========================================"
echo "Webull Portfolio Rebalancer Bot Setup"
echo "========================================"
echo

# Pythonの確認
if ! command -v python3 &> /dev/null; then
    echo "Python3がインストールされていません。"
    echo "Python 3.8以上をインストールしてください。"
    exit 1
fi

echo "Python3のバージョン:"
python3 --version

echo
echo "仮想環境を作成中..."
python3 -m venv .venv

echo
echo "仮想環境をアクティベート中..."
source .venv/bin/activate

echo
echo "依存関係をインストール中..."
pip3 install -r requirements.txt

echo
echo "セットアップが完了しました！"
echo
echo "使用方法:"
echo "  chmod +x run_webullbot_dryrun.sh"
echo "  chmod +x run_webullbot.sh"
echo "  ./run_webullbot_dryrun.sh - ドライランでテスト"
echo "  ./run_webullbot.sh - 実際の取引を実行"
echo 
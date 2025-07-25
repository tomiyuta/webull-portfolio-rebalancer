#!/bin/bash

echo "========================================"
echo "Webull Portfolio Rebalancer Bot (DRY RUN)"
echo "========================================"
echo

# 仮想環境のアクティベート
if [ -d ".venv" ]; then
    echo "仮想環境をアクティベート中..."
    source .venv/bin/activate
else
    echo "仮想環境が見つかりません。通常のPythonを使用します。"
fi

# 依存関係の確認
echo "依存関係を確認中..."
python3 -c "import webull" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Webullライブラリがインストールされていません。インストール中..."
    pip3 install -r requirements.txt
fi

echo
echo "ドライランでリバランシングを開始します..."
echo

# ドライランでリバランシングの実行
python3 run_rebalancing.py

echo
echo "ドライランが完了しました。"

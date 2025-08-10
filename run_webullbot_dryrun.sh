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

# 依存関係の確認（公式OpenAPI SDK群）
echo "依存関係を確認中..."
python3 - <<'PY'
import importlib, sys
mods = [
    'webullsdkcore',
    'webullsdktrade',
    'webullsdkmdata',
]
missing = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:
        missing.append(m)
if missing:
    sys.exit(1)
PY
if [ $? -ne 0 ]; then
    echo "SDKが見つかりません。インストール中..."
    pip3 install -r requirements.txt
fi

echo
echo "ドライランでリバランシングを開始します..."
echo

# ドライランでリバランシングの実行
python3 webull_bot_unified.py

echo
echo "ドライランが完了しました。"

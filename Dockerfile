FROM python:3.9-slim

WORKDIR /app

# 依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションファイルをコピー
COPY . .

# ログディレクトリを作成
RUN mkdir -p logs

# 実行権限を付与
RUN chmod +x run_webullbot.sh
RUN chmod +x run_webullbot_dryrun.sh

# デフォルトコマンド
CMD ["python3", "run_rebalancing.py"] 
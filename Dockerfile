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
RUN chmod +x run_webullbot_dryrun.sh

# エントリポイントの設定（APP_MODEで切替可能）
RUN chmod +x entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]
CMD ["python3", "webull_bot_unified.py"]
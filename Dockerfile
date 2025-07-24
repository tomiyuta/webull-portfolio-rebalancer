# Docker環境でgrpcioとWebull SDKをインストール
FROM python:3.9-slim

# 必要なパッケージをインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリを設定
WORKDIR /app

# Python依存関係をインストール
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel

# すべての依存関係をインストール
RUN pip install -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# テスト用のコマンド
CMD ["python", "-c", "import grpc; import webull; print('grpcio and webull SDK installed successfully')"] 
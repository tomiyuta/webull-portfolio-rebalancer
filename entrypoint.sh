#!/bin/sh
set -e

# APP_MODE=events でgRPC購読を起動。それ以外は引数のコマンドを実行（デフォルトはDockerfileのCMD）。
if [ "$APP_MODE" = "events" ]; then
  echo "[entrypoint] Starting trade events subscriber..."
  exec python3 subscribe_trade_events.py
else
  echo "[entrypoint] Starting default command: $@"
  exec "$@"
fi

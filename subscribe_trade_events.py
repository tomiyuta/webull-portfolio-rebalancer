#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Webull OpenAPI - Trade Events Subscriber (gRPC)
指定アカウントの注文ステータス変更イベントを購読してログ出力します。
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime

from webullsdkcore.common.region import Region
from webullsdktradeeventscore.events_client import EventsClient


def setup_logging() -> None:
    """ログ設定"""
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_filename = f"{log_dir}/trade_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


class TradeEventsSubscriber:
    def __init__(self, config_file: str = 'webull_config_with_allocation.json') -> None:
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_file)

        app_key = self.config.get('app_key')
        app_secret = self.config.get('app_secret')
        self.account_id = self.config.get('account_id')
        if not app_key or not app_secret or not self.account_id:
            raise ValueError('app_key, app_secret, account_id を設定してください')

        self.client = EventsClient(app_key, app_secret, Region.JP.value)
        self._setup_handlers()

        self.logger.info('TradeEventsSubscriber 初期化完了')
        self.logger.info(f'Account ID: {self.account_id}')

    def _load_config(self, config_file: str) -> dict:
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.getLogger(__name__).error(f'設定ファイル読み込みエラー: {e}')
            raise

    def _setup_handlers(self) -> None:
        def on_log(level, log_content):
            try:
                logging.log(level, f'[EventsClient] {log_content}')
            except Exception:
                logging.info(f'[EventsClient] {log_content}')

        def on_events_message(event_type, subscribe_type, payload, raw_message):
            # 受信イベントをそのままログに出力（必要に応じて条件分岐を追加）
            try:
                logging.info('[Event] type=%s subscribe_type=%s payload=%s', event_type, subscribe_type, json.dumps(payload))
            except Exception:
                logging.info('[Event] raw=%s', raw_message)

        self.client.on_log = on_log
        self.client.on_events_message = on_events_message

    def start(self) -> None:
        self.logger.info('gRPC購読を開始します（自動再接続対応）')
        backoff = 1.0
        while True:
            try:
                self.logger.info('購読要求を送信します')
                # SDK実装によりブロッキングの可能性があるため、ここで例外を待つ
                self.client.do_subscribe([self.account_id])
                # 正常終了ケースは通常ない想定。明示ログのみ。
                self.logger.warning('do_subscribeが終了しました。再接続します')
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.logger.error(f'gRPC購読エラー: {e}. {backoff:.1f}s後に再試行します')
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)  # 最大60秒まで指数バックオフ

    def run_forever(self) -> None:
        self.logger.info('Ctrl+Cで終了します')
        try:
            self.start()
        except KeyboardInterrupt:
            self.logger.info('終了シグナルを受信しました。購読を停止します')


def main() -> None:
    setup_logging()
    try:
        sub = TradeEventsSubscriber()
        sub.run_forever()
    except Exception as e:
        print(f'❌ Trade Events 購読エラー: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()

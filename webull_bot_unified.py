#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebullBot Unified - 統合版ポートフォリオリバランサー
残高確認、買い付け、売り付け、リバランシング機能を全て統合
"""

import json
import decimal
import logging
import pandas as pd
import numpy as np
import yfinance as yf
import time
import uuid
import os
import sys
import csv
import random
from datetime import datetime, timedelta
from webullsdktrade.api import API
from webullsdkcore.client import ApiClient
from webullsdkcore.common.region import Region

# ログ設定
def setup_logging():
    """構造化されたログ設定"""
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_filename = f"{log_dir}/webull_bot_{datetime.now().strftime('%Y%m%d')}.log"
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('webullsdkcore').setLevel(logging.WARNING)

setup_logging()

class WebullBotUnified:
    def __init__(self, config_file='webull_config_with_allocation.json', dry_run=None):
        """統合版WebullBotの初期化"""
        self.logger = logging.getLogger(__name__)
        self.config = self.load_config(config_file)
        
        if dry_run is not None:
            self.config['dry_run'] = dry_run
        
        self.api = self.initialize_api()
        self.account_id = self.config.get('account_id', '')
        self.dry_run = self.config.get('dry_run', True)
        
        # キャッシュの初期化
        self._price_cache = {}
        self._instrument_id_cache = {}
        self._last_api_call = {}
        self._last_price_method_by_symbol = {}
        
        # 設定の検証
        self.validate_config()
        
        # アカウントIDの確認
        if not self.ensure_account_id():
            raise ValueError("アカウントIDの取得に失敗しました。")
        
        # ポートフォリオ設定を読み込み
        portfolio_config_file = self.config.get('portfolio_config_file', 'portfolio.csv')
        self.target_allocation = self.load_portfolio_config(portfolio_config_file)
        
        self.logger.info("WebullBotUnified初期化完了")
        self.logger.info(f"Account ID: {self.account_id}")
        self.logger.info(f"Dry Run Mode: {self.dry_run}")

    # ==================== 共通ユーティリティ ====================

    def _get_api_setting(self, key: str, default_value):
        api_settings = self.config.get('api_settings', {}) or {}
        return api_settings.get(key, default_value)

    def _get_md_setting(self, key: str, default_value):
        md_settings = self.config.get('market_data_settings', {}) or {}
        return md_settings.get(key, default_value)

    def call_with_retry(self, func, *, operation_name: str = "api_call", max_retries: int = None, base_delay: float = None):
        """HTTPレスポンスベースのリトライ（429/5xx）。Retry-Afterを尊重し指数バックオフ+ジッタ。

        func: () -> response
        return: response
        """
        retry_status_codes = {429, 500, 502, 503, 504}
        max_retries = max_retries if max_retries is not None else int(self._get_api_setting('max_retries', 3))
        base_delay = base_delay if base_delay is not None else float(self._get_api_setting('retry_delay', 1.0))

        attempt = 0
        while True:
            response = None
            error = None
            try:
                response = func()
            except Exception as e:
                error = e

            if error is None and response is not None and response.status_code not in retry_status_codes:
                return response

            # 判定: リトライ終了条件
            if attempt >= max_retries:
                if error is not None:
                    self.logger.error(f"{operation_name} 失敗（例外）: {error}")
                else:
                    self.logger.error(f"{operation_name} 失敗（HTTP {response.status_code}）: {getattr(response, 'text', '')}")
                return response if response is not None else None

            # 待機時間算出
            delay = base_delay * (2 ** attempt)
            # Retry-Afterヘッダ
            if response is not None:
                try:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        delay = max(delay, float(retry_after))
                except Exception:
                    pass
            # ジッタ
            delay = delay * (1.0 + random.random() * 0.25)

            self.logger.warning(f"{operation_name} リトライ {attempt+1}/{max_retries} 待機 {delay:.2f}s")
            time.sleep(delay)
            attempt += 1

    def _resolve_instrument_type(self, symbol: str) -> str:
        """銘柄からinstrument_typeを推定（ETF判定はticker末尾やAPI照会で補強）"""
        try:
            # 明示的にAPIで照会してカテゴリを確認できる場合はそれを使う
            resp = self.call_with_retry(
                lambda: self.api.instrument.get_instrument(symbol, "US_ETF"),
                operation_name="detect_etf"
            )
            if resp is not None and resp.status_code == 200:
                data = resp.json()
                # レスポンスに当該symbolが含まれていればETFと推定
                if (isinstance(data, list) and any(d.get('symbol') == symbol for d in data)) or (
                    isinstance(data, dict) and data.get('symbol') == symbol
                ):
                    return "ETF"
        except Exception:
            pass

        # フォールバック簡易判定（ETFでありがちな記号でも確定ではないため最終手段）
        return "EQUITY"

    def load_config(self, config_file):
        """設定ファイルを読み込み"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.logger.info("設定ファイル読み込み成功")
            return config
        except Exception as e:
            self.logger.error(f"設定ファイル読み込みエラー: {e}")
            raise

    def validate_config(self):
        """設定の検証"""
        required_keys = ['app_key', 'app_secret', 'account_id']
        for key in required_keys:
            if not self.config.get(key):
                raise ValueError(f"必須設定 '{key}' が不足しています")

    def initialize_api(self):
        """Webull APIを初期化"""
        try:
            app_key = self.config.get('app_key')
            app_secret = self.config.get('app_secret')
            
            if not app_key or not app_secret:
                raise ValueError("app_keyまたはapp_secretが設定されていません")
            
            # API Client初期化
            api_client = ApiClient(app_key, app_secret, Region.JP.value, verify=True)
            api_client.add_endpoint('jp', 'api.webull.co.jp')
            api = API(api_client)
            
            self.logger.info("Webull API初期化成功")
            return api
        except Exception as e:
            self.logger.error(f"Webull API初期化エラー: {e}")
            raise

    def ensure_account_id(self):
        """アカウントIDの確認と取得（サンプルコード準拠）"""
        if self.account_id:
            self.logger.info(f"✅ アカウントID既に設定済み: {self.account_id}")
            return True
        
        try:
            # サンプルコードと同じAPI呼び出し: api.account.get_app_subscriptions()
            response = self.api.account.get_app_subscriptions()
            
            if response.status_code == 200:
                # サンプルコードと同じ処理: data = json.loads(response.text)
                data = json.loads(response.text)
                
                # サンプルコードと同じ処理: for d in data:
                for d in data:
                    # サンプルコードと同じ処理: if d.get('account_type') == "CASH":
                    if d.get('account_type') == "CASH":
                        account_number = d.get('account_number')
                        account_id = d.get('account_id')
                        
                        # サンプルコードと同じ出力形式
                        self.logger.info(f"account_number: {account_number}")
                        self.logger.info(f"account_id: {account_id}")
                        
                        self.account_id = str(account_id)
                        self.config['account_id'] = self.account_id
                        self.save_config()
                        self.logger.info(f"✅ アカウントID取得: {self.account_id}")
                        return True
                        
                self.logger.warning("CASH口座が見つかりませんでした")
            else:
                self.logger.error(f"アカウント情報取得失敗: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"アカウントID取得エラー: {e}")
        
        return False

    def save_config(self):
        """設定を保存"""
        try:
            with open('webull_config_with_allocation.json', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"設定保存エラー: {e}")

    def load_portfolio_config(self, portfolio_config_file):
        """ポートフォリオ設定を読み込み"""
        try:
            if portfolio_config_file.endswith('.csv'):
                return self.load_portfolio_config_csv(portfolio_config_file)
            else:
                return self.load_portfolio_config_json(portfolio_config_file)
        except Exception as e:
            self.logger.error(f"ポートフォリオ設定読み込みエラー: {e}")
            raise

    def load_portfolio_config_csv(self, portfolio_config_file):
        """CSVファイルからポートフォリオ設定を読み込み"""
        try:
            df = pd.read_csv(portfolio_config_file)
            target_allocation = {}
            
            for _, row in df.iterrows():
                symbol = row['symbol']
                allocation = row['allocation_percentage']
                target_allocation[symbol] = allocation
                self.logger.info(f"銘柄: {symbol} - 配分: {allocation}%")
            
            total_allocation = sum(target_allocation.values())
            self.logger.info(f"CSVポートフォリオ設定ファイル読み込み成功: {portfolio_config_file}")
            self.logger.info(f"ポートフォリオ名: CSV Portfolio ({portfolio_config_file})")
            self.logger.info(f"総銘柄数: {len(target_allocation)}")
            self.logger.info(f"配分合計: {total_allocation}%")
            
            return target_allocation
        except Exception as e:
            self.logger.error(f"CSVポートフォリオ設定読み込みエラー: {e}")
            raise

    def load_portfolio_config_json(self, portfolio_config_file):
        """JSONファイルからポートフォリオ設定を読み込み"""
        try:
            with open(portfolio_config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config.get('target_allocation', {})
        except Exception as e:
            self.logger.error(f"JSONポートフォリオ設定読み込みエラー: {e}")
            raise

    # ==================== 残高確認機能 ====================
    
    def get_account_balance(self):
        """アカウント残高を取得"""
        try:
            def api_call():
                return self.api.account_v2.get_account_balance(self.account_id)
            
            response = self.call_with_retry(api_call, operation_name="get_account_balance")
            if response.status_code == 200:
                balance_data = response.json()
                self.logger.info("口座残高取得成功（v2 API）")
                
                # 残高情報を整理
                balances = {}
                if 'account_currency_assets' in balance_data:
                    for asset in balance_data['account_currency_assets']:
                        currency = asset['currency']
                        balances[currency] = {
                            'cash_balance': float(asset['cash_balance']),
                            'buying_power': float(asset['buying_power']),
                            'unrealized_profit_loss': float(asset['unrealized_profit_loss']),
                            'available_cash': float(asset['buying_power']),
                            'original_buying_power': float(asset['buying_power']),
                            'safety_margin_applied': 0.0
                        }
                
                self.logger.info(f"口座残高詳細: {balances}")
                return balances
            else:
                self.logger.error(f"口座残高取得失敗: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            self.logger.error(f"口座残高取得エラー: {e}")
            return None

    def get_current_positions(self):
        """現在のポジションを取得"""
        try:
            res = self.call_with_retry(
                lambda: self.api.account_v2.get_account_position(self.account_id),
                operation_name="get_account_position"
            )
            if res is not None and res.status_code == 200:
                data = res.json()
                positions = []
                # v2 応答が list パターンと dict パターンの両対応
                if isinstance(data, dict):
                    groups = data.get('positions', [])
                else:
                    groups = data if isinstance(data, list) else []

                for group in groups:
                    items = group.get('items', []) if isinstance(group, dict) else []
                    for item in items:
                        symbol = item.get('symbol')
                        qty_raw = item.get('quantity') or item.get('qty') or 0
                        try:
                            qty_int = int(decimal.Decimal(str(qty_raw)))
                        except Exception:
                            qty_int = 0
                        if symbol:
                            positions.append({'symbol': symbol, 'quantity': qty_int})
                self.logger.info(f"取得ポジション数: {len(positions)}")
                return positions
            else:
                self.logger.error(f"ポジション取得失敗: {res.status_code} {res.text}")
                return []
        except Exception as e:
            self.logger.error(f"ポジション取得エラー: {e}")
            return []

    def get_stock_price(self, symbol):
        """株価を取得（Webull MDATA/Quotes優先→yfinanceフォールバック）"""
        try:
            # キャッシュをチェック
            if symbol in self._price_cache:
                cache_time, price = self._price_cache[symbol]
                ttl = int(self._get_md_setting('cache_ttl_seconds', 60))
                if time.time() - cache_time < ttl:
                    return price

            # まずWebullのMDATA/Quotes（スナップショット/最新価格）を試行
            try:
                instrument_id = self._instrument_id_cache.get(symbol)
                if not instrument_id:
                    instrument_id = self.get_instrument_id(symbol)

                mdata = getattr(self.api, 'mdata', None)
                quotes = getattr(self.api, 'quotes', None)

                def try_call(client, method_name, *args):
                    if client is None or not hasattr(client, method_name):
                        return None
                    return self.call_with_retry(lambda: getattr(client, method_name)(*args), operation_name=f"{client.__class__.__name__}.{method_name}")

                # 構成に基づくメソッド優先度
                prefer = str(self._get_md_setting('prefer', 'auto')).lower()  # auto|mdata|quotes|yfinance
                use_instrument = bool(self._get_md_setting('use_instrument_id', True)) and bool(instrument_id)
                log_attempts = bool(self._get_md_setting('log_attempts', True))

                method_plan_default = [
                    ('mdata', 'get_last_price', 'symbol'),
                    ('mdata', 'get_snapshot', 'symbol'),
                    ('quotes', 'get_last_price', 'symbol'),
                    ('quotes', 'get_snapshot', 'symbol'),
                ]
                if use_instrument:
                    method_plan_default += [
                        ('mdata', 'get_last_price_by_instrument', 'instrument'),
                        ('mdata', 'get_snapshot_by_instrument', 'instrument'),
                        ('quotes', 'get_last_price_by_instrument', 'instrument'),
                        ('quotes', 'get_snapshot_by_instrument', 'instrument'),
                    ]

                # preferで並び替え
                def score(item):
                    api_kind = item[0]
                    if prefer == 'mdata':
                        return 0 if api_kind == 'mdata' else 1
                    if prefer == 'quotes':
                        return 0 if api_kind == 'quotes' else 1
                    return 0

                method_plan = sorted(method_plan_default, key=score)

                for api_kind, method_name, arg_kind in method_plan:
                    client = mdata if api_kind == 'mdata' else quotes
                    arg = symbol if arg_kind == 'symbol' else instrument_id
                    if log_attempts:
                        self.logger.info(f"価格取得試行: {api_kind}.{method_name}({arg})")
                    res = try_call(client, method_name, arg) if arg is not None else None
                    if res is None:
                        continue
                    status = getattr(res, 'status_code', None)
                    if log_attempts:
                        body_preview = ''
                        try:
                            body_preview = getattr(res, 'text', '')
                            if body_preview and len(body_preview) > 300:
                                body_preview = body_preview[:300] + '...'
                        except Exception:
                            body_preview = '[no-text]'
                        self.logger.info(f"価格取得応答: method={api_kind}.{method_name} status={status} body={body_preview}")
                    if status == 200:
                        price = self._extract_price_from_response(res)
                        if price and price > 0:
                            self._cache_price(symbol, price)
                            self._last_price_method_by_symbol[symbol] = f"{api_kind}.{method_name}"
                            return price
            except Exception as e:
                self.logger.warning(f"MDATA価格取得失敗 ({symbol}): {e}")

            # フォールバック: yfinance
            try:
                ticker = yf.Ticker(symbol)
                price = ticker.info.get('regularMarketPrice', 0)
                if price and price > 0:
                    self._cache_price(symbol, price)
                    self._last_price_method_by_symbol[symbol] = 'yfinance'
                    return price
            except Exception as e:
                self.logger.warning(f"yfinance価格取得失敗 ({symbol}): {e}")

            self.logger.warning(f"{symbol} の価格取得に失敗")
            return 0
        except Exception as e:
            self.logger.error(f"価格取得エラー ({symbol}): {e}")
            return 0

    def _extract_price_from_response(self, response) -> float:
        """HTTPレスポンスから価格フィールドを堅牢に抽出"""
        try:
            data = response.json()
        except Exception:
            return 0.0

        def pick(d: dict):
            for k in (
                'last_price', 'last', 'price', 'p', 'regular_price', 'regularMarketPrice',
                'latestPrice', 'close', 'trade_price'
            ):  # SDK/エンドポイント差異を吸収
                v = d.get(k)
                try:
                    if v is not None:
                        fv = float(v)
                        if fv > 0:
                            return fv
                except Exception:
                    continue
            # ネストした構造の一般例
            for nested_key in ('quote', 'snapshot', 'last_trade'):
                obj = d.get(nested_key)
                if isinstance(obj, dict):
                    val = pick(obj)
                    if val and val > 0:
                        return val
            return 0.0

        if isinstance(data, dict):
            return pick(data)
        if isinstance(data, list) and data:
            if isinstance(data[0], dict):
                return pick(data[0])
        return 0.0

    def get_instrument_id(self, symbol):
        """instrument_idを取得（サンプルコード完全準拠）"""
        try:
            # キャッシュをチェック
            if symbol in self._instrument_id_cache:
                return self._instrument_id_cache[symbol]
            
            # まずETFカテゴリで照会し、見つからなければUS_STOCKも試す
            response = self.call_with_retry(
                lambda: self.api.instrument.get_instrument(symbol, "US_ETF"),
                operation_name="get_instrument_us_etf"
            )
            if response is None or response.status_code != 200 or not response.text or response.text in ('[]', '{}'):
                response = self.call_with_retry(
                    lambda: self.api.instrument.get_instrument(symbol, "US_STOCK"),
                    operation_name="get_instrument_us_stock"
                )
            
            if response.status_code == 200:
                data = response.json()
                self.logger.info(f"instrument_id取得レスポンス: {data}")
                
                # サンプルコードと同じ処理: for d in data:
                if isinstance(data, list):
                    for d in data:
                        symbol_from_response = d.get('symbol')
                        instrument_id = d.get('instrument_id')
                        if symbol_from_response == symbol and instrument_id:
                            self.logger.info(f"symbol: {symbol_from_response}")
                            self.logger.info(f"instrument_id: {instrument_id}")
                            self._cache_instrument_id(symbol, instrument_id)
                            return instrument_id
                elif isinstance(data, dict):
                    # 単一オブジェクトの場合
                    symbol_from_response = data.get('symbol')
                    instrument_id = data.get('instrument_id')
                    if symbol_from_response == symbol and instrument_id:
                        self.logger.info(f"symbol: {symbol_from_response}")
                        self.logger.info(f"instrument_id: {instrument_id}")
                        self._cache_instrument_id(symbol, instrument_id)
                        return instrument_id
            
            self.logger.warning(f"{symbol} のinstrument_id取得に失敗")
            return None
        except Exception as e:
            self.logger.error(f"instrument_id取得エラー ({symbol}): {e}")
            return None

    def _cache_price(self, symbol, price):
        """価格をキャッシュ"""
        self._price_cache[symbol] = (time.time(), price)

    def _cache_instrument_id(self, symbol, instrument_id):
        """instrument_idをキャッシュ"""
        self._instrument_id_cache[symbol] = instrument_id

    # ==================== 買い付け機能 ====================
    
    def buy_stock(self, symbol, quantity, limit_price=None):
        """株式を購入（サンプルコード準拠）"""
        try:
            if self.dry_run:
                self.logger.info(f"DRY RUN - BUY {quantity} shares of {symbol}")
                return True
            
            # 買付余力チェック
            balance = self.get_account_balance()
            if balance and 'USD' in balance:
                available_cash = balance['USD']['available_cash']
                estimated_cost = quantity * (limit_price or self.get_stock_price(symbol) * 1.005)
                if estimated_cost > available_cash * 0.95:  # 95%の安全マージン
                    self.logger.warning(f"買付余力不足: 必要額 ${estimated_cost:.2f}, 利用可能額 ${available_cash:.2f}")
                    # 数量を調整
                    adjusted_quantity = int((available_cash * 0.95) / (limit_price or self.get_stock_price(symbol) * 1.005))
                    if adjusted_quantity < quantity:
                        self.logger.info(f"数量調整: {quantity} → {adjusted_quantity}株")
                        quantity = adjusted_quantity
                        if quantity <= 0:
                            self.logger.error("調整後の数量が0以下です")
                            return False
            
            # 現在価格を取得
            current_price = self.get_stock_price(symbol)
            if current_price <= 0:
                self.logger.error(f"{symbol} の価格取得に失敗")
                return False
            
            # 銘柄タイプ判定（ETF/EQUITY）
            # v2ではETFでもEQUITY指定で通るケースが多いため統一
            instrument_type = "EQUITY"

            # 指値価格を設定
            if not limit_price:
                limit_price = current_price * 1.005  # 0.5%高め（より保守的）

            # --- v2 公式仕様に準拠した注文パラメータを作成 -----------------------
            order_body = {
                "client_order_id": uuid.uuid4().hex,
                "symbol": symbol,
                "instrument_type": instrument_type,
                "market": "US",
                "side": "BUY",
                "order_type": "LIMIT",
                "qty": str(int(quantity)),
                "limit_price": f"{limit_price:.2f}",
                "support_trading_session": "N",
                "time_in_force": "DAY",
                "entrust_type": "QTY",
                "account_tax_type": "SPECIFIC"
            }

            # 417対策: instrument_idを併記（必要な可能性に対応）
            instrument_id = self.get_instrument_id(symbol)
            if instrument_id:
                order_body["instrument_id"] = str(instrument_id)
            
            # --- Preview ----------------------------------------------------------
            preview = self.call_with_retry(
                lambda: self.api.order_v2.preview_order(self.account_id, order_body),
                operation_name="preview_order"
            )
            self.logger.info(f"Preview: {preview.status_code} {preview.text}")
            if preview.status_code != 200:
                # 追加のエラーハンドリング: JSON本文からエラー詳細を抽出
                try:
                    detail = preview.json()
                    self.logger.error(f"Preview失敗。詳細: {detail}")
                except Exception:
                    self.logger.error("Preview失敗。詳細は不明")
                return False

            self.logger.info(f"購入注文発注: {symbol} {quantity}株 @ ${limit_price:.2f}")

            response = self.call_with_retry(
                lambda: self.api.order_v2.place_order(self.account_id, order_body),
                operation_name="place_order"
            )
            
            self.logger.info(f"place_order_result: {response.json()}")
            
            if response is not None and response.status_code == 200:
                order_data = response.json()
                self.logger.info(f"✅ 購入注文成功")
                
                # レスポンス形式の確認と処理
                if 'client_order_id' in order_data:
                    client_order_id = order_data['client_order_id']
                    self.logger.info(f"注文ID: {client_order_id}")
                    return True
                elif 'data' in order_data and 'client_order_id' in order_data['data']:
                    client_order_id = order_data['data']['client_order_id']
                    self.logger.info(f"注文ID: {client_order_id}")
                    return True
                else:
                    self.logger.warning("レスポンスにclient_order_idが含まれていませんが、注文は成功しています")
                    return True
            else:
                # 追加のエラーハンドリング
                if response is None:
                    self.logger.error("❌ 購入注文失敗: 応答なし（タイムアウト/例外）")
                else:
                    try:
                        self.logger.error(f"❌ 購入注文失敗: {response.status_code} {response.json()}")
                    except Exception:
                        self.logger.error(f"❌ 購入注文失敗: {getattr(response, 'status_code', 'N/A')} {getattr(response, 'text', '')}")
                return False
                
        except Exception as e:
            self.logger.error(f"購入エラー ({symbol}): {e}")
            return False

    # ==================== 売り付け機能 ====================
    
    def sell_stock(self, symbol, quantity, limit_price=None):
        """株式を売却（成功コード準拠）"""
        try:
            if self.dry_run:
                self.logger.info(f"DRY RUN - SELL {quantity} shares of {symbol}")
                return True
            
            # 銘柄タイプ判定（ETF/EQUITY）
            instrument_type = "EQUITY"

            # 成功しているコードに完全準拠した注文パラメータを作成
            order = {
                "client_order_id": uuid.uuid4().hex,
                "symbol": symbol,
                "instrument_type": instrument_type,
                "market": "US",
                "side": "SELL",
                "order_type": "MARKET",
                "qty": str(int(quantity)),
                "support_trading_session": "N",          # Extended 無し
                "time_in_force": "DAY",
                "entrust_type": "QTY",
                "account_tax_type": "SPECIFIC"           # Cash 口座推奨値
            }

            # 417対策: instrument_idを併記
            instrument_id = self.get_instrument_id(symbol)
            if instrument_id:
                order["instrument_id"] = str(instrument_id)
            
            self.logger.info(f"売却注文発注: {symbol} {quantity}株")
            
            # サンプルコードと同じ形式でプレビュー実行
            try:
                preview_response = self.call_with_retry(
                    lambda: self.api.order_v2.preview_order(self.account_id, order),
                    operation_name="preview_order"
                )
                try:
                    self.logger.info(f"Preview OK: {preview_response.status_code} {preview_response.json()}")
                except Exception:
                    self.logger.info(f"Preview OK: {getattr(preview_response, 'status_code', 'N/A')} {getattr(preview_response, 'text', '')}")
            except Exception as e:
                self.logger.warning(f"⚠️ 売却プレビューエラー: {e}")
            
            # サンプルコードと同じ形式でプレース実行
            response = self.call_with_retry(
                lambda: self.api.order_v2.place_order(self.account_id, order),
                operation_name="place_order"
            )
            
            try:
                self.logger.info(f"Place: {response.status_code} {response.text}")
            except Exception:
                self.logger.info(f"Place: {getattr(response, 'status_code', 'N/A')} {getattr(response, 'text', '')}")
            
            if response is not None and response.status_code == 200:
                self.logger.info(f"✅ 売却注文成功")
                return True
            else:
                if response is None:
                    self.logger.error("❌ 売却注文失敗: 応答なし（タイムアウト/例外）")
                else:
                    try:
                        self.logger.error(f"❌ 売却注文失敗: {response.status_code} {response.json()}")
                    except Exception:
                        self.logger.error(f"❌ 売却注文失敗: {getattr(response, 'status_code', 'N/A')} {getattr(response, 'text', '')}")
                return False
                
        except Exception as e:
            self.logger.error(f"売却エラー ({symbol}): {e}")
            return False

    def sell_all_positions(self):
        """全ポジションを売却"""
        try:
            positions = self.get_current_positions()
            if not positions:
                self.logger.info("売却するポジションがありません")
                return True
            
            self.logger.info(f"全ポジション売却開始: {len(positions)}件")
            
            success_count = 0
            for position in positions:
                symbol = position['symbol']
                quantity = position['quantity']
                
                self.logger.info(f"売却中: {symbol} {quantity}株")
                if self.sell_stock(symbol, quantity):
                    success_count += 1
                else:
                    self.logger.error(f"{symbol} の売却に失敗")
            
            self.logger.info(f"売却完了: {success_count}/{len(positions)} 成功")
            return success_count == len(positions)
            
        except Exception as e:
            self.logger.error(f"全ポジション売却エラー: {e}")
            return False

    # ==================== リバランシング機能 ====================
    
    def calculate_rebalancing_trades(self, current_positions, target_allocation, available_cash):
        """リバランシングに必要な取引を計算"""
        try:
            trades = []
            
            # 現在の総資産価値を計算
            total_value = available_cash
            current_allocation = {}
            
            for position in current_positions:
                symbol = position['symbol']
                quantity = position['quantity']
                price = self.get_stock_price(symbol)
                value = quantity * price
                total_value += value
                current_allocation[symbol] = value
            
            # 目標配分を金額に変換
            target_values = {}
            for symbol, percentage in target_allocation.items():
                target_values[symbol] = total_value * (percentage / 100)
            
            # 売却取引を計算
            for symbol, current_value in current_allocation.items():
                if symbol in target_values:
                    target_value = target_values[symbol]
                    if current_value > target_value:
                        # 売却が必要
                        sell_value = current_value - target_value
                        price = self.get_stock_price(symbol)
                        if price > 0:
                            sell_quantity = int(sell_value / price)
                            if sell_quantity > 0:
                                trades.append({
                                    'symbol': symbol,
                                    'action': 'SELL',
                                    'quantity': sell_quantity,
                                    'estimated_value': sell_value
                                })
            
            # 購入取引を計算
            remaining_cash = available_cash
            for symbol, target_value in target_values.items():
                current_value = current_allocation.get(symbol, 0)
                if target_value > current_value:
                    # 購入が必要
                    buy_value = target_value - current_value
                    if buy_value <= remaining_cash:
                        price = self.get_stock_price(symbol)
                        if price > 0:
                            # 安全マージン（95%）を適用
                            safe_buy_value = buy_value * 0.95
                            buy_quantity = int(safe_buy_value / price)
                            if buy_quantity > 0:
                                trades.append({
                                    'symbol': symbol,
                                    'action': 'BUY',
                                    'quantity': buy_quantity,
                                    'estimated_value': buy_value
                                })
                                remaining_cash -= buy_value
            
            return trades
            
        except Exception as e:
            self.logger.error(f"リバランシング取引計算エラー: {e}")
            return []

    def execute_rebalancing(self):
        """リバランシングを実行"""
        try:
            self.logger.info("=== リバランシング開始 ===")
            
            # 現在の状況を取得
            balance = self.get_account_balance()
            if not balance or 'USD' not in balance:
                self.logger.error("残高取得に失敗")
                return False
            
            available_cash = balance['USD']['available_cash']
            positions = self.get_current_positions()
            
            self.logger.info(f"利用可能現金: ${available_cash:.2f}")
            self.logger.info(f"現在のポジション数: {len(positions)}")
            
            # リバランシング取引を計算
            trades = self.calculate_rebalancing_trades(positions, self.target_allocation, available_cash)
            
            if not trades:
                self.logger.info("リバランシングに必要な取引はありません")
                return True
            
            self.logger.info(f"実行予定取引数: {len(trades)}")
            
            # 取引を実行
            success_count = 0
            for trade in trades:
                symbol = trade['symbol']
                action = trade['action']
                quantity = trade['quantity']
                
                self.logger.info(f"取引実行: {action} {quantity} shares of {symbol}")
                
                if action == 'BUY':
                    if self.buy_stock(symbol, quantity):
                        success_count += 1
                elif action == 'SELL':
                    if self.sell_stock(symbol, quantity):
                        success_count += 1
            
            self.logger.info(f"リバランシング完了: {success_count}/{len(trades)} 成功")
            return success_count == len(trades)
            
        except Exception as e:
            self.logger.error(f"リバランシングエラー: {e}")
            return False

    # ==================== 情報表示機能 ====================
    
    def show_account_info(self):
        """アカウント情報を表示"""
        try:
            print("=== アカウント情報 ===")
            print(f"Account ID: {self.account_id}")
            print(f"Dry Run Mode: {self.dry_run}")
            
            # 残高情報
            balance = self.get_account_balance()
            if balance and 'USD' in balance:
                usd_balance = balance['USD']
                print(f"\n--- USD残高 ---")
                print(f"利用可能現金: ${usd_balance['available_cash']:.2f}")
                print(f"買付余力: ${usd_balance['buying_power']:.2f}")
                print(f"総現金: ${usd_balance['cash_balance']:.2f}")
            
            # ポジション情報
            positions = self.get_current_positions()
            if positions:
                print(f"\n--- 現在のポジション ---")
                total_value = 0
                for position in positions:
                    symbol = position['symbol']
                    quantity = position['quantity']
                    price = self.get_stock_price(symbol)
                    value = quantity * price
                    total_value += value
                    print(f"{symbol}: {quantity}株 × ${price:.2f} = ${value:.2f}")
                print(f"総ポジション価値: ${total_value:.2f}")
            else:
                print(f"\n--- 現在のポジション ---")
                print("ポジションなし")
            
            # 目標ポートフォリオ
            print(f"\n--- 目標ポートフォリオ ---")
            for symbol, percentage in self.target_allocation.items():
                print(f"{symbol}: {percentage}%")
            
        except Exception as e:
            self.logger.error(f"アカウント情報表示エラー: {e}")

    def show_investment_analysis(self):
        """投資分析を表示"""
        try:
            print("=== 投資分析 ===")
            
            balance = self.get_account_balance()
            if not balance or 'USD' not in balance:
                print("残高取得に失敗")
                return
            
            available_cash = balance['USD']['available_cash']
            positions = self.get_current_positions()
            
            # 現在の総資産価値
            total_position_value = sum([pos['quantity'] * self.get_stock_price(pos['symbol']) for pos in positions])
            total_portfolio_value = total_position_value + available_cash
            
            print(f"総ポートフォリオ価値: ${total_portfolio_value:.2f}")
            print(f"利用可能現金: ${available_cash:.2f}")
            print(f"ポジション価値: ${total_position_value:.2f}")
            
            # 目標投資額を計算
            print(f"\n--- 目標投資額 ---")
            for symbol, percentage in self.target_allocation.items():
                target_amount = total_portfolio_value * (percentage / 100)
                current_price = self.get_stock_price(symbol)
                if current_price > 0:
                    target_shares = target_amount / current_price
                    print(f"{symbol}: ${target_amount:.2f} ({target_shares:.2f}株 @ ${current_price:.2f})")
            
            # リバランシング分析
            trades = self.calculate_rebalancing_trades(positions, self.target_allocation, available_cash)
            if trades:
                print(f"\n--- リバランシング分析 ---")
                print(f"必要な取引数: {len(trades)}")
                
                buy_trades = [t for t in trades if t['action'] == 'BUY']
                sell_trades = [t for t in trades if t['action'] == 'SELL']
                
                if buy_trades:
                    print(f"購入取引: {len(buy_trades)}件")
                    total_buy = sum([t['estimated_value'] for t in buy_trades])
                    print(f"総購入金額: ${total_buy:.2f}")
                
                if sell_trades:
                    print(f"売却取引: {len(sell_trades)}件")
                    total_sell = sum([t['estimated_value'] for t in sell_trades])
                    print(f"総売却金額: ${total_sell:.2f}")
            else:
                print(f"\n--- リバランシング分析 ---")
                print("リバランシングに必要な取引はありません")
                
        except Exception as e:
            self.logger.error(f"投資分析表示エラー: {e}")

# ==================== メイン実行関数 ====================

def main():
    """メイン実行関数（設定ファイルのdry_run設定を尊重）"""
    print("=== 統合版ポートフォリオリバランサー ===")
    
    # リバランサーを初期化（設定ファイルのdry_run設定を尊重）
    bot = WebullBotUnified()
    
    print(f"Account ID: {bot.account_id}")
    print(f"Dry Run Mode: {bot.dry_run}")
    
    # アカウント情報を表示
    print("\n=== アカウント情報 ===")
    bot.show_account_info()
    
    # 投資分析を表示
    print("\n=== 投資分析 ===")
    bot.show_investment_analysis()
    
    # リバランシングを実行
    print(f"\n=== リバランシング実行 ===")
    success = bot.execute_rebalancing()
    
    if success:
        print("✅ リバランシング完了")
    else:
        print("❌ リバランシング失敗")
    
    print("\n=== 運用完了 ===")

if __name__ == "__main__":
    main() 
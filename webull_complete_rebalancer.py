#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import pandas as pd
import numpy as np
import yfinance as yf
import time
import uuid
import os
import sys
from datetime import datetime, timedelta
from webullsdktrade.api import API
from webullsdkcore.client import ApiClient
from webullsdkcore.common.region import Region

# ログ設定の改善
def setup_logging():
    """構造化されたログ設定"""
    # ログディレクトリの作成
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # ログファイル名に日付を含める
    log_filename = f"{log_dir}/webull_rebalancer_{datetime.now().strftime('%Y%m%d')}.log"
    
    # ログフォーマットの改善
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    
    # ログレベルの設定
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    # 特定のライブラリのログレベルを調整
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('webullsdkcore').setLevel(logging.WARNING)

# ログ設定を実行
setup_logging()

class WebullCompleteRebalancer:
    def __init__(self, config_file='webull_config_with_allocation.json', dry_run=None):
        """完全なポートフォリオリバランサーの初期化"""
        self.logger = logging.getLogger(__name__)
        self.config = self.load_config(config_file)
        
        # dry_runの設定（引数で上書き可能）
        if dry_run is not None:
            self.config['dry_run'] = dry_run
        
        self.api = self.initialize_api()
        self.account_id = self.config.get('account_id')
        self.dry_run = self.config.get('dry_run', True)
        
        # キャッシュの初期化
        self._price_cache = {}
        self._instrument_id_cache = {}
        self._last_api_call = {}  # API呼び出し制限用
        
        # 設定の検証
        self.validate_config()
        
        self.logger.info(f"WebullCompleteRebalancer初期化完了")
        self.logger.info(f"Account ID: {self.account_id}")
        self.logger.info(f"Dry Run Mode: {self.dry_run}")
    
    def validate_config(self):
        """設定の検証"""
        required_fields = ['app_key', 'app_secret', 'account_id']
        missing_fields = [field for field in required_fields if not self.config.get(field)]
        
        if missing_fields:
            raise ValueError(f"必須設定が不足しています: {missing_fields}")
        
        if not self.config.get('target_allocation'):
            raise ValueError("target_allocationが設定されていません")
        
        # 配分の合計を確認
        total_allocation = sum(self.config['target_allocation'].values())
        if abs(total_allocation - 100) > 1:  # 1%の誤差を許容
            self.logger.warning(f"配分の合計が100%ではありません: {total_allocation}%")
    
    def load_config(self, config_file):
        """設定ファイルを読み込み"""
        try:
            if not os.path.exists(config_file):
                raise FileNotFoundError(f"設定ファイルが見つかりません: {config_file}")
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.logger.info("設定ファイル読み込み成功")
            
            # 外部ポートフォリオ設定ファイルを読み込み
            portfolio_config_file = config.get('portfolio_config_file', 'portfolio.csv')
            if os.path.exists(portfolio_config_file):
                portfolio_config = self.load_portfolio_config(portfolio_config_file)
                # 設定を統合
                config.update(portfolio_config)
            
            return config
        except Exception as e:
            self.logger.error(f"設定ファイル読み込みエラー: {e}")
            raise
    
    def load_portfolio_config(self, portfolio_config_file):
        """外部ポートフォリオ設定ファイルを読み込み（JSONまたはCSV対応）"""
        try:
            if portfolio_config_file.endswith('.csv'):
                return self.load_portfolio_config_csv(portfolio_config_file)
            else:
                return self.load_portfolio_config_json(portfolio_config_file)
        except Exception as e:
            self.logger.error(f"ポートフォリオ設定ファイル読み込みエラー: {e}")
            raise
    
    def load_portfolio_config_csv(self, portfolio_config_file):
        """CSVポートフォリオ設定ファイルを読み込み"""
        try:
            df = pd.read_csv(portfolio_config_file, encoding='utf-8')
            
            # 必須カラムの確認
            required_columns = ['symbol', 'allocation_percentage']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"必須カラムが不足しています: {missing_columns}")
            
            # データの検証
            if df.empty:
                raise ValueError("CSVファイルが空です")
            
            # 配分の合計を確認
            total_allocation = df['allocation_percentage'].sum()
            if abs(total_allocation - 100) > 0.01:  # 小数点の誤差を許容
                self.logger.warning(f"配分の合計が100%ではありません: {total_allocation}%")
            
            # ポートフォリオ設定を構築
            portfolio_config = {
                'portfolio_name': f"CSV Portfolio ({portfolio_config_file})",
                'description': f"CSVファイルから読み込まれたポートフォリオ設定",
                'target_allocation': {}
            }
            
            # 各銘柄の配分を設定
            for _, row in df.iterrows():
                symbol = row['symbol'].strip().upper()
                allocation = float(row['allocation_percentage'])
                description = row.get('description', '') if 'description' in df.columns else ''
                
                portfolio_config['target_allocation'][symbol] = allocation
                
                self.logger.info(f"銘柄: {symbol} ({description}) - 配分: {allocation}%")
            
            self.logger.info(f"CSVポートフォリオ設定ファイル読み込み成功: {portfolio_config_file}")
            self.logger.info(f"ポートフォリオ名: {portfolio_config['portfolio_name']}")
            self.logger.info(f"総銘柄数: {len(portfolio_config['target_allocation'])}")
            self.logger.info(f"配分合計: {total_allocation}%")
            
            return portfolio_config
            
        except Exception as e:
            self.logger.error(f"CSVポートフォリオ設定ファイル読み込みエラー: {e}")
            raise
    
    def load_portfolio_config_json(self, portfolio_config_file):
        """JSONポートフォリオ設定ファイルを読み込み"""
        try:
            with open(portfolio_config_file, 'r', encoding='utf-8') as f:
                portfolio_config = json.load(f)
            
            self.logger.info(f"JSONポートフォリオ設定ファイル読み込み成功: {portfolio_config_file}")
            self.logger.info(f"ポートフォリオ名: {portfolio_config.get('portfolio_name', 'N/A')}")
            self.logger.info(f"説明: {portfolio_config.get('description', 'N/A')}")
            
            return portfolio_config
        except Exception as e:
            self.logger.error(f"JSONポートフォリオ設定ファイル読み込みエラー: {e}")
            raise
    
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
    
    def rate_limit_check(self, api_name):
        """API呼び出し制限チェック"""
        now = datetime.now()
        if api_name in self._last_api_call:
            last_call = self._last_api_call[api_name]
            time_diff = (now - last_call).total_seconds()
            
            # 1秒間隔を強制
            if time_diff < 1:
                sleep_time = 1 - time_diff
                self.logger.debug(f"API制限のため {sleep_time:.2f}秒待機: {api_name}")
                time.sleep(sleep_time)
        
        self._last_api_call[api_name] = now
    
    def api_call_with_retry(self, api_func, max_retries=3, delay=1, api_name="unknown"):
        """API呼び出しにリトライ機能を追加（改善版）"""
        for attempt in range(max_retries):
            try:
                # レート制限チェック
                self.rate_limit_check(api_name)
                
                response = api_func()
                
                # 成功した場合
                if response.status_code == 200:
                    return response
                
                # レート制限エラーの場合
                if response.status_code == 429:
                    wait_time = delay * (2 ** attempt)  # 指数バックオフ
                    self.logger.warning(f"レート制限エラー (429)。{wait_time}秒待機してリトライ...")
                    time.sleep(wait_time)
                    continue
                
                # その他のエラー
                self.logger.error(f"API呼び出し失敗 (試行 {attempt + 1}/{max_retries}): {response.status_code} - {response.text}")
                if attempt == max_retries - 1:
                    return response
                
                time.sleep(delay)
                
            except Exception as e:
                self.logger.error(f"API呼び出しエラー (試行 {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(delay)
        
        return None
    
    def get_account_balance(self):
        """口座残高を取得（リトライ機能付き）- Account Balance（v2）API使用 + 安全マージン"""
        try:
            def api_call():
                return self.api.account_v2.get_account_balance(self.account_id)
            
            response = self.api_call_with_retry(api_call, max_retries=2, api_name="get_account_balance")
            
            if response and response.status_code == 200:
                balance_data = json.loads(response.text)
                self.logger.info("口座残高取得成功（v2 API）")
                
                # レスポンス構造をデバッグ
                self.logger.info(f"APIレスポンス構造: {json.dumps(balance_data, indent=2)}")
                
                # 通貨別の残高を解析（v2 API形式）
                balances = {}
                
                # 複数のレスポンス構造に対応
                if 'data' in balance_data:
                    data = balance_data['data']
                    if isinstance(data, dict):
                        # 通貨別データが直接含まれている場合
                        for currency, currency_data in data.items():
                            if isinstance(currency_data, dict):
                                cash_balance = float(currency_data.get('cash_balance', 0))
                                buying_power = float(currency_data.get('buying_power', 0))
                                unrealized_profit_loss = float(currency_data.get('unrealized_profit_loss', 0))
                                
                                # 安全マージンOFF - 元の買付余力をそのまま使用
                                safety_margin = 0.0  # 0% (安全マージンOFF)
                                adjusted_buying_power = buying_power  # 安全マージンなし
                                
                                balances[currency] = {
                                    'cash_balance': cash_balance,
                                    'buying_power': buying_power,
                                    'unrealized_profit_loss': unrealized_profit_loss,
                                    'available_cash': adjusted_buying_power,  # 安全マージンなし
                                    'original_buying_power': buying_power,  # 元の買付余力
                                    'safety_margin_applied': safety_margin  # 適用された安全マージン
                                }
                    elif isinstance(data, list):
                        # 配列形式の場合
                        for currency_asset in data:
                            currency = currency_asset.get('currency')
                            cash_balance = float(currency_asset.get('cash_balance', 0))
                            buying_power = float(currency_asset.get('buying_power', 0))
                            unrealized_profit_loss = float(currency_asset.get('unrealized_profit_loss', 0))
                            
                            # 安全マージンOFF - 元の買付余力をそのまま使用
                            safety_margin = 0.0  # 0% (安全マージンOFF)
                            adjusted_buying_power = buying_power  # 安全マージンなし
                            
                            balances[currency] = {
                                'cash_balance': cash_balance,
                                'buying_power': buying_power,
                                'unrealized_profit_loss': unrealized_profit_loss,
                                'available_cash': adjusted_buying_power,  # 安全マージンなし
                                'original_buying_power': buying_power,  # 元の買付余力
                                'safety_margin_applied': safety_margin  # 適用された安全マージン
                            }
                else:
                    # 従来の構造に対応
                    account_currency_assets = balance_data.get('account_currency_assets', [])
                    for currency_asset in account_currency_assets:
                        currency = currency_asset.get('currency')
                        cash_balance = float(currency_asset.get('cash_balance', 0))
                        buying_power = float(currency_asset.get('buying_power', 0))
                        unrealized_profit_loss = float(currency_asset.get('unrealized_profit_loss', 0))
                        
                        # 安全マージンOFF - 元の買付余力をそのまま使用
                        safety_margin = 0.0  # 0% (安全マージンOFF)
                        adjusted_buying_power = buying_power  # 安全マージンなし
                        
                        balances[currency] = {
                            'cash_balance': cash_balance,
                            'buying_power': buying_power,
                            'unrealized_profit_loss': unrealized_profit_loss,
                            'available_cash': adjusted_buying_power,  # 安全マージンなし
                            'original_buying_power': buying_power,  # 元の買付余力
                            'safety_margin_applied': safety_margin  # 適用された安全マージン
                        }
                
                self.logger.info(f"口座残高詳細: {balances}")
                return balances
            else:
                self.logger.error(f"口座残高取得失敗: {response.status_code if response else 'No response'}")
                return None
                
        except Exception as e:
            self.logger.error(f"口座残高取得中にエラー発生: {e}")
            return None
    
    def get_current_positions(self):
        """現在のポジションを取得（リトライ機能付き）- Account Positions（v2）API使用"""
        try:
            def api_call():
                return self.api.account_v2.get_account_position(self.account_id)
            
            response = self.api_call_with_retry(api_call, max_retries=2, api_name="get_account_position")
            
            if response and response.status_code == 200:
                position_data = json.loads(response.text)
                self.logger.info(f"ポジション取得成功（v2 API）")
                
                # レスポンス構造をデバッグ
                self.logger.info(f"APIレスポンス構造: {json.dumps(position_data, indent=2)}")
                
                positions = []
                
                # レスポンスがリストの場合（空のポジション）
                if isinstance(position_data, list):
                    self.logger.info("ポジションなし（空のリスト）")
                    return positions
                
                # v2 APIのレスポンス構造に対応
                if 'data' in position_data:
                    data = position_data['data']
                    if isinstance(data, list):
                        # 配列形式の場合
                        for position in data:
                            items = position.get('items', [])
                            for item in items:
                                symbol = item.get('symbol')
                                quantity = float(item.get('quantity', 0))
                                available_quantity = float(item.get('available_quantity', 0))
                                cost_price = float(item.get('cost_price', 0))
                                unrealized_profit_loss = float(item.get('unrealized_profit_loss', 0))
                                
                                if symbol and quantity > 0:
                                    positions.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'available_quantity': available_quantity,
                                        'cost_price': cost_price,
                                        'unrealized_profit_loss': unrealized_profit_loss,
                                        'market_value': quantity * cost_price + unrealized_profit_loss
                                    })
                    elif isinstance(data, dict):
                        # 辞書形式の場合
                        items = data.get('items', [])
                        for item in items:
                            symbol = item.get('symbol')
                            quantity = float(item.get('quantity', 0))
                            available_quantity = float(item.get('available_quantity', 0))
                            cost_price = float(item.get('cost_price', 0))
                            unrealized_profit_loss = float(item.get('unrealized_profit_loss', 0))
                            
                            if symbol and quantity > 0:
                                positions.append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'available_quantity': available_quantity,
                                    'cost_price': cost_price,
                                    'unrealized_profit_loss': unrealized_profit_loss,
                                    'market_value': quantity * cost_price + unrealized_profit_loss
                                })
                else:
                    # 従来の構造に対応
                    holdings = position_data.get('holdings', [])
                    for holding in holdings:
                        symbol = holding.get('ticker', {}).get('symbol')
                        quantity = float(holding.get('quantity', 0))
                        market_value = float(holding.get('market_value', 0))
                        instrument_id = holding.get('instrument_id')
                        
                        if symbol and quantity > 0:
                            positions.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'market_value': market_value,
                                'instrument_id': instrument_id
                            })
                
                self.logger.info(f"有効なポジション: {positions}")
                return positions
            else:
                self.logger.error(f"ポジション取得失敗: {response.text if response else 'No response'}")
                return []
                
        except Exception as e:
            self.logger.error(f"ポジション取得エラー: {e}")
            return []
    
    def get_stock_price(self, symbol):
        """銘柄の現在価格を取得（Webull API使用、キャッシュ機能付き）"""
        try:
            # キャッシュチェック
            if hasattr(self, '_price_cache') and symbol in self._price_cache:
                cached_price = self._price_cache[symbol]
                self.logger.debug(f"✅ キャッシュから {symbol} の価格取得: ${cached_price}")
                return cached_price
            
            self.logger.info(f"{symbol} の価格を取得中...")
            
            # 方法1: リアルタイム価格を取得
            price = self._get_realtime_price(symbol)
            if price and price > 0:
                self._cache_price(symbol, price)
                return price
            
            # 方法2: 現在のポジションから価格を取得
            price = self._get_price_from_positions(symbol)
            if price and price > 0:
                self._cache_price(symbol, price)
                return price
            
            # 方法3: フォールバックとしてyfinanceを使用
            price = self._get_price_from_yfinance(symbol)
            if price and price > 0:
                self._cache_price(symbol, price)
                return price
            
            self.logger.warning(f"{symbol} 価格取得失敗")
            return 0
                
        except Exception as e:
            self.logger.error(f"{symbol} 価格取得エラー: {e}")
            return 0
    
    def _get_realtime_price(self, symbol):
        """Webull APIからリアルタイム価格を取得"""
        try:
            # まずinstrument_idを取得
            instrument_id = self.get_instrument_id(symbol)
            if not instrument_id:
                self.logger.warning(f"{symbol} のinstrument_idが取得できません")
                return None
            
            # 方法1: 現在のポジションから価格を取得（最も確実）
            price = self._get_price_from_positions(symbol)
            if price and price > 0:
                self.logger.info(f"✅ ポジションから {symbol} の価格取得: ${price}")
                return price
            
            # 方法2: Webull APIの正しいエンドポイントを使用
            # 公式ドキュメントに基づいて適切なAPIを呼び出し
            price = self._get_price_from_webull_api(symbol, instrument_id)
            if price and price > 0:
                self.logger.info(f"✅ Webull APIから {symbol} の価格取得: ${price}")
                return price
            
            self.logger.warning(f"{symbol} のWebull API価格取得失敗")
            return None
                
        except Exception as e:
            self.logger.warning(f"リアルタイム価格取得エラー ({symbol}): {e}")
            return None
    
    def _get_price_from_webull_api(self, symbol, instrument_id):
        """Webull APIから価格を取得（公式ドキュメントに基づく）"""
        try:
            # 複数のAPIエンドポイントを試行
            api_methods = [
                # 方法1: スナップショットAPI
                lambda: self._try_snapshot_api(symbol),
                # 方法2: 履歴バーAPI（最新の価格）
                lambda: self._try_history_bar_api(symbol),
                # 方法3: EODバーAPI
                lambda: self._try_eod_bar_api(instrument_id),
            ]
            
            for i, api_method in enumerate(api_methods, 1):
                try:
                    self.logger.debug(f"{symbol} の価格取得方法{i}を試行中...")
                    price = api_method()
                    if price and price > 0:
                        return price
                except Exception as e:
                    self.logger.debug(f"{symbol} の価格取得方法{i}でエラー: {e}")
                    continue
            
            return None
            
        except Exception as e:
            self.logger.error(f"Webull API価格取得エラー ({symbol}): {e}")
            return None
    
    def _try_snapshot_api(self, symbol):
        """スナップショットAPIで価格を取得"""
        try:
            # US_STOCKとUS_ETFの両方を試行
            for category in ["US_STOCK", "US_ETF"]:
                try:
                    def api_call():
                        return self.api.market_data.get_snapshot([symbol], category)
                    
                    response = self.api_call_with_retry(api_call, max_retries=1, delay=0.5, api_name=f"get_snapshot_{category}")
                    
                    if response and response.status_code == 200:
                        data = json.loads(response.text)
                        price = self._extract_price_from_snapshot(data, symbol)
                        if price:
                            return price
                except Exception as e:
                    self.logger.debug(f"スナップショットAPI ({category}) エラー: {e}")
                    continue
            
            return None
            
        except Exception as e:
            self.logger.debug(f"スナップショットAPIエラー: {e}")
            return None
    
    def _try_history_bar_api(self, symbol):
        """履歴バーAPIで価格を取得"""
        try:
            # US_STOCKとUS_ETFの両方を試行
            for category in ["US_STOCK", "US_ETF"]:
                try:
                    def api_call():
                        # 最新の1件を取得
                        return self.api.market_data.get_history_bar(symbol, category, "1d", "1")
                    
                    response = self.api_call_with_retry(api_call, max_retries=1, delay=0.5, api_name=f"get_history_bar_{category}")
                    
                    if response and response.status_code == 200:
                        data = json.loads(response.text)
                        price = self._extract_price_from_history_bar(data)
                        if price:
                            return price
                except Exception as e:
                    self.logger.debug(f"履歴バーAPI ({category}) エラー: {e}")
                    continue
            
            return None
            
        except Exception as e:
            self.logger.debug(f"履歴バーAPIエラー: {e}")
            return None
    
    def _try_eod_bar_api(self, instrument_id):
        """EODバーAPIで価格を取得"""
        try:
            def api_call():
                # 最新の1件を取得
                return self.api.market_data.get_eod_bar([instrument_id], count="1")
            
            response = self.api_call_with_retry(api_call, max_retries=1, delay=0.5, api_name="get_eod_bar")
            
            if response and response.status_code == 200:
                data = json.loads(response.text)
                price = self._extract_price_from_eod_bar(data)
                if price:
                    return price
            
            return None
            
        except Exception as e:
            self.logger.debug(f"EODバーAPIエラー: {e}")
            return None
    
    def _extract_price_from_snapshot(self, data, symbol):
        """スナップショットデータから価格を抽出"""
        try:
            # 複数の価格フィールドを試行
            price_fields = ['last', 'close', 'price', 'current_price', 'market_price']
            
            # データが配列の場合
            if isinstance(data, list):
                for item in data:
                    if item.get('symbol') == symbol:
                        for field in price_fields:
                            if field in item and item[field]:
                                price = float(item[field])
                                if price > 0:
                                    return price
            
            # データがオブジェクトの場合
            elif isinstance(data, dict):
                # dataフィールド内を検索
                if 'data' in data and data['data']:
                    if isinstance(data['data'], list):
                        for item in data['data']:
                            if item.get('symbol') == symbol:
                                for field in price_fields:
                                    if field in item and item[field]:
                                        price = float(item[field])
                                        if price > 0:
                                            return price
                    else:
                        for field in price_fields:
                            if field in data['data'] and data['data'][field]:
                                price = float(data['data'][field])
                                if price > 0:
                                    return price
                
                # 直接検索
                for field in price_fields:
                    if field in data and data[field]:
                        price = float(data[field])
                        if price > 0:
                            return price
            
            return None
            
        except Exception as e:
            self.logger.error(f"スナップショット価格抽出エラー: {e}")
            return None
    
    def _extract_price_from_history_bar(self, data):
        """履歴バーデータから価格を抽出"""
        try:
            # 複数の価格フィールドを試行
            price_fields = ['close', 'last', 'price']
            
            # データが配列の場合
            if isinstance(data, list) and len(data) > 0:
                latest_bar = data[0]  # 最新のバー
                for field in price_fields:
                    if field in latest_bar and latest_bar[field]:
                        price = float(latest_bar[field])
                        if price > 0:
                            return price
            
            # データがオブジェクトの場合
            elif isinstance(data, dict):
                if 'data' in data and data['data']:
                    if isinstance(data['data'], list) and len(data['data']) > 0:
                        latest_bar = data['data'][0]
                        for field in price_fields:
                            if field in latest_bar and latest_bar[field]:
                                price = float(latest_bar[field])
                                if price > 0:
                                    return price
            
            return None
            
        except Exception as e:
            self.logger.error(f"履歴バー価格抽出エラー: {e}")
            return None
    
    def _extract_price_from_eod_bar(self, data):
        """EODバーデータから価格を抽出"""
        try:
            # 複数の価格フィールドを試行
            price_fields = ['close', 'last', 'price']
            
            # データが配列の場合
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    # bars配列を確認
                    if 'bars' in item and isinstance(item['bars'], list) and len(item['bars']) > 0:
                        latest_bar = item['bars'][0]  # 最新のバー
                        for field in price_fields:
                            if field in latest_bar and latest_bar[field]:
                                price = float(latest_bar[field])
                                if price > 0:
                                    return price
            
            # データがオブジェクトの場合
            elif isinstance(data, dict):
                # dataフィールド内を検索
                if 'data' in data and data['data']:
                    if isinstance(data['data'], list) and len(data['data']) > 0:
                        for item in data['data']:
                            if 'bars' in item and isinstance(item['bars'], list) and len(item['bars']) > 0:
                                latest_bar = item['bars'][0]
                                for field in price_fields:
                                    if field in latest_bar and latest_bar[field]:
                                        price = float(latest_bar[field])
                                        if price > 0:
                                            return price
                    else:
                        # dataがオブジェクトの場合
                        if 'bars' in data['data'] and isinstance(data['data']['bars'], list) and len(data['data']['bars']) > 0:
                            latest_bar = data['data']['bars'][0]
                            for field in price_fields:
                                if field in latest_bar and latest_bar[field]:
                                    price = float(latest_bar[field])
                                    if price > 0:
                                        return price
            
            return None
            
        except Exception as e:
            self.logger.error(f"EODバー価格抽出エラー: {e}")
            return None
    
    def _get_price_from_positions(self, symbol):
        """現在のポジションから価格を取得"""
        try:
            positions = self.get_current_positions()
            for position in positions:
                if position.get('symbol') == symbol:
                    quantity = position.get('quantity', 0)
                    market_value = position.get('market_value', 0)
                    if quantity > 0 and market_value > 0:
                        price = market_value / quantity
                        self.logger.info(f"✅ ポジションから {symbol} の価格取得: ${price}")
                        return price
        except Exception as e:
            self.logger.warning(f"ポジションからの価格取得エラー: {e}")
        
        return None
    
    def _get_price_from_yfinance(self, symbol):
        """yfinanceから価格を取得（フォールバック）"""
        try:
            ticker = yf.Ticker(symbol)
            price = ticker.info.get('regularMarketPrice')
            
            if price:
                self.logger.info(f"✅ yfinanceから {symbol} の価格取得: ${price}")
                return price
            else:
                self.logger.warning(f"yfinanceから {symbol} の価格取得失敗")
                return None
                
        except Exception as e:
            self.logger.warning(f"yfinance価格取得エラー ({symbol}): {e}")
            return None
    
    def _cache_price(self, symbol, price):
        """価格をキャッシュに保存"""
        if not hasattr(self, '_price_cache'):
            self._price_cache = {}
        self._price_cache[symbol] = price
        self.logger.debug(f"価格キャッシュに保存: {symbol} -> ${price}")
    
    def clear_price_cache(self):
        """価格キャッシュをクリア"""
        if hasattr(self, '_price_cache'):
            self._price_cache.clear()
            self.logger.info("価格キャッシュをクリアしました")
    
    def get_instrument_id(self, symbol):
        """銘柄のinstrument_idを動的に取得（キャッシュ機能付き）"""
        try:
            # キャッシュチェック
            if hasattr(self, '_instrument_id_cache') and symbol in self._instrument_id_cache:
                cached_id = self._instrument_id_cache[symbol]
                self.logger.info(f"✅ キャッシュから {symbol} のinstrument_id取得: {cached_id}")
                return cached_id
            
            self.logger.info(f"{symbol} のinstrument_idを取得中...")
            
            # 方法1: get_instrument APIで銘柄情報を取得（US_STOCK）
            instrument_id = self._get_instrument_id_from_api(symbol, "US_STOCK")
            if instrument_id:
                self._cache_instrument_id(symbol, instrument_id)
                return instrument_id
            
            # 方法2: get_instrument APIで銘柄情報を取得（US_ETF）
            instrument_id = self._get_instrument_id_from_api(symbol, "US_ETF")
            if instrument_id:
                self._cache_instrument_id(symbol, instrument_id)
                return instrument_id
            
            # 方法3: 現在のポジションから銘柄情報を取得
            instrument_id = self._get_instrument_id_from_positions(symbol)
            if instrument_id:
                self._cache_instrument_id(symbol, instrument_id)
                return instrument_id
            
            # 方法4: フォールバック用のinstrument_idマッピング
            instrument_id = self._get_instrument_id_from_mapping(symbol)
            if instrument_id:
                self._cache_instrument_id(symbol, instrument_id)
                return instrument_id
            
            self.logger.error(f"❌ {symbol} のinstrument_idが見つかりません")
            return None
                
        except Exception as e:
            self.logger.error(f"instrument_id取得エラー ({symbol}): {e}")
            return None
    
    def _get_instrument_id_from_api(self, symbol, category):
        """APIからinstrument_idを取得"""
        try:
            self.logger.info(f"get_instrument APIで {symbol} の情報を取得（{category}）")
            
            def api_call():
                return self.api.instrument.get_instrument(symbol, category)
            
            response = self.api_call_with_retry(api_call, max_retries=2, delay=0.5, api_name=f"get_instrument_{category}")
            
            if response and response.status_code == 200:
                data = json.loads(response.text)
                instrument_id = self._extract_instrument_id_from_response(data, symbol)
                if instrument_id:
                    self.logger.info(f"✅ get_instrument APIから {symbol} のinstrument_id取得: {instrument_id}")
                    return instrument_id
            else:
                self.logger.warning(f"get_instrument API（{category}）エラー: {response.text if response else 'No response'}")
                
        except Exception as e:
            self.logger.warning(f"get_instrument API（{category}）エラー: {e}")
        
        return None
    
    def _extract_instrument_id_from_response(self, data, symbol):
        """APIレスポンスからinstrument_idを抽出"""
        try:
            # レスポンスが配列形式の場合
            if isinstance(data, list) and len(data) > 0:
                for instrument in data:
                    if instrument.get('symbol') == symbol:
                        instrument_id = instrument.get('instrument_id')
                        if instrument_id:
                            return instrument_id
            
            # レスポンスがdataフィールドを持つ場合
            elif 'data' in data and data['data']:
                if isinstance(data['data'], list):
                    for instrument in data['data']:
                        if instrument.get('symbol') == symbol:
                            instrument_id = instrument.get('instrument_id')
                            if instrument_id:
                                return instrument_id
                else:
                    instrument_id = data['data'].get('instrument_id')
                    if instrument_id:
                        return instrument_id
            
            return None
            
        except Exception as e:
            self.logger.error(f"レスポンス解析エラー: {e}")
            return None
    
    def _get_instrument_id_from_positions(self, symbol):
        """現在のポジションからinstrument_idを取得"""
        try:
            self.logger.info(f"現在のポジションから {symbol} の情報を取得")
            positions = self.get_current_positions()
            for position in positions:
                if position.get('symbol') == symbol:
                    instrument_id = position.get('instrument_id')
                    if instrument_id:
                        self.logger.info(f"✅ 現在のポジションから {symbol} のinstrument_id取得: {instrument_id}")
                        return instrument_id
        except Exception as e:
            self.logger.warning(f"ポジション取得エラー: {e}")
        
        return None
    
    def _get_instrument_id_from_mapping(self, symbol):
        """フォールバック用のinstrument_idマッピングから取得"""
        # 確認済みのinstrument_idマッピング
        instrument_id_mapping = {
            'AAPL': '913256135',   # Apple Inc.（確認済み）
            'AAON': '913256136',   # AAON Inc.（確認済み）
            'SPY': '913243251',    # SPDR S&P 500 ETF（確認済み）
            'XLU': '913243088',    # Utilities Select Sector SPDR Fund（確認済み）
            'TQQQ': '913732468',   # ProShares UltraPro QQQ（確認済み）
            'TECL': '913246553',   # Direxion Daily Technology Bull 3X Shares（確認済み）
            'GLD': '913244089',    # SPDR Gold Shares（確認済み）
        }
        
        instrument_id = instrument_id_mapping.get(symbol)
        if instrument_id:
            self.logger.warning(f"⚠️ マッピングから {symbol} のinstrument_id: {instrument_id} (注意: 正しくない可能性があります)")
            return instrument_id
        
        return None
    
    def _cache_instrument_id(self, symbol, instrument_id):
        """instrument_idをキャッシュに保存"""
        if not hasattr(self, '_instrument_id_cache'):
            self._instrument_id_cache = {}
        self._instrument_id_cache[symbol] = instrument_id
        self.logger.debug(f"キャッシュに保存: {symbol} -> {instrument_id}")
    
    def clear_instrument_id_cache(self):
        """instrument_idキャッシュをクリア"""
        if hasattr(self, '_instrument_id_cache'):
            self._instrument_id_cache.clear()
            self.logger.info("instrument_idキャッシュをクリアしました")
    
    def calculate_target_allocation(self, total_value):
        """目標配分を計算"""
        # 設定から目標配分を取得
        target_allocation = self.config.get('target_allocation', {})
        
        if not target_allocation:
            self.logger.warning("目標配分が設定されていません")
            return {}
        
        allocation = {}
        for symbol, percentage in target_allocation.items():
            target_value = total_value * (percentage / 100)
            allocation[symbol] = target_value
        
        self.logger.info(f"目標配分: {allocation}")
        return allocation
    
    def calculate_rebalancing_trades(self, current_positions, target_allocation, available_cash):
        """リバランシング取引を計算"""
        trades = []
        total_value = sum(pos['market_value'] for pos in current_positions) + available_cash
        
        # 現在の配分を計算
        current_allocation = {}
        for pos in current_positions:
            current_allocation[pos['symbol']] = pos['market_value']
        
        # 各銘柄について取引を計算
        for symbol, target_value in target_allocation.items():
            current_value = current_allocation.get(symbol, 0)
            difference = target_value - current_value
            
            if abs(difference) > self.config.get('rebalance_threshold', 0.05) * target_value:
                if difference > 0:
                    # 買い注文
                    price = self.get_stock_price(symbol)
                    if price > 0:
                        quantity = int(difference / price)
                        if quantity > 0:
                            trades.append({
                                'symbol': symbol,
                                'action': 'BUY',
                                'quantity': quantity,
                                'estimated_value': quantity * price
                            })
                else:
                    # 売り注文
                    current_pos = next((p for p in current_positions if p['symbol'] == symbol), None)
                    if current_pos:
                        price = self.get_stock_price(symbol)
                        if price > 0:
                            quantity = int(abs(difference) / price)
                            if quantity > 0 and quantity <= current_pos['quantity']:
                                trades.append({
                                    'symbol': symbol,
                                    'action': 'SELL',
                                    'quantity': quantity,
                                    'estimated_value': quantity * price
                                })
        
        self.logger.info(f"計算された取引: {trades}")
        return trades
    
    def execute_trades(self, trades):
        """取引を実行"""
        if self.dry_run:
            self.logger.info("DRY RUNモード: 実際の取引は実行されません")
            for trade in trades:
                self.logger.info(f"DRY RUN - {trade['action']} {trade['quantity']} shares of {trade['symbol']}")
            return True
        
        # 実際の取引実行
        self.logger.info("実際の取引実行開始")
        success_count = 0
        
        for trade in trades:
            try:
                self.logger.info(f"実際の取引: {trade['action']} {trade['quantity']} shares of {trade['symbol']}")
                
                # レート制限対策：各取引の間に待機
                time.sleep(1)
                
                # instrument_idを取得
                instrument_id = self.get_instrument_id(trade['symbol'])
                if not instrument_id:
                    self.logger.error(f"instrument_id取得失敗: {trade['symbol']}")
                    continue
                
                # 注文を発注
                success = self.place_order(trade, instrument_id)
                if success:
                    success_count += 1
                    self.logger.info(f"注文発注成功: {trade['symbol']}")
                else:
                    self.logger.error(f"注文発注失敗: {trade['symbol']}")
                
            except Exception as e:
                self.logger.error(f"取引実行エラー ({trade['symbol']}): {e}")
        
        self.logger.info(f"取引実行完了: {success_count}/{len(trades)} 成功")
        return success_count == len(trades)
    
    def place_order(self, trade, instrument_id):
        """注文を発注（リトライ機能付き）"""
        try:
            symbol = trade['symbol']
            action = trade['action']
            quantity = trade['quantity']
            
            # instrument_idの確認
            if not instrument_id:
                self.logger.error(f"❌ {symbol} のinstrument_idが取得できませんでした。注文をスキップします。")
                return False
            
            self.logger.info(f"注文発注: {action} {quantity} shares of {symbol} (instrument_id: {instrument_id})")
            
            # 現在価格を取得して指値注文の価格を設定
            current_price = self.get_stock_price(symbol)
            if current_price <= 0:
                self.logger.error(f"価格取得失敗: {symbol}")
                return False
            
            # 指値注文の価格を設定（現在価格の±1%以内）
            if action == 'BUY':
                limit_price = current_price * 1.01  # 買い注文は少し高め
            else:
                limit_price = current_price * 0.99  # 売り注文は少し安め
            
            # 注文パラメータを構築（v2 API仕様）
            client_order_id = uuid.uuid4().hex
            new_orders = {
                "client_order_id": client_order_id,
                "symbol": symbol,
                "instrument_type": "EQUITY",
                "market": "US",  # 米国市場
                "order_type": "LIMIT",
                "limit_price": f"{limit_price:.2f}",
                "quantity": str(quantity),
                "support_trading_session": "N",  # 通常取引時間のみ
                "side": "BUY" if action == "BUY" else "SELL",
                "time_in_force": "DAY",
                "entrust_type": "QTY",
                "account_tax_type": "GENERAL"
            }
            
            self.logger.info(f"注文パラメータ: {new_orders}")
            
            # リトライ機能付きで注文を発注（v2 API）
            def api_call():
                return self.api.order_v2.place_order(account_id=self.account_id, new_orders=new_orders)
            
            response = self.api_call_with_retry(api_call, max_retries=3, delay=2, api_name="place_order_v2")
            
            if response and response.status_code == 200:
                order_data = json.loads(response.text)
                self.logger.info(f"注文発注成功（v2 API）: {order_data}")
                
                # 注文IDを取得して監視を開始（v2 API仕様）
                order_id = order_data.get('order_id')
                client_order_id = order_data.get('client_order_id')
                
                if order_id:
                    self.logger.info(f"注文ID: {order_id}")
                    self.logger.info(f"クライアント注文ID: {client_order_id}")
                    # 注文の監視を開始
                    self.monitor_order(order_id, symbol)
                
                return True
            else:
                error_msg = response.text if response else 'No response'
                self.logger.error(f"注文発注失敗: {error_msg}")
                
                # 特定のエラーの場合の処理
                if response and response.status_code == 417:
                    if "ORDER_BUYING_POWER_NOT_ENOUGH" in error_msg:
                        self.logger.error(f"❌ 購入資金不足: {symbol}")
                    elif "INVALID_SYMBOL" in error_msg:
                        self.logger.error(f"❌ 無効な銘柄: {symbol}")
                    elif "INVALID_INSTRUMENT_ID" in error_msg:
                        self.logger.error(f"❌ 無効なinstrument_id: {symbol} ({instrument_id})")
                
                return False
                
        except Exception as e:
            self.logger.error(f"注文発注エラー: {e}")
            return False
    
    def monitor_order(self, order_id, symbol):
        """注文の監視（リトライ機能付き）"""
        try:
            self.logger.info(f"注文監視開始: {order_id} ({symbol})")
            
            # リトライ機能付きで注文詳細を取得（v2 API）
            def api_call():
                return self.api.order_v2.get_order_detail(order_id)
            
            response = self.api_call_with_retry(api_call, max_retries=2, delay=1, api_name="get_order_detail")
            
            if response and response.status_code == 200:
                order_detail = json.loads(response.text)
                self.logger.info(f"注文詳細: {order_detail}")
                
                # 注文ステータスを確認（v2 API仕様）
                status = order_detail.get('status')
                self.logger.info(f"注文ステータス: {status}")
                
                if status == 'FILLED':
                    self.logger.info(f"✅ 注文約定完了: {symbol}")
                elif status == 'CANCELLED':
                    self.logger.warning(f"⚠️ 注文キャンセル: {symbol}")
                elif status == 'REJECTED':
                    self.logger.error(f"❌ 注文拒否: {symbol}")
                else:
                    self.logger.info(f"⏳ 注文処理中: {symbol} (ステータス: {status})")
                
            else:
                self.logger.error(f"注文詳細取得失敗: {response.text if response else 'No response'}")
                
        except Exception as e:
            self.logger.error(f"注文監視エラー: {e}")
    
    def get_open_orders(self):
        """未約定注文を取得（リトライ機能付き）"""
        try:
            def api_call():
                return self.api.order_v2.get_order_history_request(self.account_id)
            
            response = self.api_call_with_retry(api_call, max_retries=2, delay=1, api_name="get_order_history_request")
            
            if response and response.status_code == 200:
                orders_data = json.loads(response.text)
                self.logger.info(f"注文履歴: {orders_data}")
                
                # 未約定注文のみをフィルタリング（v2 API仕様）
                open_orders = []
                
                # レスポンスがリストの場合
                if isinstance(orders_data, list):
                    orders = orders_data
                else:
                    orders = orders_data.get('data', [])
                
                for order in orders:
                    status = order.get('status')
                    if status in ['PENDING', 'PARTIALLY_FILLED']:
                        open_orders.append(order)
                
                self.logger.info(f"未約定注文数: {len(open_orders)}")
                return open_orders
            else:
                self.logger.error(f"注文履歴取得失敗: {response.text if response else 'No response'}")
                return []
                
        except Exception as e:
            self.logger.error(f"未約定注文取得エラー: {e}")
            return []
    
    def cancel_order(self, order_id):
        """注文をキャンセル（リトライ機能付き）"""
        try:
            self.logger.info(f"注文キャンセル: {order_id}")
            
            def api_call():
                return self.api.order_v2.cancel_order(order_id)
            
            response = self.api_call_with_retry(api_call, max_retries=2, delay=1, api_name="cancel_order")
            
            if response and response.status_code == 200:
                cancel_data = json.loads(response.text)
                self.logger.info(f"注文キャンセル成功: {cancel_data}")
                return True
            else:
                self.logger.error(f"注文キャンセル失敗: {response.text if response else 'No response'}")
                return False
                
        except Exception as e:
            self.logger.error(f"注文キャンセルエラー: {e}")
            return False
    
    def save_trades_to_csv(self, trades):
        """取引履歴をCSVに保存"""
        if trades:
            df = pd.DataFrame(trades)
            df['timestamp'] = datetime.now()
            df.to_csv('data/trades.csv', mode='a', header=not pd.io.common.file_exists('data/trades.csv'), index=False)
            self.logger.info("取引履歴をCSVに保存しました")
    
    def get_portfolio_summary(self):
        """ポートフォリオサマリーを取得"""
        try:
            # 口座残高を取得
            balances = self.get_account_balance()
            if not balances:
                return None
            
            # USDの利用可能資金を取得（v2 API形式）
            usd_balance = balances.get('USD', {})
            cash_balance = usd_balance.get('cash_balance', 0)
            buying_power = usd_balance.get('buying_power', 0)
            unrealized_profit_loss = usd_balance.get('unrealized_profit_loss', 0)
            
            # 現在のポジションを取得
            current_positions = self.get_current_positions()
            
            # ポジションの総価値を計算
            total_positions_value = sum(pos.get('market_value', 0) for pos in current_positions)
            
            # 総資産価値 = 現金 + ポジション価値
            total_value = cash_balance + total_positions_value
            
            summary = {
                'cash_balance': cash_balance,
                'buying_power': buying_power,
                'unrealized_profit_loss': unrealized_profit_loss,
                'total_positions': total_positions_value,
                'total_value': total_value,
                'positions_count': len(current_positions),
                'balances': balances,
                'positions': current_positions
            }
            
            self.logger.info(f"ポートフォリオサマリー: {summary}")
            return summary
            
        except Exception as e:
            self.logger.error(f"ポートフォリオサマリー取得エラー: {e}")
            return None
    
    def rebalance(self):
        """完全なポートフォリオリバランシングを実行（改善版）"""
        try:
            self.logger.info("=== 完全なポートフォリオリバランシング開始（改善版） ===")
            
            # ステップ1: 現在のポジションと残高をチェック
            self.logger.info("📊 ステップ1: 現在のポジションと残高をチェック")
            portfolio_summary = self.get_portfolio_summary()
            if not portfolio_summary:
                self.logger.error("ポートフォリオサマリー取得失敗")
                return
            
            current_positions = portfolio_summary['positions']
            total_value = portfolio_summary['total_value']
            available_cash = portfolio_summary['buying_power']  # 買付余力（Buying Power）を使用
            
            # 安全マージン情報を取得
            usd_balance = portfolio_summary['balances'].get('USD', {})
            original_buying_power = usd_balance.get('original_buying_power', available_cash)
            safety_margin = usd_balance.get('safety_margin_applied', 0)
            
            self.logger.info(f"利用可能なUSD: ${available_cash:,.2f} (安全マージンなし)")
            self.logger.info(f"元の買付余力: ${original_buying_power:,.2f}")
            self.logger.info(f"安全マージン: {safety_margin*100:.1f}% (OFF)")
            self.logger.info(f"総資産価値: ${total_value:,.2f}")
            self.logger.info(f"現在のポジション数: {len(current_positions)}")
            
            # ステップ2: 保守的価格で現在の価格を取得
            self.logger.info("💰 ステップ2: 保守的価格で現在の価格を取得")
            price_data = self.get_all_stock_prices_conservative()
            if not price_data:
                self.logger.error("保守的価格データ取得失敗")
                return
            
            self.logger.info(f"取得した保守的価格データ: {price_data}")
            
            # ステップ3: ポートフォリオ配分に従ってリバランス計算と実行
            self.logger.info("⚖️ ステップ3: ポートフォリオ配分に従ってリバランス計算（改善版）")
            
            # 改善されたリバランシング計算
            trades = self.calculate_rebalancing_trades_with_prices(
                current_positions, price_data, available_cash
            )
            
            if not trades:
                self.logger.info("実行する取引がありません")
                return
            
            # 取引実行
            self.logger.info("🚀 取引実行開始（改善版）")
            success_count = self.execute_trades_safely(trades)
            
            if success_count > 0:
                self.logger.info(f"✅ リバランシング完了: {success_count}/{len(trades)} 取引成功")
                
                # 取引後チェック
                self.post_trade_checks()
                
                # 取引履歴を保存
                self.save_trades_to_csv(trades)
            else:
                self.logger.error("❌ リバランシング失敗: 取引実行エラー")
                
        except Exception as e:
            self.logger.error(f"リバランシング中にエラー発生: {e}")
    
    def pre_trade_checks(self):
        """取引前のチェック"""
        try:
            self.logger.info("=== 取引前チェック開始 ===")
            
            # 1. 口座残高チェック
            balances = self.get_account_balance()
            if not balances:
                self.logger.error("口座残高取得失敗")
                return False
            
            # 2. 未約定注文チェック
            open_orders = self.get_open_orders()
            if open_orders:
                self.logger.warning(f"未約定注文が {len(open_orders)} 件あります")
                # 必要に応じてキャンセル
                for order in open_orders:
                    order_id = order.get('order_id')
                    if order_id:
                        self.logger.info(f"未約定注文をキャンセル: {order_id}")
                        self.cancel_order(order_id)
            
            # 3. 取引時間チェック（簡易版）
            from datetime import datetime
            now = datetime.now()
            if now.weekday() >= 5:  # 土日
                self.logger.warning("週末のため取引は実行されません")
                return False
            
            self.logger.info("取引前チェック完了")
            return True
            
        except Exception as e:
            self.logger.error(f"取引前チェックエラー: {e}")
            return False
    
    def post_trade_checks(self):
        """取引後のチェック"""
        try:
            self.logger.info("=== 取引後チェック開始 ===")
            
            # 1. 新しいポジションを確認
            new_positions = self.get_current_positions()
            self.logger.info(f"取引後のポジション数: {len(new_positions)}")
            
            # 2. 未約定注文を確認
            open_orders = self.get_open_orders()
            if open_orders:
                self.logger.warning(f"取引後に未約定注文が {len(open_orders)} 件残っています")
            
            # 3. 口座残高を再確認
            balances = self.get_account_balance()
            self.logger.info(f"取引後の口座残高: {balances}")
            
            self.logger.info("取引後チェック完了")
            
        except Exception as e:
            self.logger.error(f"取引後チェックエラー: {e}")

    def get_all_stock_prices(self):
        """すべての銘柄の現在価格を一括取得"""
        try:
            self.logger.info("全銘柄の価格を一括取得中...")
            price_data = {}
            
            # ポートフォリオ設定から銘柄リストを取得
            symbols = list(self.config.get('target_allocation', {}).keys())
            
            for symbol in symbols:
                try:
                    price = self.get_stock_price(symbol)
                    if price and price > 0:
                        price_data[symbol] = price
                        self.logger.info(f"✅ {symbol}: ${price}")
                    else:
                        self.logger.warning(f"⚠️ {symbol}: 価格取得失敗")
                        return None
                except Exception as e:
                    self.logger.error(f"❌ {symbol} 価格取得エラー: {e}")
                    return None
            
            self.logger.info(f"価格取得完了: {len(price_data)}/{len(symbols)} 銘柄")
            return price_data
            
        except Exception as e:
            self.logger.error(f"価格一括取得エラー: {e}")
            return None
    
    def get_stock_price_with_conservative_estimate(self, symbol):
        """保守的な価格見積もりで株価を取得"""
        try:
            self.logger.info(f"{symbol} の保守的価格を取得中...")
            
            # 基本価格を取得
            base_price = self.get_stock_price(symbol)
            if not base_price:
                self.logger.error(f"{symbol} の基本価格取得失敗")
                return None
            
            # 保守的マージン（1%）を適用
            conservative_margin = 0.01  # 1%
            conservative_price = base_price * (1 + conservative_margin)
            
            self.logger.info(f"{symbol} 価格: ${base_price:.2f} → 保守的価格: ${conservative_price:.2f} (+{conservative_margin*100:.1f}%)")
            
            return {
                'base_price': base_price,
                'conservative_price': conservative_price,
                'margin_applied': conservative_margin
            }
            
        except Exception as e:
            self.logger.error(f"{symbol} の保守的価格取得中にエラー発生: {e}")
            return None
    
    def get_all_stock_prices_conservative(self):
        """全銘柄の保守的価格を一括取得"""
        try:
            self.logger.info("全銘柄の保守的価格を一括取得中...")
            
            conservative_prices = {}
            successful_count = 0
            
            for symbol in self.config.get('target_allocation', {}).keys():
                price_data = self.get_stock_price_with_conservative_estimate(symbol)
                if price_data:
                    conservative_prices[symbol] = price_data['conservative_price']
                    successful_count += 1
                    self.logger.info(f"✅ {symbol}: ${price_data['conservative_price']:.2f}")
                else:
                    self.logger.error(f"❌ {symbol}: 価格取得失敗")
            
            self.logger.info(f"保守的価格取得完了: {successful_count}/{len(self.config.get('target_allocation', {}))} 銘柄")
            
            return conservative_prices
            
        except Exception as e:
            self.logger.error(f"保守的価格一括取得中にエラー発生: {e}")
            return {}
    
    def calculate_rebalancing_trades_with_prices(self, current_positions, price_data, available_cash):
        """リバランシング取引を計算（資金制約考慮 + 部分実行最適化）"""
        try:
            self.logger.info("リバランシング取引を計算中（資金制約考慮 + 部分実行最適化）...")
            
            # 目標配分を計算
            target_allocation = self.calculate_target_allocation(available_cash)
            
            # 現在のポジション価値を計算
            current_positions_value = {}
            for position in current_positions:
                symbol = position['symbol']
                quantity = position['quantity']
                price = price_data.get(symbol, 0)
                current_positions_value[symbol] = quantity * price
            
            # 取引リストを初期化
            trades = []
            remaining_cash = available_cash
            
            # 各銘柄について取引を計算（優先順位付き）
            for symbol, target_value in target_allocation.items():
                if remaining_cash <= 0:
                    self.logger.warning(f"資金不足のため {symbol} の購入をスキップ")
                    continue
                
                current_value = current_positions_value.get(symbol, 0)
                price = price_data.get(symbol, 0)
                
                if price <= 0:
                    self.logger.warning(f"{symbol} の価格が無効: ${price}")
                    continue
                
                # 目標数量を計算
                target_quantity = int(target_value / price)
                
                # 現在の数量を取得
                current_quantity = 0
                for position in current_positions:
                    if position['symbol'] == symbol:
                        current_quantity = position['quantity']
                        break
                
                # 必要な数量を計算
                needed_quantity = target_quantity - current_quantity
                
                if needed_quantity > 0:  # 購入が必要
                    # 残り資金で購入可能な最大数量を計算
                    max_affordable_quantity = int(remaining_cash / price)
                    actual_quantity = min(needed_quantity, max_affordable_quantity)
                    
                    if actual_quantity > 0:
                        estimated_value = actual_quantity * price
                        
                        # 買付余力チェック
                        if not self.check_buying_power_before_order(estimated_value):
                            self.logger.warning(f"{symbol} の買付余力不足のため購入をスキップ")
                            continue
                        
                        trade = {
                            'symbol': symbol,
                            'action': 'BUY',
                            'quantity': actual_quantity,
                            'estimated_value': estimated_value,
                            'current_price': price,
                            'target_quantity': target_quantity,
                            'current_quantity': current_quantity,
                            'remaining_cash_before': remaining_cash,
                            'remaining_cash_after': remaining_cash - estimated_value
                        }
                        
                        trades.append(trade)
                        remaining_cash -= estimated_value
                        
                        self.logger.info(f"✅ {symbol}: {actual_quantity}株購入予定 (${estimated_value:,.2f})")
                        self.logger.info(f"   残り資金: ${remaining_cash:,.2f}")
                        
                        if actual_quantity < needed_quantity:
                            self.logger.info(f"   ⚠️ 部分実行: {actual_quantity}/{needed_quantity}株")
                    else:
                        self.logger.warning(f"{symbol}: 資金不足のため購入不可")
                        
                elif needed_quantity < 0:  # 売却が必要
                    # 売却は資金を増やすので制限なし
                    trade = {
                        'symbol': symbol,
                        'action': 'SELL',
                        'quantity': abs(needed_quantity),
                        'estimated_value': abs(needed_quantity) * price,
                        'current_price': price,
                        'target_quantity': target_quantity,
                        'current_quantity': current_quantity
                    }
                    trades.append(trade)
                    self.logger.info(f"✅ {symbol}: {abs(needed_quantity)}株売却予定")
            
            self.logger.info(f"計算された取引: {trades}")
            
            # 総コストを計算
            total_cost = sum(trade['estimated_value'] for trade in trades if trade['action'] == 'BUY')
            self.logger.info(f"総推定コスト: ${total_cost:,.2f}")
            self.logger.info(f"利用可能資金: ${available_cash:,.2f}")
            self.logger.info(f"残り資金: ${remaining_cash:,.2f}")
            self.logger.info(f"実行率: {len([t for t in trades if t['action'] == 'BUY'])}/{len(target_allocation)} 銘柄")
            
            return trades
            
        except Exception as e:
            self.logger.error(f"リバランシング取引計算中にエラー発生: {e}")
            return []
    
    def execute_trades_safely(self, trades):
        """安全な取引実行（資金制約を考慮）"""
        try:
            self.logger.info("安全な取引実行開始")
            
            if self.dry_run:
                self.logger.info("DRY RUNモード: 実際の取引は実行されません")
                for trade in trades:
                    self.logger.info(f"DRY RUN - {trade['action']} {trade['quantity']} shares of {trade['symbol']}")
                return True
            else:
                self.logger.info("実際の取引実行開始")
                
                # 現在の買付余力を取得
                current_balance = self.get_account_balance()
                if not current_balance:
                    self.logger.error("買付余力取得失敗")
                    return False
                
                usd_balance = current_balance.get('USD', {})
                available_cash = usd_balance.get('available_cash', 0)
                
                self.logger.info(f"現在の利用可能資金: ${available_cash:,.2f}")
                
                success_count = 0
                total_executed_cost = 0
                
                for trade in trades:
                    try:
                        symbol = trade['symbol']
                        action = trade['action']
                        quantity = trade['quantity']
                        estimated_value = trade['estimated_value']
                        
                        self.logger.info(f"🔵 {symbol} {action} {quantity}株実行中...")
                        
                        # 買付余力チェック
                        if action == 'BUY' and estimated_value > available_cash:
                            self.logger.warning(f"❌ {symbol}: 買付余力不足 (必要: ${estimated_value:,.2f}, 利用可能: ${available_cash:,.2f})")
                            continue
                        
                        # 実際の注文実行
                        if action == 'BUY':
                            # instrument_idを取得
                            instrument_id = self.get_instrument_id(symbol)
                            if not instrument_id:
                                self.logger.error(f"❌ {symbol}: instrument_id取得失敗")
                                continue
                            
                            # 注文を発注
                            success = self.place_order(trade, instrument_id)
                        else:  # SELL
                            # instrument_idを取得
                            instrument_id = self.get_instrument_id(symbol)
                            if not instrument_id:
                                self.logger.error(f"❌ {symbol}: instrument_id取得失敗")
                                continue
                            
                            # 注文を発注
                            success = self.place_order(trade, instrument_id)
                        
                        if success:
                            success_count += 1
                            if action == 'BUY':
                                total_executed_cost += estimated_value
                                available_cash -= estimated_value
                                self.logger.info(f"✅ {symbol}: {action} {quantity}株成功 (${estimated_value:,.2f})")
                                self.logger.info(f"   残り資金: ${available_cash:,.2f}")
                            else:
                                self.logger.info(f"✅ {symbol}: {action} {quantity}株成功")
                        else:
                            self.logger.error(f"❌ {symbol}: 取引実行失敗")
                            
                    except Exception as e:
                        self.logger.error(f"❌ {trade.get('symbol', 'Unknown')}: 取引実行エラー: {e}")
                
                self.logger.info(f"取引実行完了: {success_count}/{len(trades)} 成功")
                self.logger.info(f"総実行コスト: ${total_executed_cost:,.2f}")
                
                return success_count > 0
                
        except Exception as e:
            self.logger.error(f"取引実行中にエラー発生: {e}")
            return False

    def check_buying_power_before_order(self, required_amount):
        """注文前に買付余力をチェック"""
        try:
            current_balance = self.get_account_balance()
            if not current_balance:
                self.logger.error("買付余力チェック失敗: 残高取得エラー")
                return False
            
            usd_balance = current_balance.get('USD', {})
            available_cash = usd_balance.get('available_cash', 0)
            original_buying_power = usd_balance.get('original_buying_power', 0)
            safety_margin = usd_balance.get('safety_margin_applied', 0)
            
            self.logger.info(f"買付余力チェック:")
            self.logger.info(f"  必要金額: ${required_amount:,.2f}")
            self.logger.info(f"  利用可能資金: ${available_cash:,.2f}")
            self.logger.info(f"  元の買付余力: ${original_buying_power:,.2f}")
            self.logger.info(f"  安全マージン: {safety_margin*100:.1f}% (OFF)")
            
            if available_cash >= required_amount:
                self.logger.info(f"  ✅ 買付余力充足")
                return True
            else:
                self.logger.warning(f"  ❌ 買付余力不足: 不足額 ${required_amount - available_cash:,.2f}")
                return False
                
        except Exception as e:
            self.logger.error(f"買付余力チェック中にエラー発生: {e}")
            return False

def main():
    """メイン関数"""
    try:
        # コマンドライン引数から設定ファイルを取得
        config_file = sys.argv[1] if len(sys.argv) > 1 else 'webull_config_with_allocation.json'
        dry_run = sys.argv[2] == 'dry_run' if len(sys.argv) > 2 else None
        
        rebalancer = WebullCompleteRebalancer(config_file=config_file, dry_run=dry_run)
        rebalancer.rebalance()
    except Exception as e:
        logging.error(f"メイン実行エラー: {e}")

if __name__ == "__main__":
    main() 
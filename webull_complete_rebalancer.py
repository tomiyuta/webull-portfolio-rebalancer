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
import csv
import random
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
        self.account_id = self.config.get('account_id', '')
        self.dry_run = self.config.get('dry_run', True)
        
        # キャッシュの初期化
        self._price_cache = {}
        self._instrument_id_cache = {}
        self._last_api_call = {}  # API呼び出し制限用
        
        # レート制限統計の初期化
        self._rate_limit_stats = {
            'total_calls': 0,
            'rate_limited_calls': 0,
            'server_errors': 0,
            'total_wait_time': 0,
            'api_call_counts': {}
        }
        
        # SDK互換性情報の初期化
        self._sdk_compatibility = {
            'sdk_versions': {},
            'api_methods': {},
            'compatibility_issues': [],
            'recommendations': []
        }
        
        # 設定の検証
        self.validate_config()
        
        # SDK互換性の確認
        self.check_sdk_compatibility()
        
        # アカウントIDの確認と自動取得
        if not self.ensure_account_id():
            raise ValueError("アカウントIDの取得に失敗しました。設定を確認してください。")
        
        # target_allocationをCSVファイルから読み込み
        portfolio_config_file = self.config.get('portfolio_config_file', 'portfolio.csv')
        self.target_allocation = self.load_portfolio_config_csv(portfolio_config_file)
        
        self.logger.info(f"WebullCompleteRebalancer初期化完了")
        self.logger.info(f"Account ID: {self.account_id}")
        self.logger.info(f"Dry Run Mode: {self.dry_run}")
    
    def validate_config(self):
        """設定の検証"""
        required_fields = ['app_key', 'app_secret']
        missing_fields = [field for field in required_fields if not self.config.get(field)]
        
        if missing_fields:
            raise ValueError(f"必須設定が不足しています: {missing_fields}")
        
        # account_idの検証をスキップ（認証時に自動取得されるため）
        # if not self.config.get('account_id'):
        #     raise ValueError("account_idが設定されていません")
        
        # target_allocationの検証をスキップ（CSVファイルから読み込むため）
        # if not self.config.get('target_allocation'):
        #     raise ValueError("target_allocationが設定されていません")
        
        # 配分の合計を確認（CSVファイルから読み込むためスキップ）
        # total_allocation = sum(self.config['target_allocation'].values())
        # if abs(total_allocation - 100) > 1:  # 1%の誤差を許容
        #     self.logger.warning(f"配分の合計が100%ではありません: {total_allocation}%")
    
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
    
    def get_account_id_from_api(self):
        """APIからアカウントIDを自動取得"""
        try:
            self.logger.info("=== アカウントID自動取得開始 ===")
            
            # 総合口座情報取得
            response = self.api.account.get_app_subscriptions()
            
            if response.status_code == 200:
                data = json.loads(response.text)
                self.logger.info(f"取得したアカウントデータ: {data}")
                
                # アカウント詳細を抽出
                for account_data in data:
                    if account_data.get('account_type') == "CASH":
                        account_number = account_data.get('account_number')
                        account_id = account_data.get('account_id')
                        subscription_id = account_data.get('subscription_id')
                        user_id = account_data.get('user_id')
                        
                        self.logger.info(f"✅ アカウント情報取得成功:")
                        self.logger.info(f"  - Account Number: {account_number}")
                        self.logger.info(f"  - Account ID: {account_id}")
                        self.logger.info(f"  - Subscription ID: {subscription_id}")
                        self.logger.info(f"  - User ID: {user_id}")
                        
                        # 設定ファイルを更新
                        self.config['account_id'] = account_id
                        self.config['account_number'] = account_number
                        self.config['subscription_id'] = subscription_id
                        self.config['user_id'] = user_id
                        
                        # 設定ファイルを保存
                        self.save_config()
                        
                        return account_id
                
                self.logger.error("❌ CASHアカウントが見つかりませんでした")
                return None
            else:
                self.logger.error(f"❌ API呼び出しエラー: {response.status_code}")
                self.logger.error(f"レスポンス: {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ アカウントID取得エラー: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def save_config(self):
        """設定ファイルを保存"""
        try:
            config_file = 'webull_config_with_allocation.json'
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self.logger.info(f"✅ 設定ファイルを更新しました: {config_file}")
        except Exception as e:
            self.logger.error(f"❌ 設定ファイル保存エラー: {e}")
    
    def ensure_account_id(self):
        """アカウントIDが設定されているか確認し、必要に応じて取得"""
        if not self.account_id:
            self.logger.info("アカウントIDが設定されていません。自動取得を試行します...")
            account_id = self.get_account_id_from_api()
            if account_id:
                self.account_id = account_id
                self.logger.info(f"✅ アカウントID設定完了: {account_id}")
                return True
            else:
                self.logger.error("❌ アカウントIDの取得に失敗しました")
                return False
        else:
            self.logger.info(f"✅ アカウントID既に設定済み: {self.account_id}")
            return True
    
    def rate_limit_check(self, api_name):
        """API呼び出し制限チェック（改善版）"""
        now = datetime.now()
        
        # API別の制限設定
        rate_limits = {
            'get_account_balance': 2,      # 2秒間隔
            'get_current_positions': 2,    # 2秒間隔
            'get_stock_price': 1,          # 1秒間隔
            'get_instrument_id': 1,        # 1秒間隔
            'place_order': 3,              # 3秒間隔（注文は慎重に）
            'get_order_detail': 2,         # 2秒間隔
            'get_order_list': 2,           # 2秒間隔
            'cancel_order': 3,             # 3秒間隔
            'default': 1                   # デフォルト1秒間隔
        }
        
        # API別の制限時間を取得
        min_interval = rate_limits.get(api_name, rate_limits['default'])
        
        if api_name in self._last_api_call:
            last_call = self._last_api_call[api_name]
            time_diff = (now - last_call).total_seconds()
            
            # 制限時間を超えていない場合
            if time_diff < min_interval:
                sleep_time = min_interval - time_diff
                self.logger.debug(f"API制限のため {sleep_time:.2f}秒待機: {api_name} (制限: {min_interval}秒)")
                time.sleep(sleep_time)
        
        self._last_api_call[api_name] = now
        
        # 統計情報を更新
        self._rate_limit_stats['total_calls'] += 1
        self._rate_limit_stats['api_call_counts'][api_name] = self._rate_limit_stats['api_call_counts'].get(api_name, 0) + 1
    
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
                
                # レート制限エラーの場合（429）
                if response.status_code == 429:
                    # レスポンスヘッダーからretry-afterを取得
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = int(retry_after)
                            self.logger.warning(f"レート制限エラー (429)。サーバー指定の待機時間: {wait_time}秒")
                        except ValueError:
                            wait_time = delay * (2 ** attempt)  # 指数バックオフ
                            self.logger.warning(f"レート制限エラー (429)。指数バックオフ: {wait_time}秒")
                    else:
                        wait_time = delay * (2 ** attempt)  # 指数バックオフ
                        self.logger.warning(f"レート制限エラー (429)。指数バックオフ: {wait_time}秒")
                    
                    # 最大待機時間を制限（60秒）
                    wait_time = min(wait_time, 60)
                    self.logger.info(f"API制限のため {wait_time}秒待機してリトライ... (試行 {attempt + 1}/{max_retries})")
                    
                    # 統計情報を更新
                    self._rate_limit_stats['rate_limited_calls'] += 1
                    self._rate_limit_stats['total_wait_time'] += wait_time
                    
                    time.sleep(wait_time)
                    continue
                
                # サーバーエラーの場合（5xx）
                if 500 <= response.status_code < 600:
                    wait_time = delay * (2 ** attempt)  # 指数バックオフ
                    self.logger.warning(f"サーバーエラー ({response.status_code})。{wait_time}秒待機してリトライ...")
                    
                    # 統計情報を更新
                    self._rate_limit_stats['server_errors'] += 1
                    self._rate_limit_stats['total_wait_time'] += wait_time
                    
                    time.sleep(wait_time)
                    continue
                
                # その他のエラー
                self.logger.error(f"API呼び出し失敗 (試行 {attempt + 1}/{max_retries}): {response.status_code} - {response.text}")
                
                # エラーの詳細分析
                self._analyze_api_error(response.status_code, response.text, api_name)
                
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
            # アカウントIDの確認
            if not self.account_id:
                self.logger.error("アカウントIDが設定されていません")
                return None
            
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
            # アカウントIDの確認
            if not self.account_id:
                self.logger.error("アカウントIDが設定されていません")
                return []
            
            def api_call():
                return self.api.account_v2.get_account_position(self.account_id)
            
            response = self.api_call_with_retry(api_call, max_retries=2, api_name="get_account_position")
            
            if response and response.status_code == 200:
                position_data = json.loads(response.text)
                self.logger.info(f"ポジション取得成功（v2 API）")
                
                # レスポンス構造をデバッグ
                self.logger.info(f"APIレスポンス構造: {json.dumps(position_data, indent=2)}")
                
                positions = []
                
                # レスポンスがリストの場合（直接ポジションリスト）
                if isinstance(position_data, list):
                    for position in position_data:
                        try:
                            symbol = position['items'][0]['symbol']
                            quantity = float(position['quantity'])
                            cost_price = float(position['cost_price'])
                            unrealized_pnl = float(position.get('unrealized_profit_loss', 0))
                            
                            # 数量が0より大きい場合のみ有効なポジションとして扱う
                            if quantity > 0:
                                # market_valueを計算（cost_price * quantity + unrealized_pnl）
                                market_value = cost_price * quantity + unrealized_pnl
                                
                                positions.append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'cost_price': cost_price,
                                    'market_value': market_value,
                                    'unrealized_profit_loss': unrealized_pnl
                                })
                                self.logger.info(f"ポジション: {symbol} - {quantity}株 - コスト: ${cost_price:.2f} - 市場価値: ${market_value:.2f}")
                        except (KeyError, ValueError, IndexError) as e:
                            self.logger.warning(f"ポジションデータの処理中にエラー: {e}")
                            continue
                    
                    if not positions:
                        self.logger.info("ポジションなし（空のリスト）")
                    else:
                        self.logger.info(f"取得したポジション数: {len(positions)}")
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
        """目標配分を計算（利用可能資金ベース）"""
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
    
    def calculate_target_allocation_total_value(self, current_positions, price_data, available_cash):
        """総資産価値ベースの目標配分を計算"""
        try:
            self.logger.info("総資産価値ベースの目標配分を計算中...")
            
            # 1. 現在のポジション価値を計算
            current_positions_value = {}
            for position in current_positions:
                symbol = position['symbol']
                quantity = position['quantity']
                # 価格データから取得、なければ既存のmarket_valueを使用
                price = price_data.get(symbol, 0)
                if price > 0:
                    current_positions_value[symbol] = quantity * price
                else:
                    # 既存のmarket_valueを使用
                    current_positions_value[symbol] = position.get('market_value', 0)
            
            # 2. 総資産価値を計算
            total_portfolio_value = sum(current_positions_value.values()) + available_cash
            
            # 3. 目標配分を計算
            target_allocation = self.config.get('target_allocation', {})
            allocation = {}
            
            for symbol, percentage in target_allocation.items():
                target_value = total_portfolio_value * (percentage / 100)
                allocation[symbol] = target_value
            
            self.logger.info(f"総資産価値: ${total_portfolio_value:,.2f}")
            self.logger.info(f"現在のポジション価値: {current_positions_value}")
            self.logger.info(f"目標配分: {allocation}")
            
            return allocation, current_positions_value, total_portfolio_value
            
        except Exception as e:
            self.logger.error(f"総資産価値ベース目標配分計算中にエラー発生: {e}")
            return {}, {}, 0
    
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
    
    def calculate_sell_trades(self, current_positions, target_allocation, price_data):
        """既存ポジションの売却取引を計算"""
        try:
            self.logger.info("既存ポジションの売却取引を計算中...")
            sell_trades = []
            
            for position in current_positions:
                symbol = position['symbol']
                current_quantity = position['quantity']
                price = price_data.get(symbol, 0)
                current_value = current_quantity * price
                
                # 目標配分に含まれない銘柄は全売却
                if symbol not in target_allocation:
                    # 価格データから現在価格を取得
                    current_price = price_data.get(symbol, 0)
                    if current_price > 0:
                        estimated_value = current_quantity * current_price
                    else:
                        estimated_value = current_value
                    
                    sell_trades.append({
                        'symbol': symbol,
                        'action': 'SELL',
                        'quantity': current_quantity,
                        'estimated_value': estimated_value,
                        'current_price': current_price,
                        'reason': 'target_allocation_not_included'
                    })
                    self.logger.info(f"✅ {symbol}: {current_quantity}株売却予定 (${estimated_value:,.2f}) - 目標配分に含まれない")
                else:
                    # 目標配分に含まれる銘柄の場合、過剰分を売却
                    target_value = target_allocation[symbol]
                    if current_value > target_value:
                        excess_value = current_value - target_value
                        # 価格データから現在価格を取得
                        current_price = price_data.get(symbol, 0)
                        if current_price > 0:
                            excess_quantity = int(excess_value / current_price)
                            estimated_value = excess_quantity * current_price
                        else:
                            excess_quantity = int(excess_value / price)
                            estimated_value = excess_quantity * price
                        
                        if excess_quantity > 0:
                            sell_trades.append({
                                'symbol': symbol,
                                'action': 'SELL',
                                'quantity': excess_quantity,
                                'estimated_value': estimated_value,
                                'current_price': current_price,
                                'reason': 'excess_position'
                            })
                            self.logger.info(f"✅ {symbol}: {excess_quantity}株売却予定 (${estimated_value:,.2f}) - 過剰ポジション")
            
            self.logger.info(f"売却取引: {len(sell_trades)}件")
            return sell_trades
            
        except Exception as e:
            self.logger.error(f"売却取引計算中にエラー発生: {e}")
            return []
    
    def calculate_buy_trades(self, target_allocation, current_positions, price_data, available_cash):
        """新規購入取引を計算"""
        try:
            self.logger.info("新規購入取引を計算中...")
            buy_trades = []
            remaining_cash = available_cash
            
            for symbol, target_value in target_allocation.items():
                price = price_data.get(symbol, 0)
                if price <= 0:
                    self.logger.warning(f"{symbol} の価格が無効: ${price}")
                    continue
                    
                # 現在の数量を取得
                current_quantity = 0
                for position in current_positions:
                    if position['symbol'] == symbol:
                        current_quantity = position['quantity']
                        break
                
                # 目標数量を計算
                target_quantity = int(target_value / price)
                needed_quantity = target_quantity - current_quantity
                
                if needed_quantity > 0:  # 購入が必要
                    # 購入可能な最大数量を計算
                    max_affordable_quantity = int(remaining_cash / price)
                    actual_quantity = min(needed_quantity, max_affordable_quantity)
                    
                    if actual_quantity > 0:
                        estimated_value = actual_quantity * price
                        buy_trades.append({
                            'symbol': symbol,
                            'action': 'BUY',
                            'quantity': actual_quantity,
                            'estimated_value': estimated_value,
                            'current_price': price,
                            'target_quantity': target_quantity,
                            'current_quantity': current_quantity,
                            'remaining_cash_before': remaining_cash,
                            'remaining_cash_after': remaining_cash - estimated_value
                        })
                        remaining_cash -= estimated_value
                        
                        self.logger.info(f"✅ {symbol}: {actual_quantity}株購入予定 (${estimated_value:,.2f})")
                        self.logger.info(f"   残り資金: ${remaining_cash:,.2f}")
                        
                        if actual_quantity < needed_quantity:
                            self.logger.info(f"   ⚠️ 部分実行: {actual_quantity}/{needed_quantity}株")
                    else:
                        self.logger.warning(f"{symbol}: 資金不足のため購入不可")
            
            self.logger.info(f"購入取引: {len(buy_trades)}件")
            return buy_trades
            
        except Exception as e:
            self.logger.error(f"購入取引計算中にエラー発生: {e}")
            return []
    
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
            
            # 注文パラメータを構築（Webull APIドキュメント準拠）
            client_order_id = uuid.uuid4().hex
            
            # 売却の場合は異なる注文タイプを試行
            if action == "SELL":
                # 現在のSDKに合わせてSELL注文を設定
                stock_order = {
                    "client_order_id": client_order_id,
                    "instrument_id": str(instrument_id),  # 必須パラメータ
                    "side": "SELL",
                    "tif": "DAY",  # time_in_forceではなくtif
                    "extended_hours_trading": False,  # APIの要求に従ってfalseに設定
                    "order_type": "LIMIT",  # LIMIT注文で試行
                    "limit_price": f"{limit_price:.2f}",  # 指値価格を設定
                    "qty": str(int(quantity)),  # 文字列として送信
                    "trade_currency": "USD",  # 必須パラメータ
                    "account_tax_type": "GENERAL"  # 提供されたコードに合わせてGENERALに修正
                }
                self.logger.info(f"LIMIT注文で売却を試行: {symbol}")
            else:
                # 購入の場合は通常のLIMIT注文
                stock_order = {
                    "client_order_id": client_order_id,
                    "instrument_id": str(instrument_id),  # 必須パラメータ
                    "side": "BUY",
                    "tif": "DAY",  # time_in_forceではなくtif
                    "extended_hours_trading": False,  # APIの要求に従ってfalseに設定
                    "order_type": "LIMIT",
                    "limit_price": f"{limit_price:.2f}",
                    "qty": str(int(quantity)),  # 文字列として送信
                    "trade_currency": "USD",  # 必須パラメータ
                    "account_tax_type": "SPECIFIC"  # 画像のサンプルコードに合わせてSPECIFICに修正
                }
            
            # キャッシュアカウントでの売却の場合、Webull APIドキュメントに従ってパラメータを設定
            if action == "SELL":
                # キャッシュアカウントではclose_contractsとmargin_typeは使用できない
                # 基本的な売却注文のみを使用
                self.logger.info(f"キャッシュアカウント用の売却注文を実行: {symbol}")
                # account_tax_typeはGENERALのまま維持
            
            self.logger.info(f"注文パラメータ: {stock_order}")
            
            # リトライ機能付きで注文を発注（現在のSDKに合わせて修正）
            def api_call():
                # 現在のSDKでは従来のAPIメソッドを使用
                return self.api.order.place_order_v2(account_id=self.account_id, stock_order=stock_order)
            
            response = self.api_call_with_retry(api_call, max_retries=3, delay=2, api_name="place_order_v2")
            
            if response and response.status_code == 200:
                order_data = json.loads(response.text)
                self.logger.info(f"注文発注成功（Webull API）: {order_data}")
                
                # 注文IDを取得して監視を開始（Webull API仕様）
                order_id = order_data.get('order_id')
                client_order_id = order_data.get('client_order_id')
                
                if order_id:
                    self.logger.info(f"注文ID: {order_id}")
                    self.logger.info(f"クライアント注文ID: {client_order_id}")
                    # 注文の監視を開始
                    monitor_result = self.monitor_order(order_id, symbol, client_order_id)
                    
                    # 監視結果を処理
                    if monitor_result:
                        status = monitor_result.get('status')
                        if status == 'FILLED':
                            self.logger.info(f"✅ 取引成功: {symbol}")
                            return True
                        elif status in ['CANCELLED', 'REJECTED', 'TIMEOUT', 'ERROR']:
                            self.logger.error(f"❌ 取引失敗: {symbol} (ステータス: {status})")
                            return False
                
                return True
            else:
                error_msg = response.text if response else 'No response'
                self.logger.error(f"注文発注失敗: {error_msg}")
                
                # 特定のエラーの場合の処理
                if response and response.status_code == 417:
                    if "CASH_ACCOUNT_NOT_ALLOW_SELL_SHORT" in error_msg:
                        self.logger.error(f"❌ キャッシュアカウント売却制限: {symbol}")
                        # 段階的売却方法を試行
                        return self._try_staged_sell_method(symbol, quantity, instrument_id, current_price)
                    elif "ORDER_BUYING_POWER_NOT_ENOUGH" in error_msg:
                        self.logger.error(f"❌ 購入資金不足: {symbol}")
                    elif "INVALID_SYMBOL" in error_msg:
                        self.logger.error(f"❌ 無効な銘柄: {symbol}")
                        # INVALID_SYMBOLエラーの詳細分析と対策
                        return self._handle_invalid_symbol_error(symbol, quantity, instrument_id, current_price)
                    elif "INVALID_INSTRUMENT_ID" in error_msg:
                        self.logger.error(f"❌ 無効なinstrument_id: {symbol} ({instrument_id})")
                        # INVALID_INSTRUMENT_IDエラーの詳細分析と対策
                        return self._handle_invalid_instrument_id_error(symbol, quantity, instrument_id, current_price)
                
                return False
                
        except Exception as e:
            self.logger.error(f"注文発注エラー: {e}")
            return False
    
    def monitor_order(self, order_id, symbol, client_order_id=None, max_wait_time=300):
        """注文の監視（リトライ機能付き + タイムアウト処理）"""
        try:
            self.logger.info(f"注文監視開始: {order_id} ({symbol}) - 最大待機時間: {max_wait_time}秒")
            
            start_time = time.time()
            check_interval = 10  # 10秒ごとにチェック
            
            while time.time() - start_time < max_wait_time:
                # リトライ機能付きで注文詳細を取得（Webull API）
                def api_call():
                    # Webull APIでは、account_id、client_order_idまたはorder_idが必要
                    if client_order_id:
                        return self.api.order.get_order_detail(account_id=self.account_id, client_order_id=client_order_id)
                    else:
                        return self.api.order.get_order_detail(account_id=self.account_id, order_id=order_id)
                
                response = self.api_call_with_retry(api_call, max_retries=2, delay=1, api_name="get_order_detail")
                
                if response and response.status_code == 200:
                    order_detail = json.loads(response.text)
                    
                    # 注文ステータスを確認（Webull API仕様）
                    status = order_detail.get('status')
                    self.logger.info(f"注文ステータス: {symbol} - {status}")
                    
                    if status == 'FILLED':
                        self.logger.info(f"✅ 注文約定完了: {symbol}")
                        return {'status': 'FILLED', 'order_detail': order_detail}
                    elif status == 'CANCELLED':
                        self.logger.warning(f"⚠️ 注文キャンセル: {symbol}")
                        return {'status': 'CANCELLED', 'order_detail': order_detail}
                    elif status == 'REJECTED':
                        self.logger.error(f"❌ 注文拒否: {symbol}")
                        return {'status': 'REJECTED', 'order_detail': order_detail}
                    elif status in ['PENDING', 'PARTIALLY_FILLED']:
                        elapsed_time = time.time() - start_time
                        self.logger.info(f"⏳ 注文処理中: {symbol} (経過時間: {elapsed_time:.1f}秒)")
                        
                        # タイムアウトに近づいた場合の警告
                        if elapsed_time > max_wait_time * 0.8:
                            self.logger.warning(f"⚠️ 注文タイムアウトに近づいています: {symbol}")
                        
                        time.sleep(check_interval)
                    else:
                        self.logger.info(f"⏳ 注文処理中: {symbol} (ステータス: {status})")
                        time.sleep(check_interval)
                else:
                    self.logger.error(f"注文詳細取得失敗: {response.text if response else 'No response'}")
                    time.sleep(check_interval)
            
            # タイムアウト
            self.logger.error(f"❌ 注文タイムアウト: {symbol} (最大待機時間: {max_wait_time}秒)")
            return {'status': 'TIMEOUT', 'order_detail': None}
                
        except Exception as e:
            self.logger.error(f"注文監視エラー: {e}")
            return {'status': 'ERROR', 'order_detail': None}
    
    def get_open_orders(self):
        """未約定注文を取得（リトライ機能付き）"""
        try:
            def api_call():
                # 現在のSDKで利用可能なメソッドを使用
                return self.api.order.get_order_list(self.account_id)
            
            response = self.api_call_with_retry(api_call, max_retries=2, delay=1, api_name="get_order_list")
            
            if response and response.status_code == 200:
                orders_data = json.loads(response.text)
                self.logger.info(f"注文履歴: {orders_data}")
                
                # 未約定注文のみをフィルタリング（Webull API仕様）
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
                return self.api.order.cancel_order(order_id)
            
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
    
    def monitor_all_open_orders(self, max_wait_time=300):
        """すべての未約定注文を監視"""
        try:
            self.logger.info("=== 未約定注文の一括監視開始 ===")
            
            start_time = time.time()
            check_interval = 30  # 30秒ごとにチェック
            
            while time.time() - start_time < max_wait_time:
                # 未約定注文を取得
                open_orders = self.get_open_orders()
                
                if not open_orders:
                    self.logger.info("✅ 未約定注文なし - すべての注文が約定またはキャンセルされました")
                    return True
                
                self.logger.info(f"⏳ 未約定注文数: {len(open_orders)}")
                
                # 各注文の状況を確認
                for order in open_orders:
                    order_id = order.get('order_id')
                    symbol = order.get('symbol', 'Unknown')
                    status = order.get('status')
                    
                    self.logger.info(f"注文状況: {symbol} - {status} (ID: {order_id})")
                
                # タイムアウトに近づいた場合の警告
                elapsed_time = time.time() - start_time
                if elapsed_time > max_wait_time * 0.8:
                    self.logger.warning(f"⚠️ 監視タイムアウトに近づいています (経過時間: {elapsed_time:.1f}秒)")
                
                time.sleep(check_interval)
            
            # タイムアウト
            self.logger.error(f"❌ 監視タイムアウト (最大待機時間: {max_wait_time}秒)")
            return False
            
        except Exception as e:
            self.logger.error(f"未約定注文監視エラー: {e}")
            return False
    
    def cancel_all_open_orders(self):
        """すべての未約定注文をキャンセル"""
        try:
            self.logger.info("=== 未約定注文の一括キャンセル開始 ===")
            
            open_orders = self.get_open_orders()
            
            if not open_orders:
                self.logger.info("キャンセル対象の未約定注文なし")
                return True
            
            self.logger.info(f"キャンセル対象注文数: {len(open_orders)}")
            
            success_count = 0
            for order in open_orders:
                order_id = order.get('order_id')
                symbol = order.get('symbol', 'Unknown')
                
                if self.cancel_order(order_id):
                    self.logger.info(f"✅ キャンセル成功: {symbol}")
                    success_count += 1
                else:
                    self.logger.error(f"❌ キャンセル失敗: {symbol}")
            
            self.logger.info(f"キャンセル完了: {success_count}/{len(open_orders)} 成功")
            return success_count == len(open_orders)
            
        except Exception as e:
            self.logger.error(f"一括キャンセルエラー: {e}")
            return False
    
    def get_rate_limit_stats(self):
        """レート制限統計情報を取得"""
        stats = self._rate_limit_stats.copy()
        
        # 成功率を計算
        if stats['total_calls'] > 0:
            stats['success_rate'] = ((stats['total_calls'] - stats['rate_limited_calls'] - stats['server_errors']) / stats['total_calls']) * 100
        else:
            stats['success_rate'] = 100.0
        
        # 平均待機時間を計算
        total_errors = stats['rate_limited_calls'] + stats['server_errors']
        if total_errors > 0:
            stats['avg_wait_time'] = stats['total_wait_time'] / total_errors
        else:
            stats['avg_wait_time'] = 0.0
        
        return stats
    
    def print_rate_limit_stats(self):
        """レート制限統計情報を表示"""
        stats = self.get_rate_limit_stats()
        
        self.logger.info("=== レート制限統計情報 ===")
        self.logger.info(f"総API呼び出し数: {stats['total_calls']}")
        self.logger.info(f"レート制限エラー数: {stats['rate_limited_calls']}")
        self.logger.info(f"サーバーエラー数: {stats['server_errors']}")
        self.logger.info(f"成功率: {stats['success_rate']:.1f}%")
        self.logger.info(f"総待機時間: {stats['total_wait_time']:.1f}秒")
        self.logger.info(f"平均待機時間: {stats['avg_wait_time']:.1f}秒")
        
        if stats['api_call_counts']:
            self.logger.info("API別呼び出し数:")
            for api_name, count in sorted(stats['api_call_counts'].items(), key=lambda x: x[1], reverse=True):
                self.logger.info(f"  {api_name}: {count}回")
        
        self.logger.info("==========================")
    
    def _handle_invalid_symbol_error(self, symbol, quantity, instrument_id, current_price):
        """INVALID_SYMBOLエラーの詳細分析と対策"""
        try:
            self.logger.info(f"🔍 INVALID_SYMBOLエラーの詳細分析開始: {symbol}")
            
            # ステップ1: 銘柄の存在確認
            self.logger.info("ステップ1: 銘柄の存在確認")
            
            # 複数のカテゴリで銘柄検索を試行
            categories = ['US_STOCK', 'US_ETF', 'US_OPTION']
            found_instrument_id = None
            found_category = None
            
            for category in categories:
                try:
                    self.logger.info(f"  {category}カテゴリで検索中...")
                    instrument_id_result = self._get_instrument_id_from_api(symbol, category)
                    if instrument_id_result:
                        found_instrument_id = instrument_id_result
                        found_category = category
                        self.logger.info(f"  ✅ {category}カテゴリで発見: {found_instrument_id}")
                        break
                    else:
                        self.logger.info(f"  ❌ {category}カテゴリでは見つかりませんでした")
                except Exception as e:
                    self.logger.warning(f"  ⚠️ {category}カテゴリ検索エラー: {e}")
                    continue
            
            # ステップ2: 代替銘柄の提案
            if not found_instrument_id:
                self.logger.warning("ステップ2: 代替銘柄の提案")
                alternative_symbols = self._suggest_alternative_symbols(symbol)
                if alternative_symbols:
                    self.logger.info(f"代替銘柄候補: {alternative_symbols}")
                    # 最初の代替銘柄で再試行
                    alternative_symbol = alternative_symbols[0]
                    self.logger.info(f"代替銘柄で再試行: {alternative_symbol}")
                    return self._retry_with_alternative_symbol(alternative_symbol, quantity, current_price)
                else:
                    self.logger.error("代替銘柄が見つかりませんでした")
                    return False
            
            # ステップ3: 正しいinstrument_idで再試行
            if found_instrument_id and found_instrument_id != instrument_id:
                self.logger.info(f"ステップ3: 正しいinstrument_idで再試行")
                self.logger.info(f"  元のinstrument_id: {instrument_id}")
                self.logger.info(f"  正しいinstrument_id: {found_instrument_id}")
                self.logger.info(f"  カテゴリ: {found_category}")
                
                # 正しいinstrument_idで再試行
                return self._retry_with_correct_instrument_id(symbol, quantity, found_instrument_id, current_price)
            
            # ステップ4: その他の対策
            self.logger.warning("ステップ4: その他の対策を試行")
            return self._try_alternative_trading_methods(symbol, quantity, instrument_id, current_price)
            
        except Exception as e:
            self.logger.error(f"INVALID_SYMBOLエラー処理中にエラー発生: {e}")
            return False
    
    def _suggest_alternative_symbols(self, symbol):
        """代替銘柄を提案"""
        try:
            # 一般的な代替銘柄マッピング
            symbol_mapping = {
                'SPY': ['SPY', 'VOO', 'IVV'],  # S&P 500 ETF
                'QQQ': ['QQQ', 'TQQQ', 'QLD'],  # NASDAQ ETF
                'IWM': ['IWM', 'TNA', 'UWM'],   # Russell 2000 ETF
                'GLD': ['GLD', 'IAU', 'SGOL'],  # Gold ETF
                'SLV': ['SLV', 'PSLV', 'SIVR'], # Silver ETF
                'XLU': ['XLU', 'VPU', 'IDU'],   # Utilities ETF
                'TECL': ['TECL', 'SOXL', 'TMF'], # Technology Leveraged ETF
                'NUGT': ['NUGT', 'JNUG', 'DUST'] # Gold Miners Leveraged ETF
            }
            
            # 完全一致
            if symbol in symbol_mapping:
                return symbol_mapping[symbol]
            
            # 部分一致
            alternatives = []
            for key, values in symbol_mapping.items():
                if symbol in key or key in symbol:
                    alternatives.extend(values)
            
            # 重複を除去
            alternatives = list(set(alternatives))
            
            if alternatives:
                self.logger.info(f"代替銘柄候補: {alternatives}")
                return alternatives
            
            return []
            
        except Exception as e:
            self.logger.error(f"代替銘柄提案エラー: {e}")
            return []
    
    def _retry_with_alternative_symbol(self, alternative_symbol, quantity, current_price):
        """代替銘柄で再試行"""
        try:
            self.logger.info(f"代替銘柄で再試行: {alternative_symbol}")
            
            # 代替銘柄のinstrument_idを取得
            alternative_instrument_id = self.get_instrument_id(alternative_symbol)
            if not alternative_instrument_id:
                self.logger.error(f"代替銘柄のinstrument_id取得失敗: {alternative_symbol}")
                return False
            
            # 代替銘柄の価格を取得
            alternative_price = self.get_stock_price(alternative_symbol)
            if not alternative_price:
                self.logger.error(f"代替銘柄の価格取得失敗: {alternative_symbol}")
                return False
            
            # 代替銘柄で注文を再試行
            self.logger.info(f"代替銘柄で注文再試行: {alternative_symbol} (価格: ${alternative_price})")
            
            # 注文パラメータを調整
            adjusted_quantity = int((quantity * current_price) / alternative_price)
            if adjusted_quantity <= 0:
                self.logger.error(f"調整後の数量が0以下: {adjusted_quantity}")
                return False
            
            # 注文を再試行
            return self.place_order({
                'symbol': alternative_symbol,
                'action': 'BUY',
                'quantity': adjusted_quantity,
                'price': alternative_price
            }, alternative_instrument_id)
            
        except Exception as e:
            self.logger.error(f"代替銘柄再試行エラー: {e}")
            return False
    
    def _retry_with_correct_instrument_id(self, symbol, quantity, correct_instrument_id, current_price):
        """正しいinstrument_idで再試行"""
        try:
            self.logger.info(f"正しいinstrument_idで再試行: {symbol}")
            
            # 正しいinstrument_idで注文を再試行
            return self.place_order({
                'symbol': symbol,
                'action': 'BUY',
                'quantity': quantity,
                'price': current_price
            }, correct_instrument_id)
            
        except Exception as e:
            self.logger.error(f"正しいinstrument_id再試行エラー: {e}")
            return False
    
    def _try_alternative_trading_methods(self, symbol, quantity, instrument_id, current_price):
        """その他の取引方法を試行"""
        try:
            self.logger.info(f"その他の取引方法を試行: {symbol}")
            
            # 方法1: 価格を少し上げて再試行
            self.logger.info("方法1: 価格を少し上げて再試行")
            adjusted_price = current_price * 1.01  # 1%上げ
            
            result = self.place_order({
                'symbol': symbol,
                'action': 'BUY',
                'quantity': quantity,
                'price': adjusted_price
            }, instrument_id)
            
            if result:
                self.logger.info("✅ 価格調整で成功")
                return True
            
            # 方法2: 数量を少し減らして再試行
            self.logger.info("方法2: 数量を少し減らして再試行")
            adjusted_quantity = max(1, int(quantity * 0.95))  # 5%減
            
            result = self.place_order({
                'symbol': symbol,
                'action': 'BUY',
                'quantity': adjusted_quantity,
                'price': current_price
            }, instrument_id)
            
            if result:
                self.logger.info("✅ 数量調整で成功")
                return True
            
            self.logger.error("❌ すべての代替方法が失敗")
            return False
            
        except Exception as e:
            self.logger.error(f"代替取引方法エラー: {e}")
            return False
    
    def _handle_invalid_instrument_id_error(self, symbol, quantity, instrument_id, current_price):
        """INVALID_INSTRUMENT_IDエラーの詳細分析と対策"""
        try:
            self.logger.info(f"🔍 INVALID_INSTRUMENT_IDエラーの詳細分析開始: {symbol}")
            
            # ステップ1: キャッシュのクリア
            self.logger.info("ステップ1: キャッシュのクリア")
            self.clear_instrument_id_cache()
            self.logger.info("instrument_idキャッシュをクリアしました")
            
            # ステップ2: 新しいinstrument_idの取得
            self.logger.info("ステップ2: 新しいinstrument_idの取得")
            new_instrument_id = self.get_instrument_id(symbol)
            
            if new_instrument_id and new_instrument_id != instrument_id:
                self.logger.info(f"新しいinstrument_idを取得: {new_instrument_id}")
                self.logger.info(f"  元のinstrument_id: {instrument_id}")
                self.logger.info(f"  新しいinstrument_id: {new_instrument_id}")
                
                # 新しいinstrument_idで再試行
                return self._retry_with_correct_instrument_id(symbol, quantity, new_instrument_id, current_price)
            
            # ステップ3: 複数カテゴリでの検索
            if not new_instrument_id:
                self.logger.info("ステップ3: 複数カテゴリでの検索")
                categories = ['US_STOCK', 'US_ETF', 'US_OPTION']
                
                for category in categories:
                    try:
                        self.logger.info(f"  {category}カテゴリで検索中...")
                        category_instrument_id = self._get_instrument_id_from_api(symbol, category)
                        if category_instrument_id:
                            self.logger.info(f"  ✅ {category}カテゴリで発見: {category_instrument_id}")
                            return self._retry_with_correct_instrument_id(symbol, quantity, category_instrument_id, current_price)
                        else:
                            self.logger.info(f"  ❌ {category}カテゴリでは見つかりませんでした")
                    except Exception as e:
                        self.logger.warning(f"  ⚠️ {category}カテゴリ検索エラー: {e}")
                        continue
            
            # ステップ4: ポジションからの取得
            self.logger.info("ステップ4: ポジションからの取得")
            position_instrument_id = self._get_instrument_id_from_positions(symbol)
            if position_instrument_id and position_instrument_id != instrument_id:
                self.logger.info(f"ポジションからinstrument_idを取得: {position_instrument_id}")
                return self._retry_with_correct_instrument_id(symbol, quantity, position_instrument_id, current_price)
            
            # ステップ5: その他の対策
            self.logger.warning("ステップ5: その他の対策を試行")
            return self._try_alternative_trading_methods(symbol, quantity, instrument_id, current_price)
            
        except Exception as e:
            self.logger.error(f"INVALID_INSTRUMENT_IDエラー処理中にエラー発生: {e}")
            return False
    
    def _analyze_api_error(self, status_code, error_text, api_name):
        """APIエラーの詳細分析"""
        try:
            self.logger.info(f"🔍 APIエラーの詳細分析: {api_name} (ステータス: {status_code})")
            
            # エラーの分類
            error_category = self._categorize_api_error(status_code, error_text)
            self.logger.info(f"エラーカテゴリ: {error_category}")
            
            # エラーの詳細情報
            error_details = self._extract_error_details(error_text)
            if error_details:
                self.logger.info(f"エラー詳細: {error_details}")
            
            # 推奨対策の提示
            recommendations = self._get_error_recommendations(error_category, api_name)
            if recommendations:
                self.logger.info("推奨対策:")
                for i, recommendation in enumerate(recommendations, 1):
                    self.logger.info(f"  {i}. {recommendation}")
            
            # エラー統計の更新
            self._update_error_stats(error_category, api_name)
            
        except Exception as e:
            self.logger.error(f"エラー分析中にエラー発生: {e}")
    
    def _categorize_api_error(self, status_code, error_text):
        """APIエラーをカテゴリに分類"""
        try:
            # ステータスコードベースの分類
            if status_code == 400:
                if "INVALID_SYMBOL" in error_text:
                    return "INVALID_SYMBOL"
                elif "INVALID_INSTRUMENT_ID" in error_text:
                    return "INVALID_INSTRUMENT_ID"
                elif "ORDER_BUYING_POWER_NOT_ENOUGH" in error_text:
                    return "INSUFFICIENT_FUNDS"
                elif "CASH_ACCOUNT_NOT_ALLOW_SELL_SHORT" in error_text:
                    return "CASH_ACCOUNT_RESTRICTION"
                else:
                    return "BAD_REQUEST"
            elif status_code == 401:
                return "AUTHENTICATION_ERROR"
            elif status_code == 403:
                return "AUTHORIZATION_ERROR"
            elif status_code == 404:
                return "NOT_FOUND"
            elif status_code == 429:
                return "RATE_LIMIT"
            elif 500 <= status_code < 600:
                return "SERVER_ERROR"
            else:
                return "UNKNOWN_ERROR"
                
        except Exception as e:
            self.logger.error(f"エラー分類中にエラー発生: {e}")
            return "UNKNOWN_ERROR"
    
    def _extract_error_details(self, error_text):
        """エラーテキストから詳細情報を抽出"""
        try:
            # JSON形式のエラーレスポンスを解析
            if error_text.startswith('{'):
                try:
                    error_data = json.loads(error_text)
                    details = {}
                    
                    # 一般的なエラーフィールドを抽出
                    for field in ['code', 'msg', 'message', 'error', 'details']:
                        if field in error_data:
                            details[field] = error_data[field]
                    
                    return details
                except json.JSONDecodeError:
                    pass
            
            # プレーンテキストの場合はそのまま返す
            return {'raw_error': error_text}
            
        except Exception as e:
            self.logger.error(f"エラー詳細抽出中にエラー発生: {e}")
            return None
    
    def _get_error_recommendations(self, error_category, api_name):
        """エラーカテゴリに基づく推奨対策を取得"""
        recommendations = {
            'INVALID_SYMBOL': [
                "銘柄シンボルの正確性を確認してください",
                "複数のカテゴリ（US_STOCK, US_ETF）で検索を試行してください",
                "代替銘柄の使用を検討してください"
            ],
            'INVALID_INSTRUMENT_ID': [
                "instrument_idキャッシュをクリアしてください",
                "新しいinstrument_idを取得してください",
                "複数カテゴリでの検索を試行してください"
            ],
            'INSUFFICIENT_FUNDS': [
                "口座残高を確認してください",
                "注文数量を減らしてください",
                "購入資金の追加を検討してください"
            ],
            'CASH_ACCOUNT_RESTRICTION': [
                "マージンアカウントへの変更を検討してください",
                "利用可能資金ベースのリバランスを試行してください",
                "手動での売却を検討してください"
            ],
            'AUTHENTICATION_ERROR': [
                "API認証情報を確認してください",
                "トークンの有効期限を確認してください",
                "再認証を実行してください"
            ],
            'AUTHORIZATION_ERROR': [
                "アカウント権限を確認してください",
                "APIアクセス権限を確認してください",
                "Webullサポートに問い合わせてください"
            ],
            'RATE_LIMIT': [
                "API呼び出し頻度を下げてください",
                "待機時間を増やしてください",
                "バッチ処理の使用を検討してください"
            ],
            'SERVER_ERROR': [
                "しばらく待ってから再試行してください",
                "Webullサーバーの状況を確認してください",
                "メンテナンス時間外での実行を検討してください"
            ],
            'UNKNOWN_ERROR': [
                "エラーログを詳細に確認してください",
                "Webullサポートに問い合わせてください",
                "システム管理者に報告してください"
            ]
        }
        
        return recommendations.get(error_category, ["詳細な調査が必要です"])
    
    def _update_error_stats(self, error_category, api_name):
        """エラー統計を更新"""
        try:
            # エラー統計の初期化（初回のみ）
            if not hasattr(self, '_error_stats'):
                self._error_stats = {
                    'total_errors': 0,
                    'error_categories': {},
                    'api_errors': {}
                }
            
            # 統計を更新
            self._error_stats['total_errors'] += 1
            self._error_stats['error_categories'][error_category] = self._error_stats['error_categories'].get(error_category, 0) + 1
            self._error_stats['api_errors'][api_name] = self._error_stats['api_errors'].get(api_name, 0) + 1
            
        except Exception as e:
            self.logger.error(f"エラー統計更新中にエラー発生: {e}")
    
    def get_error_stats(self):
        """エラー統計情報を取得"""
        if not hasattr(self, '_error_stats'):
            return {
                'total_errors': 0,
                'error_categories': {},
                'api_errors': {}
            }
        
        return self._error_stats.copy()
    
    def print_error_stats(self):
        """エラー統計情報を表示"""
        stats = self.get_error_stats()
        
        self.logger.info("=== エラー統計情報 ===")
        self.logger.info(f"総エラー数: {stats['total_errors']}")
        
        if stats['error_categories']:
            self.logger.info("エラーカテゴリ別統計:")
            for category, count in sorted(stats['error_categories'].items(), key=lambda x: x[1], reverse=True):
                self.logger.info(f"  {category}: {count}回")
        
        if stats['api_errors']:
            self.logger.info("API別エラー統計:")
            for api_name, count in sorted(stats['api_errors'].items(), key=lambda x: x[1], reverse=True):
                self.logger.info(f"  {api_name}: {count}回")
        
        self.logger.info("======================")
    
    def check_sdk_compatibility(self):
        """SDK互換性の確認"""
        try:
            self.logger.info("=== SDK互換性チェック開始 ===")
            
            # ステップ1: SDKバージョンの確認
            self._check_sdk_versions()
            
            # ステップ2: APIメソッドの確認
            self._check_api_methods()
            
            # ステップ3: 互換性問題の分析
            self._analyze_compatibility_issues()
            
            # ステップ4: 推奨事項の提示
            self._provide_compatibility_recommendations()
            
            self.logger.info("=== SDK互換性チェック完了 ===")
            
        except Exception as e:
            self.logger.error(f"SDK互換性チェック中にエラー発生: {e}")
    
    def _check_sdk_versions(self):
        """SDKバージョンの確認"""
        try:
            self.logger.info("ステップ1: SDKバージョンの確認")
            
            # 各SDKのバージョンを確認
            sdk_packages = {
                'webull-python-sdk-trade': 'webullsdktrade',
                'webull-python-sdk-core': 'webullsdkcore',
                'webull-python-sdk-trade-events-core': 'webullsdktradeeventscore',
                'webull-python-sdk-mdata': 'webullsdkcore',
                'webull': 'webull'
            }
            
            for package_name, import_name in sdk_packages.items():
                try:
                    module = __import__(import_name)
                    version = getattr(module, '__version__', 'Unknown')
                    self._sdk_compatibility['sdk_versions'][package_name] = version
                    self.logger.info(f"  {package_name}: {version}")
                except ImportError:
                    self._sdk_compatibility['sdk_versions'][package_name] = 'Not Installed'
                    self.logger.warning(f"  {package_name}: Not Installed")
                except Exception as e:
                    self._sdk_compatibility['sdk_versions'][package_name] = f'Error: {e}'
                    self.logger.error(f"  {package_name}: Error - {e}")
            
        except Exception as e:
            self.logger.error(f"SDKバージョン確認中にエラー発生: {e}")
    
    def _check_api_methods(self):
        """APIメソッドの確認"""
        try:
            self.logger.info("ステップ2: APIメソッドの確認")
            
            # 重要なAPIメソッドの存在確認
            api_methods_to_check = {
                'account_v2.get_account_balance': self.api.account_v2,
                'order.place_order_v2': self.api.order,
                'order.get_order_detail': self.api.order,
                'order.get_order_list': self.api.order,
                'order.cancel_order': self.api.order,
                'quote.get_snapshot': self.api.quote,
                'quote.get_history_bars': self.api.quote,
                'quote.get_eod_bars': self.api.quote,
                'quote.get_instrument_id': self.api.quote
            }
            
            for method_name, module in api_methods_to_check.items():
                try:
                    # メソッドの存在確認
                    method_parts = method_name.split('.')
                    current_module = module
                    
                    for part in method_parts[1:]:
                        if hasattr(current_module, part):
                            current_module = getattr(current_module, part)
                        else:
                            raise AttributeError(f"Method {part} not found")
                    
                    self._sdk_compatibility['api_methods'][method_name] = 'Available'
                    self.logger.info(f"  {method_name}: Available")
                    
                except AttributeError as e:
                    self._sdk_compatibility['api_methods'][method_name] = f'Not Available: {e}'
                    self.logger.warning(f"  {method_name}: Not Available - {e}")
                except Exception as e:
                    self._sdk_compatibility['api_methods'][method_name] = f'Error: {e}'
                    self.logger.error(f"  {method_name}: Error - {e}")
            
        except Exception as e:
            self.logger.error(f"APIメソッド確認中にエラー発生: {e}")
    
    def _analyze_compatibility_issues(self):
        """互換性問題の分析"""
        try:
            self.logger.info("ステップ3: 互換性問題の分析")
            
            issues = []
            
            # バージョン互換性の問題をチェック
            version_issues = self._check_version_compatibility()
            issues.extend(version_issues)
            
            # APIメソッドの問題をチェック
            method_issues = self._check_method_compatibility()
            issues.extend(method_issues)
            
            # 設定の問題をチェック
            config_issues = self._check_config_compatibility()
            issues.extend(config_issues)
            
            self._sdk_compatibility['compatibility_issues'] = issues
            
            if issues:
                self.logger.warning(f"互換性問題が {len(issues)} 件見つかりました:")
                for i, issue in enumerate(issues, 1):
                    self.logger.warning(f"  {i}. {issue}")
            else:
                self.logger.info("互換性問題は見つかりませんでした")
            
        except Exception as e:
            self.logger.error(f"互換性問題分析中にエラー発生: {e}")
    
    def _check_version_compatibility(self):
        """バージョン互換性の問題をチェック"""
        issues = []
        
        try:
            # 推奨バージョンの定義
            recommended_versions = {
                'webull-python-sdk-trade': '0.1.11',
                'webull-python-sdk-core': '0.1.11',
                'webull-python-sdk-trade-events-core': '0.1.11',
                'webull-python-sdk-mdata': '0.1.11',
                'webull': '0.6.0'
            }
            
            for package, current_version in self._sdk_compatibility['sdk_versions'].items():
                if package in recommended_versions:
                    recommended = recommended_versions[package]
                    if current_version != recommended and current_version != 'Not Installed' and not current_version.startswith('Error'):
                        issues.append(f"{package}: 現在のバージョン {current_version} が推奨バージョン {recommended} と異なります")
            
        except Exception as e:
            issues.append(f"バージョン互換性チェックエラー: {e}")
        
        return issues
    
    def _check_method_compatibility(self):
        """APIメソッド互換性の問題をチェック"""
        issues = []
        
        try:
            # 必須メソッドの定義
            required_methods = [
                'account_v2.get_account_balance',
                'order.place_order_v2',
                'order.get_order_detail',
                'order.get_order_list',
                'order.cancel_order'
            ]
            
            for method in required_methods:
                if method in self._sdk_compatibility['api_methods']:
                    status = self._sdk_compatibility['api_methods'][method]
                    if not status.startswith('Available'):
                        issues.append(f"必須メソッド {method} が利用できません: {status}")
                else:
                    issues.append(f"必須メソッド {method} が見つかりません")
            
        except Exception as e:
            issues.append(f"メソッド互換性チェックエラー: {e}")
        
        return issues
    
    def _check_config_compatibility(self):
        """設定互換性の問題をチェック"""
        issues = []
        
        try:
            # 必須設定の確認
            required_configs = ['app_key', 'app_secret']
            for config in required_configs:
                if not self.config.get(config):
                    issues.append(f"必須設定 {config} が不足しています")
            
            # アカウントタイプの確認
            if self.config.get('account_type') == 'CASH':
                issues.append("キャッシュアカウントでは売却制限があります")
            
        except Exception as e:
            issues.append(f"設定互換性チェックエラー: {e}")
        
        return issues
    
    def _provide_compatibility_recommendations(self):
        """互換性に関する推奨事項を提示"""
        try:
            self.logger.info("ステップ4: 推奨事項の提示")
            
            recommendations = []
            
            # バージョン関連の推奨事項
            version_recs = self._get_version_recommendations()
            recommendations.extend(version_recs)
            
            # メソッド関連の推奨事項
            method_recs = self._get_method_recommendations()
            recommendations.extend(method_recs)
            
            # 設定関連の推奨事項
            config_recs = self._get_config_recommendations()
            recommendations.extend(config_recs)
            
            self._sdk_compatibility['recommendations'] = recommendations
            
            if recommendations:
                self.logger.info("推奨事項:")
                for i, recommendation in enumerate(recommendations, 1):
                    self.logger.info(f"  {i}. {recommendation}")
            else:
                self.logger.info("推奨事項はありません")
            
        except Exception as e:
            self.logger.error(f"推奨事項提示中にエラー発生: {e}")
    
    def _get_version_recommendations(self):
        """バージョン関連の推奨事項を取得"""
        recommendations = []
        
        try:
            # 推奨バージョンの定義
            recommended_versions = {
                'webull-python-sdk-trade': '0.1.11',
                'webull-python-sdk-core': '0.1.11',
                'webull-python-sdk-trade-events-core': '0.1.11',
                'webull-python-sdk-mdata': '0.1.11',
                'webull': '0.6.0'
            }
            
            for package, current_version in self._sdk_compatibility['sdk_versions'].items():
                if package in recommended_versions:
                    recommended = recommended_versions[package]
                    if current_version != recommended and current_version != 'Not Installed' and not current_version.startswith('Error'):
                        recommendations.append(f"{package} をバージョン {recommended} に更新することを推奨します")
            
        except Exception as e:
            recommendations.append(f"バージョン推奨事項の取得エラー: {e}")
        
        return recommendations
    
    def _get_method_recommendations(self):
        """メソッド関連の推奨事項を取得"""
        recommendations = []
        
        try:
            # 利用できないメソッドに対する推奨事項
            unavailable_methods = []
            for method, status in self._sdk_compatibility['api_methods'].items():
                if not status.startswith('Available'):
                    unavailable_methods.append(method)
            
            if unavailable_methods:
                recommendations.append(f"利用できないメソッドがあります: {', '.join(unavailable_methods)}")
                recommendations.append("SDKの更新または代替メソッドの使用を検討してください")
            
        except Exception as e:
            recommendations.append(f"メソッド推奨事項の取得エラー: {e}")
        
        return recommendations
    
    def _get_config_recommendations(self):
        """設定関連の推奨事項を取得"""
        recommendations = []
        
        try:
            # アカウントタイプの推奨事項
            if self.config.get('account_type') == 'CASH':
                recommendations.append("マージンアカウントへの変更を検討してください（売却制限の回避）")
            
            # 認証情報の推奨事項
            if not self.config.get('app_key') or not self.config.get('app_secret'):
                recommendations.append("API認証情報の設定を確認してください")
            
        except Exception as e:
            recommendations.append(f"設定推奨事項の取得エラー: {e}")
        
        return recommendations
    
    def get_sdk_compatibility_info(self):
        """SDK互換性情報を取得"""
        return self._sdk_compatibility.copy()
    
    def print_sdk_compatibility_info(self):
        """SDK互換性情報を表示"""
        info = self.get_sdk_compatibility_info()
        
        self.logger.info("=== SDK互換性情報 ===")
        
        # SDKバージョン情報
        self.logger.info("SDKバージョン:")
        for package, version in info['sdk_versions'].items():
            self.logger.info(f"  {package}: {version}")
        
        # APIメソッド情報
        self.logger.info("APIメソッド:")
        for method, status in info['api_methods'].items():
            self.logger.info(f"  {method}: {status}")
        
        # 互換性問題
        if info['compatibility_issues']:
            self.logger.info("互換性問題:")
            for issue in info['compatibility_issues']:
                self.logger.info(f"  - {issue}")
        
        # 推奨事項
        if info['recommendations']:
            self.logger.info("推奨事項:")
            for recommendation in info['recommendations']:
                self.logger.info(f"  - {recommendation}")
        
        self.logger.info("=====================")
    
    def save_trades_to_csv(self, trades):
        """取引履歴をCSVに保存（詳細版）"""
        try:
            if not trades:
                return
            
            # 取引詳細の強化
            detailed_trades = []
            for trade in trades:
                detailed_trade = self._enhance_trade_details(trade)
                detailed_trades.append(detailed_trade)
            
            # 既存の取引履歴を読み込み
            existing_trades = []
            if os.path.exists('data/trades.csv'):
                try:
                    with open('data/trades.csv', 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        existing_trades = list(reader)
                except Exception as e:
                    self.logger.warning(f"既存の取引履歴読み込みエラー: {e}")
            
            # 新しい取引を追加
            all_trades = existing_trades + detailed_trades
            
            # データ検証を実行
            validated_trades = []
            for trade in all_trades:
                validated_trade = self._validate_trade_data(trade)
                validated_trades.append(validated_trade)
            
            # CSVに保存
            with open('data/trades.csv', 'w', newline='', encoding='utf-8') as f:
                if validated_trades:
                    fieldnames = validated_trades[0].keys()
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(validated_trades)
            
            self.logger.info(f"✅ 詳細取引履歴をCSVに保存完了: {len(detailed_trades)}件の取引を追加")
            
        except Exception as e:
            self.logger.error(f"取引履歴のCSV保存中にエラー発生: {e}")
            # フォールバック: 元の方法で保存
            try:
                df = pd.DataFrame(trades)
                df['timestamp'] = datetime.now()
                df.to_csv('data/trades.csv', mode='a', header=not os.path.exists('data/trades.csv'), index=False)
                self.logger.info("フォールバック: 基本取引履歴をCSVに保存しました")
            except Exception as fallback_error:
                self.logger.error(f"フォールバック保存も失敗: {fallback_error}")
    
    def _validate_trade_data(self, trade):
        """取引データの検証と修正"""
        try:
            validated_trade = trade.copy()
            
            # 1. 必須フィールドの確認
            required_fields = ['symbol', 'action', 'quantity', 'timestamp']
            for field in required_fields:
                if field not in validated_trade or not validated_trade[field]:
                    if field == 'timestamp':
                        validated_trade[field] = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                    elif field == 'quantity':
                        validated_trade[field] = '0'
                    else:
                        validated_trade[field] = ''
            
            # 2. 数値フィールドの型変換
            numeric_fields = ['quantity', 'estimated_value', 'current_price', 'target_quantity', 
                            'current_quantity', 'remaining_cash_before', 'remaining_cash_after']
            for field in numeric_fields:
                if field in validated_trade:
                    try:
                        value = validated_trade[field]
                        if value and str(value).strip():
                            # 数値に変換可能かチェック
                            float_val = float(value)
                            if field in ['target_quantity', 'current_quantity']:
                                validated_trade[field] = str(int(float_val))
                            else:
                                validated_trade[field] = str(float_val)
                        else:
                            validated_trade[field] = '0.0'
                    except (ValueError, TypeError):
                        self.logger.warning(f"数値フィールド '{field}' の変換エラー: {validated_trade[field]}")
                        validated_trade[field] = '0.0'
            
            # 3. actionフィールドの正規化
            if 'action' in validated_trade:
                action = str(validated_trade['action']).upper().strip()
                if action not in ['BUY', 'SELL']:
                    self.logger.warning(f"無効なaction値: {action} → BUYに修正")
                    validated_trade['action'] = 'BUY'
                else:
                    validated_trade['action'] = action
            
            # 4. symbolフィールドの正規化
            if 'symbol' in validated_trade:
                symbol = str(validated_trade['symbol']).strip().upper()
                validated_trade['symbol'] = symbol
            
            # 5. タイムスタンプの標準化
            if 'timestamp' in validated_trade:
                timestamp = validated_trade['timestamp']
                if timestamp and str(timestamp).strip():
                    try:
                        # 既存のフォーマットを確認
                        parsed = False
                        for fmt in ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S']:
                            try:
                                datetime.strptime(str(timestamp), fmt)
                                parsed = True
                                break
                            except ValueError:
                                continue
                        
                        if not parsed:
                            # 数値が混入している場合
                            try:
                                float(timestamp)
                                self.logger.warning(f"タイムスタンプが数値: {timestamp} → 現在時刻に修正")
                                validated_trade['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                            except ValueError:
                                self.logger.warning(f"未対応のタイムスタンプ: {timestamp} → 現在時刻に修正")
                                validated_trade['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                    except Exception as e:
                        self.logger.warning(f"タイムスタンプ解析エラー: {timestamp} → 現在時刻に修正")
                        validated_trade['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                else:
                    validated_trade['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            
            return validated_trade
            
        except Exception as e:
            self.logger.error(f"取引データ検証中にエラー発生: {e}")
            return trade
    
    def _enhance_trade_details(self, trade):
        """取引詳細の強化"""
        try:
            enhanced_trade = trade.copy()
            
            # 基本情報の追加
            enhanced_trade['trade_id'] = self._generate_trade_id()
            enhanced_trade['session_id'] = self._get_session_id()
            enhanced_trade['execution_status'] = trade.get('execution_status', 'UNKNOWN')
            enhanced_trade['order_type'] = trade.get('order_type', 'LIMIT')
            enhanced_trade['time_in_force'] = trade.get('time_in_force', 'DAY')
            
            # 価格情報の詳細化
            enhanced_trade['limit_price'] = trade.get('limit_price', '')
            enhanced_trade['market_price'] = trade.get('current_price', '')
            enhanced_trade['execution_price'] = trade.get('execution_price', trade.get('current_price', ''))
            enhanced_trade['price_difference'] = self._calculate_price_difference(
                trade.get('limit_price'), trade.get('current_price')
            )
            
            # 数量情報の詳細化
            enhanced_trade['requested_quantity'] = trade.get('quantity', 0)
            enhanced_trade['executed_quantity'] = trade.get('executed_quantity', trade.get('quantity', 0))
            enhanced_trade['remaining_quantity'] = trade.get('remaining_quantity', 0)
            enhanced_trade['fill_percentage'] = self._calculate_fill_percentage(
                trade.get('quantity', 0), trade.get('executed_quantity', 0)
            )
            
            # 金額情報の詳細化
            enhanced_trade['total_value'] = trade.get('estimated_value', 0)
            enhanced_trade['executed_value'] = trade.get('executed_value', trade.get('estimated_value', 0))
            enhanced_trade['commission'] = trade.get('commission', 0)
            enhanced_trade['fees'] = trade.get('fees', 0)
            enhanced_trade['net_value'] = self._calculate_net_value(
                trade.get('executed_value', 0), trade.get('commission', 0), trade.get('fees', 0)
            )
            
            # ポートフォリオ情報の詳細化
            enhanced_trade['target_allocation'] = trade.get('target_allocation', '')
            enhanced_trade['current_allocation'] = trade.get('current_allocation', '')
            enhanced_trade['allocation_difference'] = self._calculate_allocation_difference(
                trade.get('target_allocation', 0), trade.get('current_allocation', 0)
            )
            
            # 市場情報の詳細化
            enhanced_trade['market_conditions'] = self._get_market_conditions()
            enhanced_trade['volatility'] = trade.get('volatility', '')
            enhanced_trade['volume'] = trade.get('volume', '')
            
            # タイミング情報の詳細化
            enhanced_trade['order_placed_time'] = trade.get('order_placed_time', trade.get('timestamp', ''))
            enhanced_trade['order_filled_time'] = trade.get('order_filled_time', '')
            enhanced_trade['execution_duration'] = self._calculate_execution_duration(
                trade.get('order_placed_time'), trade.get('order_filled_time')
            )
            
            # エラー情報の詳細化
            enhanced_trade['error_code'] = trade.get('error_code', '')
            enhanced_trade['error_message'] = trade.get('error_message', '')
            enhanced_trade['retry_count'] = trade.get('retry_count', 0)
            
            # パフォーマンス情報の詳細化
            enhanced_trade['slippage'] = trade.get('slippage', 0)
            enhanced_trade['impact_cost'] = trade.get('impact_cost', 0)
            enhanced_trade['execution_quality'] = self._calculate_execution_quality(
                trade.get('slippage', 0), trade.get('impact_cost', 0)
            )
            
            # メタデータの追加
            enhanced_trade['api_version'] = self._get_api_version()
            enhanced_trade['sdk_version'] = self._get_sdk_version()
            enhanced_trade['config_version'] = self._get_config_version()
            
            return enhanced_trade
            
        except Exception as e:
            self.logger.error(f"取引詳細の強化中にエラー発生: {e}")
            return trade
    
    def _generate_trade_id(self):
        """取引IDの生成"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
            random_suffix = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=4))
            return f"TRADE_{timestamp}_{random_suffix}"
        except Exception as e:
            self.logger.error(f"取引ID生成中にエラー発生: {e}")
            return f"TRADE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    def _get_session_id(self):
        """セッションIDの取得"""
        try:
            if not hasattr(self, '_session_id'):
                self._session_id = f"SESSION_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            return self._session_id
        except Exception as e:
            self.logger.error(f"セッションID取得中にエラー発生: {e}")
            return "UNKNOWN_SESSION"
    
    def _calculate_price_difference(self, limit_price, market_price):
        """価格差の計算"""
        try:
            if limit_price and market_price:
                limit = float(limit_price)
                market = float(market_price)
                return round(market - limit, 4)
            return 0
        except Exception as e:
            self.logger.error(f"価格差計算中にエラー発生: {e}")
            return 0
    
    def _calculate_fill_percentage(self, requested, executed):
        """約定率の計算"""
        try:
            if requested and executed:
                requested = float(requested)
                executed = float(executed)
                if requested > 0:
                    return round((executed / requested) * 100, 2)
            return 0
        except Exception as e:
            self.logger.error(f"約定率計算中にエラー発生: {e}")
            return 0
    
    def _calculate_net_value(self, executed_value, commission, fees):
        """純額の計算"""
        try:
            executed = float(executed_value or 0)
            comm = float(commission or 0)
            fee = float(fees or 0)
            return round(executed - comm - fee, 2)
        except Exception as e:
            self.logger.error(f"純額計算中にエラー発生: {e}")
            return executed_value
    
    def _calculate_allocation_difference(self, target, current):
        """配分差の計算"""
        try:
            if target and current:
                target_val = float(target)
                current_val = float(current)
                return round(target_val - current_val, 2)
            return 0
        except Exception as e:
            self.logger.error(f"配分差計算中にエラー発生: {e}")
            return 0
    
    def _get_market_conditions(self):
        """市場状況の取得"""
        try:
            # 簡単な市場状況の判定（実際の実装ではより詳細な分析が必要）
            current_hour = datetime.now().hour
            if 9 <= current_hour <= 16:
                return "REGULAR_HOURS"
            elif 4 <= current_hour <= 9 or 16 <= current_hour <= 20:
                return "EXTENDED_HOURS"
            else:
                return "AFTER_HOURS"
        except Exception as e:
            self.logger.error(f"市場状況取得中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _calculate_execution_duration(self, placed_time, filled_time):
        """実行時間の計算"""
        try:
            if placed_time and filled_time:
                placed = datetime.fromisoformat(placed_time.replace('Z', '+00:00'))
                filled = datetime.fromisoformat(filled_time.replace('Z', '+00:00'))
                duration = (filled - placed).total_seconds()
                return round(duration, 2)
            return 0
        except Exception as e:
            self.logger.error(f"実行時間計算中にエラー発生: {e}")
            return 0
    
    def _calculate_execution_quality(self, slippage, impact_cost):
        """実行品質の計算"""
        try:
            # 簡単な品質スコア（0-100）
            slippage_score = max(0, 100 - abs(float(slippage or 0)) * 10)
            impact_score = max(0, 100 - abs(float(impact_cost or 0)) * 5)
            return round((slippage_score + impact_score) / 2, 1)
        except Exception as e:
            self.logger.error(f"実行品質計算中にエラー発生: {e}")
            return 50
    
    def _get_api_version(self):
        """APIバージョンの取得"""
        try:
            return "v2"  # 現在使用しているAPIバージョン
        except Exception as e:
            self.logger.error(f"APIバージョン取得中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _get_sdk_version(self):
        """SDKバージョンの取得"""
        try:
            sdk_info = self.get_sdk_compatibility_info()
            versions = sdk_info.get('sdk_versions', {})
            return versions.get('webull-python-sdk-trade', 'UNKNOWN')
        except Exception as e:
            self.logger.error(f"SDKバージョン取得中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _get_config_version(self):
        """設定バージョンの取得"""
        try:
            return self.config.get('version', '1.0')
        except Exception as e:
            self.logger.error(f"設定バージョン取得中にエラー発生: {e}")
            return "UNKNOWN"
    
    def analyze_trade_history(self, days=30):
        """取引履歴の分析"""
        try:
            self.logger.info(f"=== 取引履歴分析開始（過去{days}日間） ===")
            
            # 取引履歴の読み込み
            trades = self.load_trade_history()
            if not trades:
                self.logger.warning("取引履歴が見つかりません")
                return None
            
            # 日付フィルタリング
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_trades = []
            
            for trade in trades:
                try:
                    trade_date = datetime.fromisoformat(trade.get('timestamp', '').replace('Z', '+00:00'))
                    if trade_date >= cutoff_date:
                        recent_trades.append(trade)
                except Exception as e:
                    self.logger.warning(f"取引日付の解析エラー: {e}")
            
            if not recent_trades:
                self.logger.warning(f"過去{days}日間の取引履歴が見つかりません")
                return None
            
            # 分析の実行
            analysis = {
                'period': f"過去{days}日間",
                'total_trades': len(recent_trades),
                'trade_summary': self._analyze_trade_summary(recent_trades),
                'performance_metrics': self._analyze_performance_metrics(recent_trades),
                'risk_metrics': self._analyze_risk_metrics(recent_trades),
                'execution_quality': self._analyze_execution_quality(recent_trades),
                'portfolio_changes': self._analyze_portfolio_changes(recent_trades),
                'error_analysis': self._analyze_errors(recent_trades)
            }
            
            # 分析結果の表示
            self._display_trade_analysis(analysis)
            
            self.logger.info("=== 取引履歴分析完了 ===")
            return analysis
            
        except Exception as e:
            self.logger.error(f"取引履歴分析中にエラー発生: {e}")
            return None
    
    def load_trade_history(self):
        """取引履歴の読み込み"""
        try:
            if not os.path.exists('data/trades.csv'):
                return []
            
            trades = []
            with open('data/trades.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                trades = list(reader)
            
            self.logger.info(f"取引履歴読み込み完了: {len(trades)}件")
            return trades
            
        except Exception as e:
            self.logger.error(f"取引履歴読み込み中にエラー発生: {e}")
            return []
    
    def _analyze_trade_summary(self, trades):
        """取引サマリーの分析"""
        try:
            summary = {
                'buy_trades': 0,
                'sell_trades': 0,
                'total_volume': 0,
                'total_value': 0,
                'successful_trades': 0,
                'failed_trades': 0,
                'symbols_traded': set(),
                'sessions': set()
            }
            
            for trade in trades:
                action = trade.get('action', '').upper()
                if action == 'BUY':
                    summary['buy_trades'] += 1
                elif action == 'SELL':
                    summary['sell_trades'] += 1
                
                quantity = float(trade.get('quantity', 0))
                summary['total_volume'] += quantity
                
                value = float(trade.get('estimated_value', 0))
                summary['total_value'] += value
                
                status = trade.get('execution_status', '').upper()
                if status in ['FILLED', 'SUCCESS']:
                    summary['successful_trades'] += 1
                elif status in ['FAILED', 'REJECTED', 'CANCELLED']:
                    summary['failed_trades'] += 1
                
                symbol = trade.get('symbol', '')
                if symbol:
                    summary['symbols_traded'].add(symbol)
                
                session = trade.get('session_id', '')
                if session:
                    summary['sessions'].add(session)
            
            # セットをリストに変換
            summary['symbols_traded'] = list(summary['symbols_traded'])
            summary['sessions'] = list(summary['sessions'])
            
            return summary
            
        except Exception as e:
            self.logger.error(f"取引サマリー分析中にエラー発生: {e}")
            return {}
    
    def _analyze_performance_metrics(self, trades):
        """パフォーマンス指標の分析"""
        try:
            metrics = {
                'total_return': 0,
                'average_execution_quality': 0,
                'fill_rate': 0,
                'average_slippage': 0,
                'total_commission': 0,
                'total_fees': 0
            }
            
            total_quality = 0
            quality_count = 0
            total_fill_rate = 0
            fill_count = 0
            total_slippage = 0
            slippage_count = 0
            
            for trade in trades:
                # 実行品質
                quality = float(trade.get('execution_quality', 0))
                if quality > 0:
                    total_quality += quality
                    quality_count += 1
                
                # 約定率
                fill_rate = float(trade.get('fill_percentage', 0))
                if fill_rate > 0:
                    total_fill_rate += fill_rate
                    fill_count += 1
                
                # スリッページ
                slippage = float(trade.get('slippage', 0))
                if slippage != 0:
                    total_slippage += abs(slippage)
                    slippage_count += 1
                
                # 手数料
                commission = float(trade.get('commission', 0))
                fees = float(trade.get('fees', 0))
                metrics['total_commission'] += commission
                metrics['total_fees'] += fees
            
            # 平均値の計算
            if quality_count > 0:
                metrics['average_execution_quality'] = round(total_quality / quality_count, 2)
            if fill_count > 0:
                metrics['fill_rate'] = round(total_fill_rate / fill_count, 2)
            if slippage_count > 0:
                metrics['average_slippage'] = round(total_slippage / slippage_count, 4)
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"パフォーマンス指標分析中にエラー発生: {e}")
            return {}
    
    def _analyze_risk_metrics(self, trades):
        """リスク指標の分析"""
        try:
            metrics = {
                'max_drawdown': 0,
                'volatility': 0,
                'sharpe_ratio': 0,
                'win_rate': 0,
                'average_win': 0,
                'average_loss': 0
            }
            
            # 価格変動の追跡
            price_changes = []
            wins = 0
            losses = 0
            total_win = 0
            total_loss = 0
            
            for trade in trades:
                price_diff = float(trade.get('price_difference', 0))
                if price_diff != 0:
                    price_changes.append(price_diff)
                    
                    if price_diff > 0:
                        wins += 1
                        total_win += price_diff
                    else:
                        losses += 1
                        total_loss += abs(price_diff)
            
            # リスク指標の計算
            if price_changes:
                metrics['volatility'] = round(np.std(price_changes), 4)
                metrics['max_drawdown'] = round(min(price_changes), 4)
                
                total_trades = wins + losses
                if total_trades > 0:
                    metrics['win_rate'] = round((wins / total_trades) * 100, 2)
                
                if wins > 0:
                    metrics['average_win'] = round(total_win / wins, 4)
                if losses > 0:
                    metrics['average_loss'] = round(total_loss / losses, 4)
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"リスク指標分析中にエラー発生: {e}")
            return {}
    
    def _analyze_execution_quality(self, trades):
        """実行品質の分析"""
        try:
            quality_metrics = {
                'execution_speed': {},
                'price_improvement': {},
                'market_impact': {},
                'timing_analysis': {}
            }
            
            execution_times = []
            price_improvements = []
            market_impacts = []
            
            for trade in trades:
                # 実行時間
                duration = float(trade.get('execution_duration', 0))
                if duration > 0:
                    execution_times.append(duration)
                
                # 価格改善
                price_diff = float(trade.get('price_difference', 0))
                if price_diff > 0:
                    price_improvements.append(price_diff)
                
                # 市場インパクト
                impact = float(trade.get('impact_cost', 0))
                if impact != 0:
                    market_impacts.append(abs(impact))
            
            # 統計計算
            if execution_times:
                quality_metrics['execution_speed'] = {
                    'average': round(np.mean(execution_times), 2),
                    'median': round(np.median(execution_times), 2),
                    'min': round(min(execution_times), 2),
                    'max': round(max(execution_times), 2)
                }
            
            if price_improvements:
                quality_metrics['price_improvement'] = {
                    'total_improvement': round(sum(price_improvements), 4),
                    'average_improvement': round(np.mean(price_improvements), 4),
                    'improvement_count': len(price_improvements)
                }
            
            if market_impacts:
                quality_metrics['market_impact'] = {
                    'average_impact': round(np.mean(market_impacts), 4),
                    'max_impact': round(max(market_impacts), 4)
                }
            
            return quality_metrics
            
        except Exception as e:
            self.logger.error(f"実行品質分析中にエラー発生: {e}")
            return {}
    
    def _analyze_portfolio_changes(self, trades):
        """ポートフォリオ変更の分析"""
        try:
            changes = {
                'allocation_changes': {},
                'position_changes': {},
                'cash_flow': 0,
                'rebalancing_frequency': 0
            }
            
            total_cash_flow = 0
            rebalancing_sessions = set()
            
            for trade in trades:
                action = trade.get('action', '').upper()
                value = float(trade.get('estimated_value', 0))
                symbol = trade.get('symbol', '')
                session = trade.get('session_id', '')
                
                # キャッシュフロー
                if action == 'BUY':
                    total_cash_flow -= value
                elif action == 'SELL':
                    total_cash_flow += value
                
                # セッション追跡
                if session:
                    rebalancing_sessions.add(session)
                
                # 銘柄別変更
                if symbol:
                    if symbol not in changes['position_changes']:
                        changes['position_changes'][symbol] = {'buys': 0, 'sells': 0, 'net_change': 0}
                    
                    if action == 'BUY':
                        changes['position_changes'][symbol]['buys'] += 1
                        changes['position_changes'][symbol]['net_change'] += 1
                    elif action == 'SELL':
                        changes['position_changes'][symbol]['sells'] += 1
                        changes['position_changes'][symbol]['net_change'] -= 1
            
            changes['cash_flow'] = round(total_cash_flow, 2)
            changes['rebalancing_frequency'] = len(rebalancing_sessions)
            
            return changes
            
        except Exception as e:
            self.logger.error(f"ポートフォリオ変更分析中にエラー発生: {e}")
            return {}
    
    def _analyze_errors(self, trades):
        """エラー分析"""
        try:
            error_analysis = {
                'total_errors': 0,
                'error_types': {},
                'error_frequency': {},
                'recovery_rate': 0
            }
            
            total_trades = len(trades)
            error_trades = 0
            recovered_trades = 0
            
            for trade in trades:
                error_code = trade.get('error_code', '')
                error_message = trade.get('error_message', '')
                retry_count = int(trade.get('retry_count', 0))
                
                if error_code or error_message:
                    error_trades += 1
                    error_analysis['total_errors'] += 1
                    
                    # エラータイプの分類
                    error_type = self._categorize_trade_error(error_code, error_message)
                    error_analysis['error_types'][error_type] = error_analysis['error_types'].get(error_type, 0) + 1
                    
                    # リトライ回数
                    if retry_count > 0:
                        error_analysis['error_frequency'][f'{retry_count}_retries'] = error_analysis['error_frequency'].get(f'{retry_count}_retries', 0) + 1
                    
                    # 回復率（最終的に成功したか）
                    status = trade.get('execution_status', '').upper()
                    if status in ['FILLED', 'SUCCESS']:
                        recovered_trades += 1
            
            if error_trades > 0:
                error_analysis['recovery_rate'] = round((recovered_trades / error_trades) * 100, 2)
            
            return error_analysis
            
        except Exception as e:
            self.logger.error(f"エラー分析中にエラー発生: {e}")
            return {}
    
    def _categorize_trade_error(self, error_code, error_message):
        """取引エラーの分類"""
        try:
            error_text = f"{error_code} {error_message}".upper()
            
            if 'INSUFFICIENT_FUNDS' in error_text:
                return 'INSUFFICIENT_FUNDS'
            elif 'INVALID_SYMBOL' in error_text:
                return 'INVALID_SYMBOL'
            elif 'RATE_LIMIT' in error_text:
                return 'RATE_LIMIT'
            elif 'CASH_ACCOUNT' in error_text:
                return 'CASH_ACCOUNT_RESTRICTION'
            elif 'TIMEOUT' in error_text:
                return 'TIMEOUT'
            elif 'NETWORK' in error_text:
                return 'NETWORK_ERROR'
            else:
                return 'OTHER_ERROR'
                
        except Exception as e:
            self.logger.error(f"エラー分類中にエラー発生: {e}")
            return 'UNKNOWN_ERROR'
    
    def _display_trade_analysis(self, analysis):
        """取引分析結果の表示"""
        try:
            self.logger.info("=== 取引履歴分析結果 ===")
            
            # 基本サマリー
            summary = analysis.get('trade_summary', {})
            self.logger.info(f"📊 取引サマリー ({analysis.get('period', '')})")
            self.logger.info(f"  総取引数: {summary.get('total_trades', 0)}")
            self.logger.info(f"  買い注文: {summary.get('buy_trades', 0)}")
            self.logger.info(f"  売り注文: {summary.get('sell_trades', 0)}")
            self.logger.info(f"  成功取引: {summary.get('successful_trades', 0)}")
            self.logger.info(f"  失敗取引: {summary.get('failed_trades', 0)}")
            self.logger.info(f"  取引銘柄数: {len(summary.get('symbols_traded', []))}")
            self.logger.info(f"  リバランシングセッション数: {len(summary.get('sessions', []))}")
            
            # パフォーマンス指標
            performance = analysis.get('performance_metrics', {})
            self.logger.info(f"📈 パフォーマンス指標")
            self.logger.info(f"  平均実行品質: {performance.get('average_execution_quality', 0)}/100")
            self.logger.info(f"  平均約定率: {performance.get('fill_rate', 0)}%")
            self.logger.info(f"  平均スリッページ: {performance.get('average_slippage', 0)}")
            self.logger.info(f"  総手数料: ${performance.get('total_commission', 0):.2f}")
            self.logger.info(f"  総手数料: ${performance.get('total_fees', 0):.2f}")
            
            # リスク指標
            risk = analysis.get('risk_metrics', {})
            self.logger.info(f"⚠️ リスク指標")
            self.logger.info(f"  勝率: {risk.get('win_rate', 0)}%")
            self.logger.info(f"  平均利益: {risk.get('average_win', 0)}")
            self.logger.info(f"  平均損失: {risk.get('average_loss', 0)}")
            self.logger.info(f"  ボラティリティ: {risk.get('volatility', 0)}")
            
            # エラー分析
            errors = analysis.get('error_analysis', {})
            self.logger.info(f"🚨 エラー分析")
            self.logger.info(f"  総エラー数: {errors.get('total_errors', 0)}")
            self.logger.info(f"  エラー回復率: {errors.get('recovery_rate', 0)}%")
            
            if errors.get('error_types'):
                self.logger.info("  エラータイプ:")
                for error_type, count in errors['error_types'].items():
                    self.logger.info(f"    {error_type}: {count}回")
            
            self.logger.info("========================")
            
        except Exception as e:
            self.logger.error(f"分析結果表示中にエラー発生: {e}")
    
    def track_trade_results(self, trade_id=None, session_id=None, days=7):
        """取引結果の追跡"""
        try:
            self.logger.info("=== 取引結果追跡開始 ===")
            
            # 追跡対象の特定
            if trade_id:
                self.logger.info(f"特定取引の追跡: {trade_id}")
                results = self._track_specific_trade(trade_id)
            elif session_id:
                self.logger.info(f"セッション全体の追跡: {session_id}")
                results = self._track_session_results(session_id)
            else:
                self.logger.info(f"最近{days}日間の取引結果追跡")
                results = self._track_recent_trades(days)
            
            if results:
                self._display_trade_results(results)
                self._save_trade_results(results)
            
            self.logger.info("=== 取引結果追跡完了 ===")
            return results
            
        except Exception as e:
            self.logger.error(f"取引結果追跡中にエラー発生: {e}")
            return None
    
    def _track_specific_trade(self, trade_id):
        """特定取引の追跡"""
        try:
            # 取引履歴から該当取引を検索
            trades = self.load_trade_history()
            target_trade = None
            
            for trade in trades:
                if trade.get('trade_id') == trade_id:
                    target_trade = trade
                    break
            
            if not target_trade:
                self.logger.warning(f"取引ID {trade_id} が見つかりません")
                return None
            
            # 取引結果の詳細分析
            result = {
                'trade_id': trade_id,
                'trade_details': target_trade,
                'execution_analysis': self._analyze_trade_execution(target_trade),
                'performance_impact': self._analyze_trade_performance_impact(target_trade),
                'risk_assessment': self._analyze_trade_risk(target_trade),
                'comparison_analysis': self._compare_trade_with_benchmark(target_trade)
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"特定取引追跡中にエラー発生: {e}")
            return None
    
    def _track_session_results(self, session_id):
        """セッション全体の結果追跡"""
        try:
            # セッション内の全取引を取得
            trades = self.load_trade_history()
            session_trades = []
            
            for trade in trades:
                if trade.get('session_id') == session_id:
                    session_trades.append(trade)
            
            if not session_trades:
                self.logger.warning(f"セッションID {session_id} の取引が見つかりません")
                return None
            
            # セッション全体の分析
            result = {
                'session_id': session_id,
                'total_trades': len(session_trades),
                'trades': session_trades,
                'session_summary': self._analyze_session_summary(session_trades),
                'execution_timeline': self._analyze_session_timeline(session_trades),
                'portfolio_impact': self._analyze_session_portfolio_impact(session_trades),
                'success_rate': self._calculate_session_success_rate(session_trades)
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"セッション結果追跡中にエラー発生: {e}")
            return None
    
    def _track_recent_trades(self, days):
        """最近の取引結果追跡"""
        try:
            # 最近の取引を取得
            trades = self.load_trade_history()
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_trades = []
            
            for trade in trades:
                try:
                    timestamp = trade.get('timestamp', '')
                    if not timestamp:
                        continue
                    
                    # 複数の日付フォーマットに対応
                    trade_date = None
                    try:
                        # ISO形式
                        trade_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    except ValueError:
                        try:
                            # 標準的な日付形式
                            trade_date = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S.%f')
                        except ValueError:
                            try:
                                # 日付のみ
                                trade_date = datetime.strptime(timestamp, '%Y-%m-%d')
                            except ValueError:
                                self.logger.warning(f"未対応の日付フォーマット: {timestamp}")
                                continue
                    
                    if trade_date >= cutoff_date:
                        recent_trades.append(trade)
                        
                except Exception as e:
                    self.logger.warning(f"取引日付の解析エラー: {e}")
            
            if not recent_trades:
                self.logger.warning(f"過去{days}日間の取引が見つかりません")
                return None
            
            # 最近の取引の分析
            result = {
                'period': f"過去{days}日間",
                'total_trades': len(recent_trades),
                'trades': recent_trades,
                'trend_analysis': self._analyze_trade_trends(recent_trades),
                'performance_summary': self._analyze_trade_summary(recent_trades),
                'risk_metrics': self._analyze_risk_metrics(recent_trades),
                'improvement_suggestions': self._generate_improvement_suggestions(recent_trades)
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"最近の取引追跡中にエラー発生: {e}")
            return None
    
    def _analyze_trade_execution(self, trade):
        """取引実行の詳細分析"""
        try:
            analysis = {
                'execution_speed': {},
                'price_accuracy': {},
                'fill_quality': {},
                'market_impact': {}
            }
            
            # 実行速度の分析
            duration = float(trade.get('execution_duration', 0))
            if duration > 0:
                analysis['execution_speed'] = {
                    'duration_seconds': duration,
                    'speed_rating': self._rate_execution_speed(duration),
                    'comparison_to_average': self._compare_to_average_duration(duration)
                }
            
            # 価格精度の分析
            limit_price = float(trade.get('limit_price', 0))
            execution_price = float(trade.get('execution_price', 0))
            if limit_price > 0 and execution_price > 0:
                price_diff = abs(execution_price - limit_price) / limit_price
                analysis['price_accuracy'] = {
                    'price_difference_percent': round(price_diff * 100, 4),
                    'accuracy_rating': self._rate_price_accuracy(price_diff),
                    'slippage_analysis': self._analyze_slippage(limit_price, execution_price)
                }
            
            # 約定品質の分析
            requested_qty = float(trade.get('requested_quantity', 0))
            executed_qty = float(trade.get('executed_quantity', 0))
            if requested_qty > 0:
                fill_rate = executed_qty / requested_qty
                analysis['fill_quality'] = {
                    'fill_rate': round(fill_rate * 100, 2),
                    'quality_rating': self._rate_fill_quality(fill_rate),
                    'partial_fill_analysis': self._analyze_partial_fill(requested_qty, executed_qty)
                }
            
            # 市場インパクトの分析
            impact_cost = float(trade.get('impact_cost', 0))
            if impact_cost != 0:
                analysis['market_impact'] = {
                    'impact_cost': impact_cost,
                    'impact_rating': self._rate_market_impact(impact_cost),
                    'impact_analysis': self._analyze_market_impact(impact_cost, executed_qty)
                }
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"取引実行分析中にエラー発生: {e}")
            return {}
    
    def _analyze_trade_performance_impact(self, trade):
        """取引のパフォーマンス影響分析"""
        try:
            impact = {
                'immediate_impact': {},
                'portfolio_effect': {},
                'cost_analysis': {},
                'efficiency_metrics': {}
            }
            
            # 即座の影響
            action = trade.get('action', '').upper()
            value = float(trade.get('estimated_value', 0))
            commission = float(trade.get('commission', 0))
            fees = float(trade.get('fees', 0))
            
            if action == 'BUY':
                impact['immediate_impact'] = {
                    'cash_outflow': value,
                    'position_increase': value,
                    'net_cost': value + commission + fees
                }
            elif action == 'SELL':
                impact['immediate_impact'] = {
                    'cash_inflow': value,
                    'position_decrease': value,
                    'net_proceeds': value - commission - fees
                }
            
            # ポートフォリオ効果
            symbol = trade.get('symbol', '')
            if symbol:
                impact['portfolio_effect'] = {
                    'symbol_affected': symbol,
                    'allocation_change': self._calculate_allocation_change(trade),
                    'diversification_impact': self._assess_diversification_impact(trade)
                }
            
            # コスト分析
            total_cost = commission + fees
            impact['cost_analysis'] = {
                'total_cost': total_cost,
                'cost_percentage': round((total_cost / value) * 100, 4) if value > 0 else 0,
                'cost_efficiency': self._rate_cost_efficiency(total_cost, value)
            }
            
            # 効率性指標
            execution_quality = float(trade.get('execution_quality', 0))
            impact['efficiency_metrics'] = {
                'execution_quality_score': execution_quality,
                'efficiency_rating': self._rate_efficiency(execution_quality),
                'improvement_potential': self._calculate_improvement_potential(execution_quality)
            }
            
            return impact
            
        except Exception as e:
            self.logger.error(f"パフォーマンス影響分析中にエラー発生: {e}")
            return {}
    
    def _analyze_trade_risk(self, trade):
        """取引のリスク分析"""
        try:
            risk = {
                'execution_risk': {},
                'market_risk': {},
                'liquidity_risk': {},
                'overall_risk_score': 0
            }
            
            # 実行リスク
            execution_status = trade.get('execution_status', '').upper()
            retry_count = int(trade.get('retry_count', 0))
            
            risk['execution_risk'] = {
                'status_risk': self._assess_status_risk(execution_status),
                'retry_risk': self._assess_retry_risk(retry_count),
                'error_risk': self._assess_error_risk(trade.get('error_code', ''))
            }
            
            # 市場リスク
            volatility = trade.get('volatility', 0)
            market_conditions = trade.get('market_conditions', '')
            
            risk['market_risk'] = {
                'volatility_risk': self._assess_volatility_risk(volatility),
                'timing_risk': self._assess_timing_risk(market_conditions),
                'price_risk': self._assess_price_risk(trade)
            }
            
            # 流動性リスク
            symbol = trade.get('symbol', '')
            volume = trade.get('volume', 0)
            
            risk['liquidity_risk'] = {
                'symbol_liquidity': self._assess_symbol_liquidity(symbol),
                'volume_risk': self._assess_volume_risk(volume),
                'spread_risk': self._assess_spread_risk(trade)
            }
            
            # 総合リスクスコア
            risk['overall_risk_score'] = self._calculate_overall_risk_score(risk)
            
            return risk
            
        except Exception as e:
            self.logger.error(f"リスク分析中にエラー発生: {e}")
            return {}
    
    def _compare_trade_with_benchmark(self, trade):
        """取引とベンチマークの比較"""
        try:
            comparison = {
                'benchmark_performance': {},
                'relative_performance': {},
                'peer_comparison': {},
                'improvement_opportunities': []
            }
            
            # ベンチマークパフォーマンス
            symbol = trade.get('symbol', '')
            if symbol:
                benchmark_data = self._get_benchmark_data(symbol, trade.get('timestamp', ''))
                if benchmark_data:
                    comparison['benchmark_performance'] = {
                        'benchmark_return': benchmark_data.get('return', 0),
                        'benchmark_volatility': benchmark_data.get('volatility', 0),
                        'benchmark_sharpe': benchmark_data.get('sharpe_ratio', 0)
                    }
            
            # 相対パフォーマンス
            execution_quality = float(trade.get('execution_quality', 0))
            comparison['relative_performance'] = {
                'quality_vs_benchmark': self._compare_quality_to_benchmark(execution_quality),
                'cost_vs_benchmark': self._compare_cost_to_benchmark(trade),
                'timing_vs_benchmark': self._compare_timing_to_benchmark(trade)
            }
            
            # ピア比較
            comparison['peer_comparison'] = {
                'similar_trades_analysis': self._analyze_similar_trades(trade),
                'peer_performance': self._get_peer_performance_metrics(trade)
            }
            
            # 改善機会
            comparison['improvement_opportunities'] = self._identify_improvement_opportunities(trade)
            
            return comparison
            
        except Exception as e:
            self.logger.error(f"ベンチマーク比較中にエラー発生: {e}")
            return {}
    
    def _rate_execution_speed(self, duration):
        """実行速度の評価"""
        try:
            if duration <= 5:
                return "EXCELLENT"
            elif duration <= 15:
                return "GOOD"
            elif duration <= 30:
                return "AVERAGE"
            elif duration <= 60:
                return "POOR"
            else:
                return "VERY_POOR"
        except Exception as e:
            self.logger.error(f"実行速度評価中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _rate_price_accuracy(self, price_diff):
        """価格精度の評価"""
        try:
            if price_diff <= 0.001:  # 0.1%以下
                return "EXCELLENT"
            elif price_diff <= 0.005:  # 0.5%以下
                return "GOOD"
            elif price_diff <= 0.01:  # 1%以下
                return "AVERAGE"
            elif price_diff <= 0.02:  # 2%以下
                return "POOR"
            else:
                return "VERY_POOR"
        except Exception as e:
            self.logger.error(f"価格精度評価中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _rate_fill_quality(self, fill_rate):
        """約定品質の評価"""
        try:
            if fill_rate >= 0.95:  # 95%以上
                return "EXCELLENT"
            elif fill_rate >= 0.90:  # 90%以上
                return "GOOD"
            elif fill_rate >= 0.80:  # 80%以上
                return "AVERAGE"
            elif fill_rate >= 0.70:  # 70%以上
                return "POOR"
            else:
                return "VERY_POOR"
        except Exception as e:
            self.logger.error(f"約定品質評価中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _rate_market_impact(self, impact_cost):
        """市場インパクトの評価"""
        try:
            if abs(impact_cost) <= 0.001:  # 0.1%以下
                return "MINIMAL"
            elif abs(impact_cost) <= 0.005:  # 0.5%以下
                return "LOW"
            elif abs(impact_cost) <= 0.01:  # 1%以下
                return "MODERATE"
            elif abs(impact_cost) <= 0.02:  # 2%以下
                return "HIGH"
            else:
                return "VERY_HIGH"
        except Exception as e:
            self.logger.error(f"市場インパクト評価中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _rate_cost_efficiency(self, cost, value):
        """コスト効率の評価"""
        try:
            if value <= 0:
                return "UNKNOWN"
            
            cost_percentage = (cost / value) * 100
            if cost_percentage <= 0.1:  # 0.1%以下
                return "EXCELLENT"
            elif cost_percentage <= 0.25:  # 0.25%以下
                return "GOOD"
            elif cost_percentage <= 0.5:  # 0.5%以下
                return "AVERAGE"
            elif cost_percentage <= 1.0:  # 1%以下
                return "POOR"
            else:
                return "VERY_POOR"
        except Exception as e:
            self.logger.error(f"コスト効率評価中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _rate_efficiency(self, quality_score):
        """効率性の評価"""
        try:
            if quality_score >= 90:
                return "EXCELLENT"
            elif quality_score >= 80:
                return "GOOD"
            elif quality_score >= 70:
                return "AVERAGE"
            elif quality_score >= 60:
                return "POOR"
            else:
                return "VERY_POOR"
        except Exception as e:
            self.logger.error(f"効率性評価中にエラー発生: {e}")
            return "UNKNOWN"
    
    def _display_trade_results(self, results):
        """取引結果の表示"""
        try:
            self.logger.info("=== 取引結果追跡レポート ===")
            
            if 'trade_id' in results:
                # 特定取引の結果
                self._display_specific_trade_results(results)
            elif 'session_id' in results:
                # セッション全体の結果
                self._display_session_results(results)
            else:
                # 最近の取引結果
                self._display_recent_trades_results(results)
            
            self.logger.info("=============================")
            
        except Exception as e:
            self.logger.error(f"取引結果表示中にエラー発生: {e}")
    
    def _display_specific_trade_results(self, results):
        """特定取引結果の表示"""
        try:
            trade = results['trade_details']
            self.logger.info(f"🎯 取引ID: {results['trade_id']}")
            self.logger.info(f"  銘柄: {trade.get('symbol', 'N/A')}")
            self.logger.info(f"  アクション: {trade.get('action', 'N/A')}")
            self.logger.info(f"  数量: {trade.get('quantity', 'N/A')}")
            self.logger.info(f"  価値: ${trade.get('estimated_value', 'N/A')}")
            
            # 実行分析
            execution = results.get('execution_analysis', {})
            if execution:
                self.logger.info("📊 実行分析:")
                if 'execution_speed' in execution:
                    speed = execution['execution_speed']
                    self.logger.info(f"  実行速度: {speed.get('speed_rating', 'N/A')} ({speed.get('duration_seconds', 0)}秒)")
                
                if 'price_accuracy' in execution:
                    accuracy = execution['price_accuracy']
                    self.logger.info(f"  価格精度: {accuracy.get('accuracy_rating', 'N/A')} ({accuracy.get('price_difference_percent', 0)}%)")
                
                if 'fill_quality' in execution:
                    quality = execution['fill_quality']
                    self.logger.info(f"  約定品質: {quality.get('quality_rating', 'N/A')} ({quality.get('fill_rate', 0)}%)")
            
            # パフォーマンス影響
            impact = results.get('performance_impact', {})
            if impact:
                self.logger.info("📈 パフォーマンス影響:")
                if 'cost_analysis' in impact:
                    cost = impact['cost_analysis']
                    self.logger.info(f"  総コスト: ${cost.get('total_cost', 0):.2f} ({cost.get('cost_percentage', 0)}%)")
                    self.logger.info(f"  コスト効率: {cost.get('cost_efficiency', 'N/A')}")
            
            # リスク評価
            risk = results.get('risk_assessment', {})
            if risk:
                self.logger.info("⚠️ リスク評価:")
                self.logger.info(f"  総合リスクスコア: {risk.get('overall_risk_score', 0)}/100")
            
        except Exception as e:
            self.logger.error(f"特定取引結果表示中にエラー発生: {e}")
    
    def _display_session_results(self, results):
        """セッション結果の表示"""
        try:
            self.logger.info(f"🔄 セッションID: {results['session_id']}")
            self.logger.info(f"  総取引数: {results['total_trades']}")
            
            summary = results.get('session_summary', {})
            if summary:
                self.logger.info("📊 セッションサマリー:")
                self.logger.info(f"  成功取引: {summary.get('successful_trades', 0)}")
                self.logger.info(f"  失敗取引: {summary.get('failed_trades', 0)}")
                self.logger.info(f"  成功率: {summary.get('success_rate', 0)}%")
            
            success_rate = results.get('success_rate', 0)
            self.logger.info(f"✅ セッション成功率: {success_rate}%")
            
        except Exception as e:
            self.logger.error(f"セッション結果表示中にエラー発生: {e}")
    
    def _display_recent_trades_results(self, results):
        """最近の取引結果の表示"""
        try:
            self.logger.info(f"📅 期間: {results['period']}")
            self.logger.info(f"  総取引数: {results['total_trades']}")
            
            trends = results.get('trend_analysis', {})
            if trends:
                self.logger.info("📈 トレンド分析:")
                self.logger.info(f"  実行品質トレンド: {trends.get('quality_trend', 'N/A')}")
                self.logger.info(f"  成功率トレンド: {trends.get('success_trend', 'N/A')}")
            
            suggestions = results.get('improvement_suggestions', [])
            if suggestions:
                self.logger.info("💡 改善提案:")
                for i, suggestion in enumerate(suggestions[:5], 1):  # 上位5件を表示
                    self.logger.info(f"  {i}. {suggestion}")
            
        except Exception as e:
            self.logger.error(f"最近の取引結果表示中にエラー発生: {e}")
    
    def _save_trade_results(self, results):
        """取引結果の保存"""
        try:
            # 結果をJSONファイルに保存
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if 'trade_id' in results:
                filename = f"data/trade_results_{results['trade_id']}_{timestamp}.json"
            elif 'session_id' in results:
                filename = f"data/session_results_{results['session_id']}_{timestamp}.json"
            else:
                filename = f"data/recent_trades_results_{timestamp}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False, default=str)
            
            self.logger.info(f"✅ 取引結果を保存: {filename}")
            
        except Exception as e:
            self.logger.error(f"取引結果保存中にエラー発生: {e}")
    
    def _analyze_session_summary(self, trades):
        """セッションサマリーの分析"""
        try:
            summary = {
                'successful_trades': 0,
                'failed_trades': 0,
                'total_value': 0,
                'average_execution_quality': 0
            }
            
            total_quality = 0
            quality_count = 0
            
            for trade in trades:
                status = trade.get('execution_status', '').upper()
                if status in ['FILLED', 'SUCCESS']:
                    summary['successful_trades'] += 1
                else:
                    summary['failed_trades'] += 1
                
                value = float(trade.get('estimated_value', 0))
                summary['total_value'] += value
                
                quality = float(trade.get('execution_quality', 0))
                if quality > 0:
                    total_quality += quality
                    quality_count += 1
            
            if quality_count > 0:
                summary['average_execution_quality'] = round(total_quality / quality_count, 2)
            
            total_trades = summary['successful_trades'] + summary['failed_trades']
            if total_trades > 0:
                summary['success_rate'] = round((summary['successful_trades'] / total_trades) * 100, 2)
            
            return summary
            
        except Exception as e:
            self.logger.error(f"セッションサマリー分析中にエラー発生: {e}")
            return {}
    
    def _calculate_session_success_rate(self, trades):
        """セッション成功率の計算"""
        try:
            successful = 0
            total = len(trades)
            
            for trade in trades:
                status = trade.get('execution_status', '').upper()
                if status in ['FILLED', 'SUCCESS']:
                    successful += 1
            
            return round((successful / total) * 100, 2) if total > 0 else 0
            
        except Exception as e:
            self.logger.error(f"セッション成功率計算中にエラー発生: {e}")
            return 0
    
    def _analyze_trade_trends(self, trades):
        """取引トレンドの分析"""
        try:
            trends = {
                'quality_trend': 'STABLE',
                'success_trend': 'STABLE',
                'volume_trend': 'STABLE'
            }
            
            if len(trades) < 2:
                return trends
            
            # 品質トレンド
            qualities = [float(t.get('execution_quality', 0)) for t in trades if float(t.get('execution_quality', 0)) > 0]
            if len(qualities) >= 2:
                if qualities[-1] > qualities[0] * 1.1:
                    trends['quality_trend'] = 'IMPROVING'
                elif qualities[-1] < qualities[0] * 0.9:
                    trends['quality_trend'] = 'DECLINING'
            
            # 成功率トレンド
            success_rates = []
            for i in range(0, len(trades), max(1, len(trades)//5)):  # 5つの期間に分割
                period_trades = trades[i:i+max(1, len(trades)//5)]
                successful = sum(1 for t in period_trades if t.get('execution_status', '').upper() in ['FILLED', 'SUCCESS'])
                success_rates.append(successful / len(period_trades) if period_trades else 0)
            
            if len(success_rates) >= 2:
                if success_rates[-1] > success_rates[0] * 1.1:
                    trends['success_trend'] = 'IMPROVING'
                elif success_rates[-1] < success_rates[0] * 0.9:
                    trends['success_trend'] = 'DECLINING'
            
            return trends
            
        except Exception as e:
            self.logger.error(f"トレンド分析中にエラー発生: {e}")
            return {}
    
    def _generate_improvement_suggestions(self, trades):
        """改善提案の生成"""
        try:
            suggestions = []
            
            # 成功率が低い場合
            success_rate = self._calculate_overall_success_rate(trades)
            if success_rate < 80:
                suggestions.append("成功率の改善が必要です。エラー分析を確認してください。")
            
            # 実行品質が低い場合
            avg_quality = self._calculate_average_quality(trades)
            if avg_quality < 70:
                suggestions.append("実行品質の向上が必要です。価格設定とタイミングを改善してください。")
            
            # コストが高い場合
            avg_cost_percentage = self._calculate_average_cost_percentage(trades)
            if avg_cost_percentage > 0.5:
                suggestions.append("取引コストの削減が必要です。手数料の見直しを検討してください。")
            
            # スリッページが大きい場合
            avg_slippage = self._calculate_average_slippage(trades)
            if avg_slippage > 0.01:
                suggestions.append("スリッページの削減が必要です。市場状況に応じた注文タイミングを検討してください。")
            
            return suggestions
            
        except Exception as e:
            self.logger.error(f"改善提案生成中にエラー発生: {e}")
            return []
    
    def _calculate_overall_success_rate(self, trades):
        """全体成功率の計算"""
        try:
            successful = sum(1 for t in trades if t.get('execution_status', '').upper() in ['FILLED', 'SUCCESS'])
            return round((successful / len(trades)) * 100, 2) if trades else 0
        except Exception as e:
            self.logger.error(f"全体成功率計算中にエラー発生: {e}")
            return 0
    
    def _calculate_average_quality(self, trades):
        """平均品質の計算"""
        try:
            qualities = [float(t.get('execution_quality', 0)) for t in trades if float(t.get('execution_quality', 0)) > 0]
            return round(sum(qualities) / len(qualities), 2) if qualities else 0
        except Exception as e:
            self.logger.error(f"平均品質計算中にエラー発生: {e}")
            return 0
    
    def _calculate_average_cost_percentage(self, trades):
        """平均コスト率の計算"""
        try:
            cost_percentages = []
            for trade in trades:
                value = float(trade.get('estimated_value', 0))
                commission = float(trade.get('commission', 0))
                fees = float(trade.get('fees', 0))
                if value > 0:
                    cost_percentages.append((commission + fees) / value)
            
            return round(sum(cost_percentages) / len(cost_percentages), 4) if cost_percentages else 0
        except Exception as e:
            self.logger.error(f"平均コスト率計算中にエラー発生: {e}")
            return 0
    
    def _calculate_average_slippage(self, trades):
        """平均スリッページの計算"""
        try:
            slippages = [abs(float(t.get('slippage', 0))) for t in trades if float(t.get('slippage', 0)) != 0]
            return round(sum(slippages) / len(slippages), 4) if slippages else 0
        except Exception as e:
            self.logger.error(f"平均スリッページ計算中にエラー発生: {e}")
            return 0
    
    def analyze_performance(self, period='30d', benchmark='SPY'):
        """包括的なパフォーマンス分析"""
        try:
            self.logger.info("=== パフォーマンス分析開始 ===")
            
            # 分析期間の設定
            analysis_period = self._get_analysis_period(period)
            
            # 取引履歴の取得
            trades = self._get_trades_for_period(analysis_period)
            if not trades:
                self.logger.warning("分析期間内の取引が見つかりません")
                return None
            
            # 包括的なパフォーマンス分析
            performance_analysis = {
                'period': period,
                'analysis_date': datetime.now().isoformat(),
                'trade_performance': self._analyze_trade_performance(trades),
                'portfolio_performance': self._analyze_portfolio_performance(trades),
                'risk_metrics': self._analyze_risk_metrics_comprehensive(trades),
                'execution_quality': self._analyze_execution_quality_comprehensive(trades),
                'cost_analysis': self._analyze_cost_performance(trades),
                'benchmark_comparison': self._compare_with_benchmark(trades, benchmark),
                'performance_attribution': self._analyze_performance_attribution(trades),
                'improvement_recommendations': self._generate_performance_recommendations(trades)
            }
            
            # 分析結果の表示
            self._display_performance_analysis(performance_analysis)
            
            # 結果の保存
            self._save_performance_analysis(performance_analysis)
            
            self.logger.info("=== パフォーマンス分析完了 ===")
            return performance_analysis
            
        except Exception as e:
            self.logger.error(f"パフォーマンス分析中にエラー発生: {e}")
            return None
    
    def _get_analysis_period(self, period):
        """分析期間の取得"""
        try:
            end_date = datetime.now()
            
            if period.endswith('d'):
                days = int(period[:-1])
                start_date = end_date - timedelta(days=days)
            elif period.endswith('w'):
                weeks = int(period[:-1])
                start_date = end_date - timedelta(weeks=weeks)
            elif period.endswith('m'):
                months = int(period[:-1])
                start_date = end_date - timedelta(days=months*30)
            elif period.endswith('y'):
                years = int(period[:-1])
                start_date = end_date - timedelta(days=years*365)
            else:
                # デフォルト: 30日
                start_date = end_date - timedelta(days=30)
            
            return {
                'start_date': start_date,
                'end_date': end_date,
                'period_days': (end_date - start_date).days
            }
            
        except Exception as e:
            self.logger.error(f"分析期間取得中にエラー発生: {e}")
            return {
                'start_date': datetime.now() - timedelta(days=30),
                'end_date': datetime.now(),
                'period_days': 30
            }
    
    def _get_trades_for_period(self, analysis_period):
        """期間内の取引履歴を取得"""
        try:
            trades = self.load_trade_history()
            period_trades = []
            
            for trade in trades:
                try:
                    timestamp = trade.get('timestamp', '')
                    if not timestamp:
                        continue
                    
                    # 複数の日付フォーマットに対応
                    trade_date = None
                    try:
                        # ISO形式
                        trade_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    except ValueError:
                        try:
                            # 標準的な日付形式
                            trade_date = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S.%f')
                        except ValueError:
                            try:
                                # 日付のみ
                                trade_date = datetime.strptime(timestamp, '%Y-%m-%d')
                            except ValueError:
                                self.logger.warning(f"未対応の日付フォーマット: {timestamp}")
                                continue
                    
                    if analysis_period['start_date'] <= trade_date <= analysis_period['end_date']:
                        period_trades.append(trade)
                        
                except Exception as e:
                    self.logger.warning(f"取引日付の解析エラー: {e}")
            
            return period_trades
            
        except Exception as e:
            self.logger.error(f"期間内取引取得中にエラー発生: {e}")
            return []
    
    def _analyze_trade_performance(self, trades):
        """取引パフォーマンスの分析"""
        try:
            performance = {
                'total_trades': len(trades),
                'successful_trades': 0,
                'failed_trades': 0,
                'success_rate': 0,
                'total_volume': 0,
                'total_value': 0,
                'average_trade_size': 0,
                'trade_frequency': 0,
                'execution_times': [],
                'fill_rates': [],
                'price_improvements': []
            }
            
            total_execution_time = 0
            total_fill_rate = 0
            total_price_improvement = 0
            valid_execution_count = 0
            valid_fill_count = 0
            valid_improvement_count = 0
            
            for trade in trades:
                # 成功/失敗の統計
                status = trade.get('execution_status', '').upper()
                if status in ['FILLED', 'SUCCESS']:
                    performance['successful_trades'] += 1
                else:
                    performance['failed_trades'] += 1
                
                # ボリュームと価値
                quantity = float(trade.get('quantity', 0))
                value = float(trade.get('estimated_value', 0))
                performance['total_volume'] += quantity
                performance['total_value'] += value
                
                # 実行時間
                duration = float(trade.get('execution_duration', 0))
                if duration > 0:
                    performance['execution_times'].append(duration)
                    total_execution_time += duration
                    valid_execution_count += 1
                
                # 約定率
                fill_rate = float(trade.get('fill_percentage', 0))
                if fill_rate > 0:
                    performance['fill_rates'].append(fill_rate)
                    total_fill_rate += fill_rate
                    valid_fill_count += 1
                
                # 価格改善
                price_diff = float(trade.get('price_difference', 0))
                if price_diff > 0:
                    performance['price_improvements'].append(price_diff)
                    total_price_improvement += price_diff
                    valid_improvement_count += 1
            
            # 計算値の設定
            total_trades = performance['successful_trades'] + performance['failed_trades']
            if total_trades > 0:
                performance['success_rate'] = round((performance['successful_trades'] / total_trades) * 100, 2)
            
            if total_trades > 0:
                performance['average_trade_size'] = round(performance['total_value'] / total_trades, 2)
            
            # 取引頻度（1日あたり）
            if performance['total_trades'] > 0:
                performance['trade_frequency'] = round(performance['total_trades'] / 30, 2)  # 30日で正規化
            
            # 平均実行時間
            if valid_execution_count > 0:
                performance['average_execution_time'] = round(total_execution_time / valid_execution_count, 2)
            
            # 平均約定率
            if valid_fill_count > 0:
                performance['average_fill_rate'] = round(total_fill_rate / valid_fill_count, 2)
            
            # 平均価格改善
            if valid_improvement_count > 0:
                performance['average_price_improvement'] = round(total_price_improvement / valid_improvement_count, 4)
            
            return performance
            
        except Exception as e:
            self.logger.error(f"取引パフォーマンス分析中にエラー発生: {e}")
            return {}
    
    def _analyze_portfolio_performance(self, trades):
        """ポートフォリオパフォーマンスの分析"""
        try:
            portfolio = {
                'total_return': 0,
                'buy_volume': 0,
                'sell_volume': 0,
                'net_position_change': 0,
                'cash_flow': 0,
                'position_turnover': 0,
                'diversification_metrics': {},
                'allocation_efficiency': {}
            }
            
            total_buy_value = 0
            total_sell_value = 0
            symbols_traded = set()
            allocation_changes = {}
            
            for trade in trades:
                action = trade.get('action', '').upper()
                value = float(trade.get('estimated_value', 0))
                symbol = trade.get('symbol', '')
                
                if action == 'BUY':
                    total_buy_value += value
                    portfolio['buy_volume'] += value
                    portfolio['cash_flow'] -= value
                elif action == 'SELL':
                    total_sell_value += value
                    portfolio['sell_volume'] += value
                    portfolio['cash_flow'] += value
                
                if symbol:
                    symbols_traded.add(symbol)
                    
                    # 配分変更の追跡
                    if symbol not in allocation_changes:
                        allocation_changes[symbol] = {'buys': 0, 'sells': 0}
                    
                    if action == 'BUY':
                        allocation_changes[symbol]['buys'] += value
                    elif action == 'SELL':
                        allocation_changes[symbol]['sells'] += value
            
            # 計算値の設定
            portfolio['net_position_change'] = total_buy_value - total_sell_value
            
            # ポジション回転率
            total_volume = portfolio['buy_volume'] + portfolio['sell_volume']
            if total_volume > 0:
                portfolio['position_turnover'] = round(total_volume / (total_buy_value + total_sell_value) * 2, 2)
            
            # 分散化指標
            portfolio['diversification_metrics'] = {
                'symbols_traded': len(symbols_traded),
                'symbol_diversity': self._calculate_symbol_diversity(symbols_traded),
                'concentration_risk': self._calculate_concentration_risk(allocation_changes)
            }
            
            # 配分効率
            portfolio['allocation_efficiency'] = {
                'target_vs_actual': self._compare_target_vs_actual_allocation(trades),
                'rebalancing_efficiency': self._calculate_rebalancing_efficiency(trades),
                'allocation_drift': self._calculate_allocation_drift(trades)
            }
            
            return portfolio
            
        except Exception as e:
            self.logger.error(f"ポートフォリオパフォーマンス分析中にエラー発生: {e}")
            return {}
    
    def _analyze_risk_metrics_comprehensive(self, trades):
        """包括的なリスク指標の分析"""
        try:
            risk_metrics = {
                'volatility': 0,
                'max_drawdown': 0,
                'var_95': 0,  # Value at Risk (95%)
                'sharpe_ratio': 0,
                'sortino_ratio': 0,
                'calmar_ratio': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'average_win': 0,
                'average_loss': 0,
                'largest_win': 0,
                'largest_loss': 0,
                'consecutive_wins': 0,
                'consecutive_losses': 0
            }
            
            # 価格変動の追跡
            price_changes = []
            wins = 0
            losses = 0
            total_win = 0
            total_loss = 0
            consecutive_wins = 0
            consecutive_losses = 0
            max_consecutive_wins = 0
            max_consecutive_losses = 0
            
            for trade in trades:
                price_diff = float(trade.get('price_difference', 0))
                if price_diff != 0:
                    price_changes.append(price_diff)
                    
                    if price_diff > 0:
                        wins += 1
                        total_win += price_diff
                        consecutive_wins += 1
                        consecutive_losses = 0
                        max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
                    else:
                        losses += 1
                        total_loss += abs(price_diff)
                        consecutive_losses += 1
                        consecutive_wins = 0
                        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
            
            # リスク指標の計算
            if price_changes:
                risk_metrics['volatility'] = round(np.std(price_changes), 4)
                risk_metrics['max_drawdown'] = round(min(price_changes), 4)
                
                # VaR (95%)
                sorted_changes = sorted(price_changes)
                var_index = int(len(sorted_changes) * 0.05)
                risk_metrics['var_95'] = round(sorted_changes[var_index], 4)
                
                # シャープレシオ（リスクフリーレートを0%と仮定）
                mean_return = np.mean(price_changes)
                if risk_metrics['volatility'] > 0:
                    risk_metrics['sharpe_ratio'] = round(mean_return / risk_metrics['volatility'], 4)
            
            # 勝率と利益指標
            total_trades = wins + losses
            if total_trades > 0:
                risk_metrics['win_rate'] = round((wins / total_trades) * 100, 2)
            
            if wins > 0:
                risk_metrics['average_win'] = round(total_win / wins, 4)
                risk_metrics['largest_win'] = round(max(price_changes), 4)
            
            if losses > 0:
                risk_metrics['average_loss'] = round(total_loss / losses, 4)
                risk_metrics['largest_loss'] = round(min(price_changes), 4)
            
            # 利益因子
            if total_loss > 0:
                risk_metrics['profit_factor'] = round(total_win / total_loss, 4)
            
            # 連続勝敗
            risk_metrics['consecutive_wins'] = max_consecutive_wins
            risk_metrics['consecutive_losses'] = max_consecutive_losses
            
            return risk_metrics
            
        except Exception as e:
            self.logger.error(f"リスク指標分析中にエラー発生: {e}")
            return {}
    
    def _analyze_execution_quality_comprehensive(self, trades):
        """包括的な実行品質の分析"""
        try:
            quality_metrics = {
                'overall_quality_score': 0,
                'speed_metrics': {},
                'accuracy_metrics': {},
                'fill_metrics': {},
                'impact_metrics': {},
                'timing_metrics': {},
                'quality_distribution': {}
            }
            
            # 品質スコアの収集
            quality_scores = []
            execution_times = []
            price_accuracies = []
            fill_rates = []
            market_impacts = []
            
            for trade in trades:
                # 実行品質スコア
                quality = float(trade.get('execution_quality', 0))
                if quality > 0:
                    quality_scores.append(quality)
                
                # 実行時間
                duration = float(trade.get('execution_duration', 0))
                if duration > 0:
                    execution_times.append(duration)
                
                # 価格精度
                limit_price = float(trade.get('limit_price', 0))
                execution_price = float(trade.get('execution_price', 0))
                if limit_price > 0 and execution_price > 0:
                    accuracy = abs(execution_price - limit_price) / limit_price
                    price_accuracies.append(accuracy)
                
                # 約定率
                fill_rate = float(trade.get('fill_percentage', 0))
                if fill_rate > 0:
                    fill_rates.append(fill_rate)
                
                # 市場インパクト
                impact = float(trade.get('impact_cost', 0))
                if impact != 0:
                    market_impacts.append(abs(impact))
            
            # 全体品質スコア
            if quality_scores:
                quality_metrics['overall_quality_score'] = round(np.mean(quality_scores), 2)
            
            # 速度指標
            if execution_times:
                quality_metrics['speed_metrics'] = {
                    'average_time': round(np.mean(execution_times), 2),
                    'median_time': round(np.median(execution_times), 2),
                    'fastest_time': round(min(execution_times), 2),
                    'slowest_time': round(max(execution_times), 2),
                    'speed_consistency': round(1 - (np.std(execution_times) / np.mean(execution_times)), 4)
                }
            
            # 精度指標
            if price_accuracies:
                quality_metrics['accuracy_metrics'] = {
                    'average_accuracy': round(np.mean(price_accuracies) * 100, 4),
                    'best_accuracy': round(min(price_accuracies) * 100, 4),
                    'worst_accuracy': round(max(price_accuracies) * 100, 4),
                    'accuracy_consistency': round(1 - (np.std(price_accuracies) / np.mean(price_accuracies)), 4)
                }
            
            # 約定指標
            if fill_rates:
                quality_metrics['fill_metrics'] = {
                    'average_fill_rate': round(np.mean(fill_rates), 2),
                    'perfect_fills': len([r for r in fill_rates if r >= 100]),
                    'partial_fills': len([r for r in fill_rates if r < 100 and r > 0]),
                    'fill_consistency': round(1 - (np.std(fill_rates) / np.mean(fill_rates)), 4)
                }
            
            # インパクト指標
            if market_impacts:
                quality_metrics['impact_metrics'] = {
                    'average_impact': round(np.mean(market_impacts), 4),
                    'max_impact': round(max(market_impacts), 4),
                    'impact_consistency': round(1 - (np.std(market_impacts) / np.mean(market_impacts)), 4)
                }
            
            # 品質分布
            if quality_scores:
                quality_metrics['quality_distribution'] = {
                    'excellent': len([q for q in quality_scores if q >= 90]),
                    'good': len([q for q in quality_scores if 80 <= q < 90]),
                    'average': len([q for q in quality_scores if 70 <= q < 80]),
                    'poor': len([q for q in quality_scores if 60 <= q < 70]),
                    'very_poor': len([q for q in quality_scores if q < 60])
                }
            
            return quality_metrics
            
        except Exception as e:
            self.logger.error(f"実行品質分析中にエラー発生: {e}")
            return {}
    
    def _analyze_cost_performance(self, trades):
        """コストパフォーマンスの分析"""
        try:
            cost_metrics = {
                'total_commission': 0,
                'total_fees': 0,
                'total_cost': 0,
                'average_cost_per_trade': 0,
                'cost_percentage': 0,
                'cost_efficiency': 0,
                'cost_breakdown': {},
                'cost_trends': {}
            }
            
            total_value = 0
            commission_by_type = {}
            fees_by_type = {}
            
            for trade in trades:
                # コストの集計
                commission = float(trade.get('commission', 0))
                fees = float(trade.get('fees', 0))
                value = float(trade.get('estimated_value', 0))
                
                cost_metrics['total_commission'] += commission
                cost_metrics['total_fees'] += fees
                cost_metrics['total_cost'] += commission + fees
                total_value += value
                
                # 取引タイプ別のコスト分類
                action = trade.get('action', '').upper()
                if action not in commission_by_type:
                    commission_by_type[action] = 0
                    fees_by_type[action] = 0
                
                commission_by_type[action] += commission
                fees_by_type[action] += fees
            
            # 平均コスト
            if len(trades) > 0:
                cost_metrics['average_cost_per_trade'] = round(cost_metrics['total_cost'] / len(trades), 2)
            
            # コスト率
            if total_value > 0:
                cost_metrics['cost_percentage'] = round((cost_metrics['total_cost'] / total_value) * 100, 4)
            
            # コスト効率（品質スコアとの相関）
            quality_scores = [float(t.get('execution_quality', 0)) for t in trades if float(t.get('execution_quality', 0)) > 0]
            if quality_scores and cost_metrics['total_cost'] > 0:
                avg_quality = np.mean(quality_scores)
                cost_metrics['cost_efficiency'] = round(avg_quality / cost_metrics['cost_percentage'], 2)
            
            # コスト内訳
            cost_metrics['cost_breakdown'] = {
                'commission_by_type': commission_by_type,
                'fees_by_type': fees_by_type,
                'commission_percentage': round((cost_metrics['total_commission'] / cost_metrics['total_cost']) * 100, 2) if cost_metrics['total_cost'] > 0 else 0,
                'fees_percentage': round((cost_metrics['total_fees'] / cost_metrics['total_cost']) * 100, 2) if cost_metrics['total_cost'] > 0 else 0
            }
            
            return cost_metrics
            
        except Exception as e:
            self.logger.error(f"コストパフォーマンス分析中にエラー発生: {e}")
            return {}
    
    def _compare_with_benchmark(self, trades, benchmark):
        """ベンチマークとの比較"""
        try:
            benchmark_comparison = {
                'benchmark_symbol': benchmark,
                'benchmark_return': 0,
                'relative_performance': 0,
                'excess_return': 0,
                'information_ratio': 0,
                'tracking_error': 0,
                'correlation': 0
            }
            
            # ベンチマークデータの取得（簡易版）
            benchmark_data = self._get_benchmark_data_simple(benchmark)
            if not benchmark_data:
                return benchmark_comparison
            
            # ポートフォリオリターンの計算
            portfolio_return = self._calculate_portfolio_return(trades)
            
            # 比較指標の計算
            benchmark_comparison['benchmark_return'] = benchmark_data.get('return', 0)
            benchmark_comparison['relative_performance'] = portfolio_return - benchmark_data.get('return', 0)
            benchmark_comparison['excess_return'] = benchmark_comparison['relative_performance']
            
            # 情報比率
            tracking_error = benchmark_data.get('volatility', 0.01)
            if tracking_error > 0:
                benchmark_comparison['information_ratio'] = round(benchmark_comparison['excess_return'] / tracking_error, 4)
            
            benchmark_comparison['tracking_error'] = tracking_error
            benchmark_comparison['correlation'] = benchmark_data.get('correlation', 0)
            
            return benchmark_comparison
            
        except Exception as e:
            self.logger.error(f"ベンチマーク比較中にエラー発生: {e}")
            return {}
    
    def _get_benchmark_data_simple(self, benchmark):
        """簡易ベンチマークデータの取得"""
        try:
            # 簡易的なベンチマークデータ（実際の実装では外部APIを使用）
            benchmark_data = {
                'SPY': {'return': 0.05, 'volatility': 0.15, 'correlation': 0.8},
                'QQQ': {'return': 0.08, 'volatility': 0.20, 'correlation': 0.7},
                'IWM': {'return': 0.06, 'volatility': 0.18, 'correlation': 0.6}
            }
            
            return benchmark_data.get(benchmark, {'return': 0.05, 'volatility': 0.15, 'correlation': 0.5})
            
        except Exception as e:
            self.logger.error(f"ベンチマークデータ取得中にエラー発生: {e}")
            return None
    
    def _calculate_portfolio_return(self, trades):
        """ポートフォリオリターンの計算"""
        try:
            total_return = 0
            total_value = 0
            
            for trade in trades:
                value = float(trade.get('estimated_value', 0))
                price_diff = float(trade.get('price_difference', 0))
                
                if value > 0:
                    trade_return = price_diff / value
                    total_return += trade_return * value
                    total_value += value
            
            return round((total_return / total_value) * 100, 4) if total_value > 0 else 0
            
        except Exception as e:
            self.logger.error(f"ポートフォリオリターン計算中にエラー発生: {e}")
            return 0
    
    def _analyze_performance_attribution(self, trades):
        """パフォーマンス帰属分析"""
        try:
            attribution = {
                'timing_contribution': 0,
                'selection_contribution': 0,
                'execution_contribution': 0,
                'cost_contribution': 0,
                'factor_breakdown': {}
            }
            
            # 各要因の貢献度を計算
            timing_contrib = 0
            selection_contrib = 0
            execution_contrib = 0
            cost_contrib = 0
            
            for trade in trades:
                # タイミング貢献（市場タイミング）
                market_timing = self._calculate_market_timing_contribution(trade)
                timing_contrib += market_timing
                
                # 銘柄選択貢献
                selection_contrib += self._calculate_selection_contribution(trade)
                
                # 実行貢献
                execution_contrib += self._calculate_execution_contribution(trade)
                
                # コスト貢献
                cost_contrib += self._calculate_cost_contribution(trade)
            
            attribution['timing_contribution'] = round(timing_contrib, 4)
            attribution['selection_contribution'] = round(selection_contrib, 4)
            attribution['execution_contribution'] = round(execution_contrib, 4)
            attribution['cost_contribution'] = round(cost_contrib, 4)
            
            # 要因別内訳
            attribution['factor_breakdown'] = {
                'timing_percentage': round((timing_contrib / (timing_contrib + selection_contrib + execution_contrib + cost_contrib)) * 100, 2) if (timing_contrib + selection_contrib + execution_contrib + cost_contrib) > 0 else 0,
                'selection_percentage': round((selection_contrib / (timing_contrib + selection_contrib + execution_contrib + cost_contrib)) * 100, 2) if (timing_contrib + selection_contrib + execution_contrib + cost_contrib) > 0 else 0,
                'execution_percentage': round((execution_contrib / (timing_contrib + selection_contrib + execution_contrib + cost_contrib)) * 100, 2) if (timing_contrib + selection_contrib + execution_contrib + cost_contrib) > 0 else 0,
                'cost_percentage': round((cost_contrib / (timing_contrib + selection_contrib + execution_contrib + cost_contrib)) * 100, 2) if (timing_contrib + selection_contrib + execution_contrib + cost_contrib) > 0 else 0
            }
            
            return attribution
            
        except Exception as e:
            self.logger.error(f"パフォーマンス帰属分析中にエラー発生: {e}")
            return {}
    
    def _calculate_market_timing_contribution(self, trade):
        """市場タイミング貢献の計算"""
        try:
            # 簡易的な市場タイミング貢献の計算
            market_conditions = trade.get('market_conditions', '')
            if market_conditions == 'REGULAR_HOURS':
                return 0.001  # 通常時間は有利
            elif market_conditions == 'EXTENDED_HOURS':
                return 0.0005  # 延長時間は中程度
            else:
                return -0.001  # 時間外は不利
        except Exception as e:
            self.logger.error(f"市場タイミング貢献計算中にエラー発生: {e}")
            return 0
    
    def _calculate_selection_contribution(self, trade):
        """銘柄選択貢献の計算"""
        try:
            # 簡易的な銘柄選択貢献の計算
            symbol = trade.get('symbol', '')
            if symbol in ['XLU', 'TQQQ', 'TECL']:  # 高配分銘柄
                return 0.002
            else:
                return 0.001
        except Exception as e:
            self.logger.error(f"銘柄選択貢献計算中にエラー発生: {e}")
            return 0
    
    def _calculate_execution_contribution(self, trade):
        """実行貢献の計算"""
        try:
            # 実行品質に基づく貢献の計算
            quality = float(trade.get('execution_quality', 0))
            if quality >= 90:
                return 0.002
            elif quality >= 80:
                return 0.001
            elif quality >= 70:
                return 0.0005
            else:
                return -0.001
        except Exception as e:
            self.logger.error(f"実行貢献計算中にエラー発生: {e}")
            return 0
    
    def _calculate_cost_contribution(self, trade):
        """コスト貢献の計算"""
        try:
            # コストに基づく貢献の計算（負の貢献）
            commission = float(trade.get('commission', 0))
            fees = float(trade.get('fees', 0))
            value = float(trade.get('estimated_value', 0))
            
            if value > 0:
                cost_rate = (commission + fees) / value
                return -cost_rate
            return 0
        except Exception as e:
            self.logger.error(f"コスト貢献計算中にエラー発生: {e}")
            return 0
    
    def _generate_performance_recommendations(self, trades):
        """パフォーマンス改善提案の生成"""
        try:
            recommendations = []
            
            # 成功率の分析
            success_rate = self._calculate_overall_success_rate(trades)
            if success_rate < 85:
                recommendations.append({
                    'category': 'Success Rate',
                    'priority': 'HIGH',
                    'recommendation': f"成功率が{success_rate}%と低いです。エラー分析を確認し、注文パラメータを最適化してください。",
                    'action_items': ['エラーログの確認', '注文パラメータの見直し', '市場状況の分析']
                })
            
            # 実行品質の分析
            avg_quality = self._calculate_average_quality(trades)
            if avg_quality < 75:
                recommendations.append({
                    'category': 'Execution Quality',
                    'priority': 'HIGH',
                    'recommendation': f"実行品質が{avg_quality}/100と低いです。価格設定とタイミングを改善してください。",
                    'action_items': ['価格設定の最適化', '注文タイミングの改善', '市場インパクトの最小化']
                })
            
            # コスト効率の分析
            avg_cost_percentage = self._calculate_average_cost_percentage(trades)
            if avg_cost_percentage > 0.3:
                recommendations.append({
                    'category': 'Cost Efficiency',
                    'priority': 'MEDIUM',
                    'recommendation': f"取引コストが{avg_cost_percentage*100:.2f}%と高いです。手数料の見直しを検討してください。",
                    'action_items': ['手数料プランの見直し', '取引頻度の最適化', '大口取引の検討']
                })
            
            # リスク管理の分析
            risk_metrics = self._analyze_risk_metrics_comprehensive(trades)
            if risk_metrics.get('max_drawdown', 0) < -0.05:
                recommendations.append({
                    'category': 'Risk Management',
                    'priority': 'HIGH',
                    'recommendation': f"最大ドローダウンが{risk_metrics.get('max_drawdown', 0)*100:.2f}%と大きいです。リスク管理を強化してください。",
                    'action_items': ['ポジションサイズの調整', 'ストップロス設定', '分散投資の強化']
                })
            
            return recommendations
            
        except Exception as e:
            self.logger.error(f"改善提案生成中にエラー発生: {e}")
            return []
    
    def _display_performance_analysis(self, analysis):
        """パフォーマンス分析結果の表示"""
        try:
            self.logger.info("=== パフォーマンス分析レポート ===")
            
            # 基本情報
            self.logger.info(f"📅 分析期間: {analysis.get('period', 'N/A')}")
            self.logger.info(f"📊 分析日時: {analysis.get('analysis_date', 'N/A')}")
            
            # 取引パフォーマンス
            trade_perf = analysis.get('trade_performance', {})
            self.logger.info(f"📈 取引パフォーマンス:")
            self.logger.info(f"  総取引数: {trade_perf.get('total_trades', 0)}")
            self.logger.info(f"  成功率: {trade_perf.get('success_rate', 0)}%")
            self.logger.info(f"  平均取引サイズ: ${trade_perf.get('average_trade_size', 0):,.2f}")
            self.logger.info(f"  取引頻度: {trade_perf.get('trade_frequency', 0)}回/日")
            
            # ポートフォリオパフォーマンス
            portfolio_perf = analysis.get('portfolio_performance', {})
            self.logger.info(f"💼 ポートフォリオパフォーマンス:")
            self.logger.info(f"  買いボリューム: ${portfolio_perf.get('buy_volume', 0):,.2f}")
            self.logger.info(f"  売りボリューム: ${portfolio_perf.get('sell_volume', 0):,.2f}")
            self.logger.info(f"  ポジション回転率: {portfolio_perf.get('position_turnover', 0)}")
            
            # リスク指標
            risk_metrics = analysis.get('risk_metrics', {})
            self.logger.info(f"⚠️ リスク指標:")
            self.logger.info(f"  ボラティリティ: {risk_metrics.get('volatility', 0):.4f}")
            self.logger.info(f"  最大ドローダウン: {risk_metrics.get('max_drawdown', 0):.4f}")
            self.logger.info(f"  シャープレシオ: {risk_metrics.get('sharpe_ratio', 0):.4f}")
            self.logger.info(f"  勝率: {risk_metrics.get('win_rate', 0)}%")
            
            # 実行品質
            quality_metrics = analysis.get('execution_quality', {})
            self.logger.info(f"🎯 実行品質:")
            self.logger.info(f"  全体品質スコア: {quality_metrics.get('overall_quality_score', 0)}/100")
            
            # コスト分析
            cost_metrics = analysis.get('cost_analysis', {})
            self.logger.info(f"💰 コスト分析:")
            self.logger.info(f"  総コスト: ${cost_metrics.get('total_cost', 0):,.2f}")
            self.logger.info(f"  コスト率: {cost_metrics.get('cost_percentage', 0):.4f}%")
            
            # ベンチマーク比較
            benchmark = analysis.get('benchmark_comparison', {})
            self.logger.info(f"📊 ベンチマーク比較 ({benchmark.get('benchmark_symbol', 'N/A')}):")
            self.logger.info(f"  相対パフォーマンス: {benchmark.get('relative_performance', 0):.4f}%")
            self.logger.info(f"  情報比率: {benchmark.get('information_ratio', 0):.4f}")
            
            # 改善提案
            recommendations = analysis.get('improvement_recommendations', [])
            if recommendations:
                self.logger.info(f"💡 改善提案:")
                for i, rec in enumerate(recommendations[:3], 1):  # 上位3件を表示
                    self.logger.info(f"  {i}. [{rec.get('priority', 'N/A')}] {rec.get('recommendation', 'N/A')}")
            
            self.logger.info("=================================")
            
        except Exception as e:
            self.logger.error(f"パフォーマンス分析表示中にエラー発生: {e}")
    
    def _save_performance_analysis(self, analysis):
        """パフォーマンス分析結果の保存"""
        try:
            # 結果をJSONファイルに保存
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"data/performance_analysis_{analysis.get('period', 'unknown')}_{timestamp}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)
            
            self.logger.info(f"✅ パフォーマンス分析結果を保存: {filename}")
            
        except Exception as e:
            self.logger.error(f"パフォーマンス分析保存中にエラー発生: {e}")
    
    def _calculate_symbol_diversity(self, symbols):
        """銘柄多様性の計算"""
        try:
            # 簡易的な多様性指標（実際の実装ではより詳細な分析が必要）
            return len(symbols)
        except Exception as e:
            self.logger.error(f"銘柄多様性計算中にエラー発生: {e}")
            return 0
    
    def _calculate_concentration_risk(self, allocation_changes):
        """集中度リスクの計算"""
        try:
            if not allocation_changes:
                return 0
            
            # 各銘柄の取引額を取得
            values = [abs(changes['buys'] - changes['sells']) for changes in allocation_changes.values()]
            total_value = sum(values)
            
            if total_value == 0:
                return 0
            
            # ヘルファインダール指数（集中度指標）
            concentration = sum((v / total_value) ** 2 for v in values)
            return round(concentration, 4)
            
        except Exception as e:
            self.logger.error(f"集中度リスク計算中にエラー発生: {e}")
            return 0
    
    def _compare_target_vs_actual_allocation(self, trades):
        """目標配分と実際の配分の比較"""
        try:
            # 簡易的な比較（実際の実装ではより詳細な分析が必要）
            return {
                'target_allocation': self.target_allocation,
                'actual_allocation': self._calculate_actual_allocation(trades),
                'allocation_drift': 0.05  # 仮の値
            }
        except Exception as e:
            self.logger.error(f"配分比較中にエラー発生: {e}")
            return {}
    
    def _calculate_actual_allocation(self, trades):
        """実際の配分の計算"""
        try:
            # 簡易的な実際の配分計算
            symbol_values = {}
            total_value = 0
            
            for trade in trades:
                symbol = trade.get('symbol', '')
                value = float(trade.get('estimated_value', 0))
                
                if symbol not in symbol_values:
                    symbol_values[symbol] = 0
                
                symbol_values[symbol] += value
                total_value += value
            
            # パーセンテージに変換
            if total_value > 0:
                return {symbol: (value / total_value) * 100 for symbol, value in symbol_values.items()}
            
            return {}
            
        except Exception as e:
            self.logger.error(f"実際の配分計算中にエラー発生: {e}")
            return {}
    
    def _calculate_rebalancing_efficiency(self, trades):
        """リバランシング効率の計算"""
        try:
            # 簡易的なリバランシング効率計算
            rebalancing_trades = [t for t in trades if t.get('reason', '').startswith('rebalancing')]
            total_trades = len(trades)
            
            if total_trades > 0:
                return round(len(rebalancing_trades) / total_trades, 4)
            
            return 0
            
        except Exception as e:
            self.logger.error(f"リバランシング効率計算中にエラー発生: {e}")
            return 0
    
    def _calculate_allocation_drift(self, trades):
        """配分ドリフトの計算"""
        try:
            # 簡易的な配分ドリフト計算
            return 0.02  # 仮の値（実際の実装ではより詳細な計算が必要）
        except Exception as e:
            self.logger.error(f"配分ドリフト計算中にエラー発生: {e}")
            return 0
    
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
            
            # 保守的価格マージンの設定を表示
            conservative_margin = self.config.get('trading_settings', {}).get('conservative_price_margin', 0.0)
            if conservative_margin > 0:
                self.logger.info(f"保守的価格マージン: {conservative_margin*100:.1f}%")
            else:
                self.logger.info("保守的価格マージン: なし (0%)")
            
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
    
    def rebalance_total_value_staged(self):
        """段階的な総資産価値ベースのリバランス実行（売却→購入の順序）"""
        try:
            self.logger.info("=== 段階的リバランシング開始（売却→購入） ===")
            
            # 保守的価格マージンの設定を表示
            conservative_margin = self.config.get('trading_settings', {}).get('conservative_price_margin', 0.0)
            if conservative_margin > 0:
                self.logger.info(f"保守的価格マージン: {conservative_margin*100:.1f}%")
            else:
                self.logger.info("保守的価格マージン: なし (0%)")
            
            # ステップ1: 現在の状況を取得
            self.logger.info("📊 ステップ1: 現在のポジションと残高をチェック")
            portfolio_summary = self.get_portfolio_summary()
            if not portfolio_summary:
                self.logger.error("ポートフォリオサマリー取得失敗")
                return
            
            current_positions = portfolio_summary['positions']
            available_cash = portfolio_summary['buying_power']
            
            # ステップ2: 価格データを取得
            self.logger.info("💰 ステップ2: 保守的価格で現在の価格を取得")
            price_data = self.get_all_stock_prices_conservative()
            if not price_data:
                self.logger.error("保守的価格データ取得失敗")
                return
            
            self.logger.info(f"取得した保守的価格データ: {price_data}")
            
            # ステップ3: 総資産価値ベースの目標配分を計算
            self.logger.info("⚖️ ステップ3: 総資産価値ベースの目標配分を計算")
            target_allocation, current_positions_value, total_portfolio_value = \
                self.calculate_target_allocation_total_value(current_positions, price_data, available_cash)
            
            if not target_allocation:
                self.logger.error("目標配分の計算に失敗しました")
                return
            
            # ステップ4: 売却取引を計算
            self.logger.info("📉 ステップ4: 売却取引を計算")
            sell_trades = self.calculate_sell_trades(current_positions, target_allocation, price_data)
            
            # ステップ5: 売却取引を実行
            if sell_trades:
                self.logger.info("🚀 第1段階: 売却取引実行開始")
                sell_success_count = self.execute_trades_safely(sell_trades)
                self.logger.info(f"売却取引結果: {sell_success_count}/{len(sell_trades)} 成功")
                
                # 売却後の状況を再取得
                if sell_success_count > 0:
                    self.logger.info("⏳ 売却後の状況を再取得中...")
                    time.sleep(5)  # 5秒待機
                    
                    # 売却後の状況を再取得
                    portfolio_summary_after_sell = self.get_portfolio_summary()
                    if portfolio_summary_after_sell:
                        current_positions_after_sell = portfolio_summary_after_sell['positions']
                        available_cash_after_sell = portfolio_summary_after_sell['buying_power']
                        
                        self.logger.info(f"売却後の利用可能資金: ${available_cash_after_sell}")
                        
                        # ステップ6: 購入取引を計算（売却後の資金で）
                        self.logger.info("📈 ステップ6: 購入取引を計算（売却後の資金）")
                        buy_trades = self.calculate_buy_trades(target_allocation, current_positions_after_sell, price_data, available_cash_after_sell)
                        
                        # ステップ7: 購入取引を実行
                        if buy_trades:
                            self.logger.info("🚀 第2段階: 購入取引実行開始")
                            buy_success_count = self.execute_trades_safely(buy_trades)
                            self.logger.info(f"購入取引結果: {buy_success_count}/{len(buy_trades)} 成功")
                            
                            total_success = sell_success_count + buy_success_count
                            total_trades = len(sell_trades) + len(buy_trades)
                            
                            if total_success > 0:
                                self.logger.info(f"✅ 段階的リバランシング完了: {total_success}/{total_trades} 取引成功")
                                
                                # 取引後チェック
                                self.post_trade_checks()
                                
                                # 取引履歴を保存
                                all_trades = sell_trades + buy_trades
                                self.save_trades_to_csv(all_trades)
                                
                                # レート制限統計情報を表示
                                self.print_rate_limit_stats()
                                
                                # エラー統計情報を表示
                                self.print_error_stats()
                                
                                # SDK互換性情報を表示
                                self.print_sdk_compatibility_info()
                            else:
                                self.logger.error("❌ 段階的リバランシング失敗: すべての取引が失敗")
                        else:
                            self.logger.info("購入する取引がありません")
                            if sell_success_count > 0:
                                self.logger.info(f"✅ 売却のみ完了: {sell_success_count}/{len(sell_trades)} 取引成功")
                                self.save_trades_to_csv(sell_trades)
                    else:
                        self.logger.error("売却後の状況取得に失敗")
                else:
                    self.logger.error("❌ 売却取引がすべて失敗")
            else:
                self.logger.info("売却する取引がありません")
                
                # 売却取引がない場合は、通常の購入取引を実行
                self.logger.info("📈 購入取引を計算")
                buy_trades = self.calculate_buy_trades(target_allocation, current_positions, price_data, available_cash)
                
                if buy_trades:
                    self.logger.info("🚀 購入取引実行開始")
                    buy_success_count = self.execute_trades_safely(buy_trades)
                    self.logger.info(f"購入取引結果: {buy_success_count}/{len(buy_trades)} 成功")
                    
                    if buy_success_count > 0:
                        self.logger.info(f"✅ 購入のみ完了: {buy_success_count}/{len(buy_trades)} 取引成功")
                        self.post_trade_checks()
                        self.save_trades_to_csv(buy_trades)
                    else:
                        self.logger.error("❌ 購入取引がすべて失敗")
                else:
                    self.logger.info("実行する取引がありません")
                
        except Exception as e:
            self.logger.error(f"段階的リバランシング中にエラー発生: {e}")

    def rebalance_total_value(self):
        """総資産価値ベースのリバランス実行（段階的実行）"""
        try:
            self.logger.info("=== 総資産価値ベースリバランス開始（段階的実行） ===")
            
            # 保守的価格マージンの設定を表示
            conservative_margin = self.config.get('trading_settings', {}).get('conservative_price_margin', 0.0)
            if conservative_margin > 0:
                self.logger.info(f"保守的価格マージン: {conservative_margin*100:.1f}%")
            else:
                self.logger.info("保守的価格マージン: なし (0%)")
            
            # ステップ1: 現在の状況を取得
            self.logger.info("📊 ステップ1: 現在のポジションと残高をチェック")
            portfolio_summary = self.get_portfolio_summary()
            if not portfolio_summary:
                self.logger.error("ポートフォリオサマリー取得失敗")
                return
            
            current_positions = portfolio_summary['positions']
            available_cash = portfolio_summary['buying_power']
            
            # ステップ2: 価格データを取得
            self.logger.info("💰 ステップ2: 保守的価格で現在の価格を取得")
            price_data = self.get_all_stock_prices_conservative()
            if not price_data:
                self.logger.error("保守的価格データ取得失敗")
                return
            
            self.logger.info(f"取得した保守的価格データ: {price_data}")
            
            # ステップ3: 総資産価値ベースの目標配分を計算
            self.logger.info("⚖️ ステップ3: 総資産価値ベースの目標配分を計算")
            target_allocation, current_positions_value, total_portfolio_value = \
                self.calculate_target_allocation_total_value(current_positions, price_data, available_cash)
            
            if not target_allocation:
                self.logger.error("目標配分の計算に失敗しました")
                return
            
            # ステップ4: 売却取引を計算
            self.logger.info("📉 ステップ4: 売却取引を計算")
            sell_trades = self.calculate_sell_trades(current_positions, target_allocation, price_data)
            
            # ステップ5: 売却取引を実行
            if sell_trades:
                self.logger.info("🚀 第1段階: 売却取引実行開始")
                sell_success_count = self.execute_trades_safely(sell_trades)
                self.logger.info(f"売却取引結果: {sell_success_count}/{len(sell_trades)} 成功")
                
                # 売却後の状況を再取得
                if sell_success_count > 0:
                    self.logger.info("⏳ 売却後の状況を再取得中...")
                    time.sleep(5)  # 5秒待機
                    
                    # 売却後の状況を再取得
                    portfolio_summary_after_sell = self.get_portfolio_summary()
                    if portfolio_summary_after_sell:
                        current_positions_after_sell = portfolio_summary_after_sell['positions']
                        available_cash_after_sell = portfolio_summary_after_sell['buying_power']
                        
                        self.logger.info(f"売却後の利用可能資金: ${available_cash_after_sell}")
                        
                        # ステップ6: 購入取引を計算（売却後の資金で）
                        self.logger.info("📈 ステップ6: 購入取引を計算（売却後の資金）")
                        buy_trades = self.calculate_buy_trades(target_allocation, current_positions_after_sell, price_data, available_cash_after_sell)
                        
                        # ステップ7: 購入取引を実行
                        if buy_trades:
                            self.logger.info("🚀 第2段階: 購入取引実行開始")
                            buy_success_count = self.execute_trades_safely(buy_trades)
                            self.logger.info(f"購入取引結果: {buy_success_count}/{len(buy_trades)} 成功")
                            
                            total_success = sell_success_count + buy_success_count
                            total_trades = len(sell_trades) + len(buy_trades)
                            
                            if total_success > 0:
                                self.logger.info(f"✅ リバランシング完了: {total_success}/{total_trades} 取引成功")
                                
                                # 取引後チェック
                                self.post_trade_checks()
                                
                                # 取引履歴を保存
                                all_trades = sell_trades + buy_trades
                                self.save_trades_to_csv(all_trades)
                            else:
                                self.logger.error("❌ リバランシング失敗: すべての取引が失敗")
                        else:
                            self.logger.info("購入する取引がありません")
                            if sell_success_count > 0:
                                self.logger.info(f"✅ 売却のみ完了: {sell_success_count}/{len(sell_trades)} 取引成功")
                                self.save_trades_to_csv(sell_trades)
                    else:
                        self.logger.error("売却後の状況取得に失敗")
                else:
                    self.logger.error("❌ 売却取引がすべて失敗")
            else:
                self.logger.info("売却する取引がありません")
                
                # 売却取引がない場合は、通常の購入取引を実行
                self.logger.info("📈 購入取引を計算")
                buy_trades = self.calculate_buy_trades(target_allocation, current_positions, price_data, available_cash)
                
                if buy_trades:
                    self.logger.info("🚀 購入取引実行開始")
                    buy_success_count = self.execute_trades_safely(buy_trades)
                    self.logger.info(f"購入取引結果: {buy_success_count}/{len(buy_trades)} 成功")
                    
                    if buy_success_count > 0:
                        self.logger.info(f"✅ 購入のみ完了: {buy_success_count}/{len(buy_trades)} 取引成功")
                        self.post_trade_checks()
                        self.save_trades_to_csv(buy_trades)
                    else:
                        self.logger.error("❌ 購入取引がすべて失敗")
                else:
                    self.logger.info("実行する取引がありません")
                
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
                
                # 未約定注文の監視を開始
                self.logger.info("未約定注文の監視を開始します...")
                monitor_success = self.monitor_all_open_orders(max_wait_time=180)  # 3分間監視
                
                if not monitor_success:
                    self.logger.warning("監視タイムアウト - 未約定注文のキャンセルを検討してください")
            else:
                self.logger.info("✅ 未約定注文なし")
            
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
            
            # 設定ファイルから保守的マージンを取得（デフォルト: 0%）
            conservative_margin = self.config.get('trading_settings', {}).get('conservative_price_margin', 0.0)
            
            # 保守的価格を計算
            conservative_price = base_price * (1 + conservative_margin)
            
            if conservative_margin > 0:
                self.logger.info(f"{symbol} 価格: ${base_price:.2f} → 保守的価格: ${conservative_price:.2f} (+{conservative_margin*100:.1f}%)")
            else:
                self.logger.info(f"{symbol} 価格: ${base_price:.2f} (保守的マージンなし)")
            
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

    def _get_contract_id_for_position(self, symbol):
        """既存ポジションからcontract_idを取得"""
        try:
            # 現在のポジションを取得
            positions = self.get_current_positions()
            if not positions:
                return None
            
            # 指定されたシンボルのポジションを検索
            for position in positions:
                if position.get('symbol') == symbol:
                    # item_idをcontract_idとして使用
                    items = position.get('items', [])
                    if items and len(items) > 0:
                        contract_id = items[0].get('item_id')
                        if contract_id:
                            self.logger.info(f"contract_id取得: {symbol} -> {contract_id}")
                            return contract_id
                        else:
                            self.logger.warning(f"item_idが存在しません: {symbol}")
                            return None
                    else:
                        self.logger.warning(f"itemsが存在しません: {symbol}")
                        return None
            
            self.logger.warning(f"ポジションが見つかりません: {symbol}")
            return None
            
        except Exception as e:
            self.logger.error(f"contract_id取得エラー: {e}")
            return None

    def _try_alternative_sell_method(self, symbol, quantity, instrument_id, current_price):
        """代替売却方法を試行"""
        try:
            self.logger.info(f"代替売却方法を試行: {symbol}")
            
            # 方法1: LIMIT注文で売却を試行
            client_order_id = uuid.uuid4().hex
            limit_price = current_price * 0.98  # より安い価格で売却
            
            stock_order = {
                "client_order_id": client_order_id,
                "instrument_id": str(instrument_id),
                "side": "SELL",
                "tif": "DAY",
                "extended_hours_trading": False,  # APIの要求に従ってfalseに設定
                "order_type": "LIMIT",
                "limit_price": f"{limit_price:.2f}",
                "qty": str(int(quantity)),
                "trade_currency": "USD",
                "account_tax_type": "SPECIFIC"  # SPECIFICに変更
            }
            
            self.logger.info(f"代替LIMIT注文パラメータ: {stock_order}")
            
            def api_call():
                return self.api.order.place_order_v2(account_id=self.account_id, stock_order=stock_order)
            
            response = self.api_call_with_retry(api_call, max_retries=2, delay=1, api_name="alternative_sell")
            
            if response and response.status_code == 200:
                self.logger.info(f"✅ 代替売却成功: {symbol}")
                return True
            else:
                self.logger.warning(f"代替売却失敗: {symbol}")
                return False
                
        except Exception as e:
            self.logger.error(f"代替売却エラー: {e}")
            return False

    def _try_staged_sell_method(self, symbol, quantity, instrument_id, current_price):
        """段階的な売却方法を試行（小さな注文→修正）"""
        try:
            self.logger.info(f"段階的売却方法を試行: {symbol}")
            
            # ステップ1: 小さな注文（1株）を発注
            small_quantity = 1
            client_order_id = uuid.uuid4().hex
            
            stock_order = {
                "client_order_id": client_order_id,
                "instrument_id": str(instrument_id),
                "side": "SELL",
                "tif": "DAY",
                "extended_hours_trading": False,
                "order_type": "LIMIT",
                "limit_price": f"{current_price * 0.95:.2f}",  # 5%安い価格
                "qty": str(small_quantity),
                "trade_currency": "USD",
                "account_tax_type": "GENERAL"
            }
            
            self.logger.info(f"小さな注文パラメータ: {stock_order}")
            
            def api_call():
                return self.api.order.place_order_v2(account_id=self.account_id, stock_order=stock_order)
            
            response = self.api_call_with_retry(api_call, max_retries=2, delay=1, api_name="small_sell")
            
            if response and response.status_code == 200:
                order_data = json.loads(response.text)
                self.logger.info(f"小さな注文成功: {order_data}")
                
                # ステップ2: 注文を修正して数量を増やす
                order_id = order_data.get('order_id')
                if order_id:
                    return self._modify_order_quantity(order_id, client_order_id, quantity, current_price)
                else:
                    self.logger.warning("注文IDが取得できませんでした")
                    return False
            else:
                self.logger.warning(f"小さな注文失敗: {response.text if response else 'No response'}")
                return False
                
        except Exception as e:
            self.logger.error(f"段階的売却エラー: {e}")
            return False

    def _modify_order_quantity(self, order_id, client_order_id, target_quantity, current_price):
        """注文数量を修正"""
        try:
            self.logger.info(f"注文数量修正: {order_id} -> {target_quantity}株")
            
            # replace-order APIを使用して数量を修正
            stock_order = {
                "client_order_id": client_order_id,
                "order_type": "LIMIT",
                "limit_price": f"{current_price * 0.95:.2f}",
                "qty": str(target_quantity)
            }
            
            self.logger.info(f"修正注文パラメータ: {stock_order}")
            
            def api_call():
                return self.api.order.replace_order_v2(account_id=self.account_id, stock_order=stock_order)
            
            response = self.api_call_with_retry(api_call, max_retries=2, delay=1, api_name="replace_order")
            
            if response and response.status_code == 200:
                self.logger.info(f"✅ 注文修正成功: {symbol}")
                return True
            else:
                self.logger.warning(f"注文修正失敗: {response.text if response else 'No response'}")
                return False
                
        except Exception as e:
            self.logger.error(f"注文修正エラー: {e}")
            return False

    def calculate_remaining_cash_allocation(self, available_cash, current_prices, target_allocations):
        """残り資金を有効活用するための追加購入を計算"""
        self.logger.info(f"💰 残り資金活用計算: ${available_cash:.2f}")
        
        # 購入可能な銘柄を特定（1株でも購入可能な銘柄）
        affordable_stocks = []
        for symbol, price in current_prices.items():
            if price <= available_cash:
                affordable_stocks.append((symbol, price))
        
        if not affordable_stocks:
            self.logger.info(f"❌ 残り資金${available_cash:.2f}では1株も購入できません")
            return []
        
        # 価格の安い順にソート
        affordable_stocks.sort(key=lambda x: x[1])
        
        # 最も安い銘柄を選択
        best_symbol, best_price = affordable_stocks[0]
        max_shares = int(available_cash / best_price)
        
        if max_shares > 0:
            cost = max_shares * best_price
            self.logger.info(f"✅ 残り資金活用: {best_symbol} {max_shares}株購入予定 (${cost:.2f})")
            return [{
                'symbol': best_symbol,
                'action': 'BUY',
                'quantity': max_shares,
                'estimated_cost': cost
            }]
        
        return []

    def calculate_fractional_buy_trades(self, available_cash, current_prices, target_allocations):
        """残り資金で部分的な購入を計算"""
        self.logger.info(f"💰 部分購入計算: ${available_cash:.2f}")
        
        # 価格の安い順にソート
        sorted_prices = sorted(current_prices.items(), key=lambda x: x[1])
        
        for symbol, price in sorted_prices:
            # 1株でも購入可能かチェック
            if price <= available_cash:
                max_shares = int(available_cash / price)
                if max_shares > 0:
                    cost = max_shares * price
                    self.logger.info(f"✅ 部分購入可能: {symbol} {max_shares}株 (${cost:.2f})")
                    return [{
                        'symbol': symbol,
                        'action': 'BUY',
                        'quantity': max_shares,
                        'estimated_cost': cost
                    }]
        
        self.logger.info(f"❌ 残り資金${available_cash:.2f}では部分購入もできません")
        return []

def main():
    """メイン関数"""
    try:
        # コマンドライン引数から設定ファイルを取得
        config_file = sys.argv[1] if len(sys.argv) > 1 else 'webull_config_with_allocation.json'
        dry_run = sys.argv[2] == 'dry_run' if len(sys.argv) > 2 else None
        staged_mode = '--staged' in sys.argv  # 段階的リバランシングモード
        
        rebalancer = WebullCompleteRebalancer(config_file=config_file, dry_run=dry_run)
        
        if staged_mode:
            # 段階的リバランシング（売却→購入の順序）
            rebalancer.rebalance_total_value_staged()
        else:
            # 通常のリバランシング
            rebalancer.rebalance()
    except Exception as e:
        logging.error(f"メイン実行エラー: {e}")

if __name__ == "__main__":
    main() 
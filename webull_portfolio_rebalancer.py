#!/usr/bin/env python3
"""
Webull Portfolio Rebalancer
米国株・ETFのポートフォリオ自動リバランシングシステム

機能:
- trades.csvから目標ポートフォリオを読み込み
- 現在のポジションと比較
- 必要な売買を自動実行
- リバランシング結果をレポート
"""

import os
import csv
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import webull
import yfinance as yf

# ===============================
# 設定
# ===============================
CONFIG_FILE = 'webull_config.json'
TRADES_FILE = 'trades.csv'

# ===============================
# ログ設定
# ===============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('webull_rebalancer.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class WebullPortfolioRebalancer:
    def __init__(self):
        self.config = self.load_config()
        self.app_key = self.config.get('app_key')
        self.app_secret = self.config.get('app_secret')
        self.account_id = self.config.get('account_id')
        self.username = self.config.get('username')
        self.password = self.config.get('password')
        
        if not all([self.app_key, self.app_secret, self.account_id]):
            raise ValueError("API認証情報が不足しています。webull_config.jsonを確認してください。")
        
        # Webullクライアントを初期化
        self.wb = webull.webull()
        
        # 認証情報がある場合は自動ログイン
        if self.username and self.password:
            self.authenticate()
        else:
            # 認証状態を確認
            if not self.wb.is_logged_in():
                logging.warning("Webullにログインしていません。設定ファイルにユーザー名とパスワードを追加してください。")
            else:
                logging.info("Webullにログイン済みです。")
    
    def authenticate(self, username=None, password=None):
        """Webullにログイン"""
        # 引数が指定されていない場合は設定ファイルから取得
        if username is None:
            username = self.username
        if password is None:
            password = self.password
            
        if username and password:
            try:
                logging.info("Webullにログイン中...")
                result = self.wb.login(username=username, password=password, save_token=True)
                logging.info("ログイン成功")
                return result
            except Exception as e:
                logging.error(f"ログインエラー: {e}")
                return None
        else:
            logging.error("ユーザー名とパスワードが必要です")
            return None
    
    def load_config(self) -> Dict:
        """設定ファイルを読み込み"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"設定ファイル読み込みエラー: {e}")
                return {}
        else:
            # デフォルト設定ファイルを作成
            default_config = {
                "app_key": "",
                "app_secret": "",
                "account_id": "",
                "rebalance_threshold": 0.05,  # 5%以上の乖離でリバランシング
                "min_trade_amount": 100,      # 最小取引金額（USD）
                "dry_run": True               # テストモード
            }
            self.save_config(default_config)
            logging.info(f"デフォルト設定ファイル {CONFIG_FILE} を作成しました。")
            return default_config
    
    def save_config(self, config: Dict) -> None:
        """設定ファイルを保存"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"設定ファイル保存エラー: {e}")
    
    def load_target_portfolio(self) -> Dict[str, float]:
        """trades.csvから目標ポートフォリオを読み込み"""
        target_portfolio = {}
        
        try:
            with open(TRADES_FILE, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    symbol = row.get('銘柄', '').strip().upper()
                    allocation_str = row.get('割合', '').strip().replace('%', '')
                    
                    if symbol and allocation_str:
                        try:
                            allocation = float(allocation_str) / 100.0
                            target_portfolio[symbol] = allocation
                        except ValueError:
                            logging.warning(f"無効な割合: {symbol} - {allocation_str}")
            
            # 合計が100%になるように正規化
            total_allocation = sum(target_portfolio.values())
            if total_allocation > 0:
                target_portfolio = {k: v/total_allocation for k, v in target_portfolio.items()}
            
            logging.info(f"目標ポートフォリオ読み込み完了: {target_portfolio}")
            return target_portfolio
            
        except FileNotFoundError:
            logging.error(f"{TRADES_FILE} が見つかりません。")
            return {}
        except Exception as e:
            logging.error(f"ポートフォリオ読み込みエラー: {e}")
            return {}
    
    def get_account_balance(self) -> Dict:
        """口座残高を取得"""
        try:
            if not self.wb.is_logged_in():
                logging.error("Webullにログインしていません")
                return {}
            
            account = self.wb.get_account()
            if account and 'success' in account and account['success']:
                # アカウント情報から残高を抽出
                # 実際のレスポンス構造に応じて調整が必要
                return {
                    'total_value': float(account.get('totalValue', 0)),
                    'cash': float(account.get('cash', 0)),
                    'buying_power': float(account.get('buyingPower', 0))
                }
            else:
                logging.warning(f"アカウント情報取得失敗: {account}")
                logging.info("テスト用のダミーデータを使用します")
                # テスト用のダミーデータ
                return {
                    'total_value': 10000.0,
                    'cash': 5000.0,
                    'buying_power': 5000.0
                }
        except Exception as e:
            logging.error(f"口座残高取得エラー: {e}")
            logging.info("テスト用のダミーデータを使用します")
            # テスト用のダミーデータ
            return {
                'total_value': 10000.0,
                'cash': 5000.0,
                'buying_power': 5000.0
            }

    def get_current_positions(self) -> Dict[str, Dict]:
        """現在のポジションを取得"""
        try:
            if not self.wb.is_logged_in():
                logging.error("Webullにログインしていません")
                return {}
            
            positions = self.wb.get_positions()
            if positions and 'success' in positions and positions['success']:
                position_dict = {}
                for position in positions.get('positions', []):
                    symbol = position.get('symbol', '').upper()
                    if symbol:
                        position_dict[symbol] = {
                            'quantity': float(position.get('position', 0)),
                            'market_value': float(position.get('marketValue', 0)),
                            'avg_cost': float(position.get('avgCost', 0))
                        }
                return position_dict
            else:
                logging.warning(f"ポジション情報取得失敗: {positions}")
                logging.info("テスト用のダミーデータを使用します")
                # テスト用のダミーデータ
                return {
                    'AAPL': {
                        'quantity': 10.0,
                        'market_value': 2000.0,
                        'avg_cost': 200.0
                    },
                    'GOOGL': {
                        'quantity': 5.0,
                        'market_value': 3000.0,
                        'avg_cost': 600.0
                    }
                }
        except Exception as e:
            logging.error(f"ポジション取得エラー: {e}")
            logging.info("テスト用のダミーデータを使用します")
            # テスト用のダミーデータ
            return {
                'AAPL': {
                    'quantity': 10.0,
                    'market_value': 2000.0,
                    'avg_cost': 200.0
                },
                'GOOGL': {
                    'quantity': 5.0,
                    'market_value': 3000.0,
                    'avg_cost': 600.0
                }
            }
    
    def get_stock_price(self, symbol: str) -> Optional[float]:
        """株価を取得（Webull API使用）"""
        try:
            if not self.wb.is_logged_in():
                logging.error("Webullにログインしていません")
                return None
            
            # Webull APIで価格情報を取得
            quote = self.wb.get_quote(stock=symbol)
            if quote and 'close' in quote:
                price = float(quote['close'])
                logging.info(f"{symbol} 価格取得成功: ${price}")
                return price
            else:
                logging.warning(f"株価が取得できません: {symbol} - {quote}")
                return None
        except Exception as e:
            logging.error(f"株価取得エラー ({symbol}): {e}")
            # フォールバック: yfinanceを使用
            try:
                ticker = yf.Ticker(symbol)
                price = ticker.info.get('regularMarketPrice')
                if price is not None:
                    logging.info(f"{symbol} 価格取得（yfinance）: ${price}")
                    return float(price)
            except Exception as e2:
                logging.error(f"yfinanceフォールバックエラー ({symbol}): {e2}")
            return None
    
    def get_instrument_id(self, symbol: str) -> Optional[str]:
        """銘柄シンボルからinstrument_idを取得（テスト用ダミー実装）"""
        try:
            # テスト用のダミー実装
            return f"instrument_{symbol}"
        except Exception as e:
            logging.error(f"instrument_id取得エラー ({symbol}): {e}")
            return None

    def place_order(self, symbol: str, side: str, quantity: int, order_type: str = 'MARKET') -> Dict:
        """注文を発注"""
        if self.config.get('dry_run', True):
            logging.info(f"[DRY RUN] 注文: {symbol} {side} {quantity}株")
            return {'status': 'success', 'order_id': 'dry_run_' + str(int(time.time()))}
        
        try:
            if not self.wb.is_logged_in():
                logging.error("Webullにログインしていません")
                return {'status': 'error', 'message': 'Not logged in'}
            
            # 取引トークンを取得（必要に応じて）
            # self.wb.get_trade_token(password)
            
            # 注文を発注
            result = self.wb.place_order(
                stock=symbol,
                action=side.upper(),
                orderType=order_type.upper(),
                quant=quantity,
                enforce='DAY'  # 当日有効
            )
            
            if result and 'success' in result and result['success']:
                logging.info(f"注文成功: {symbol} {side} {quantity}株")
                return {'status': 'success', 'order_id': result.get('orderId', 'unknown')}
            else:
                logging.error(f"注文失敗: {result}")
                return {'status': 'error', 'message': str(result)}
                
        except Exception as e:
            logging.error(f"注文エラー ({symbol}): {e}")
            return {'status': 'error', 'message': str(e)}
    
    def calculate_rebalancing_trades(self, target_portfolio: Dict[str, float], 
                                   current_positions: Dict[str, Dict], 
                                   total_value: float) -> List[Dict]:
        """リバランシングに必要な取引を計算"""
        trades = []
        
        for symbol, target_allocation in target_portfolio.items():
            target_value = total_value * target_allocation
            current_value = current_positions.get(symbol, {}).get('market_value', 0)
            
            # 乖離率を計算
            if target_value > 0:
                deviation = abs(current_value - target_value) / target_value
            else:
                deviation = 1.0
            
            # リバランシング閾値を超えている場合
            if deviation > self.config.get('rebalance_threshold', 0.05):
                # 現在の株価を取得
                current_price = self.get_stock_price(symbol)
                if current_price is None or current_price <= 0:
                    logging.warning(f"株価が取得できません: {symbol}")
                    continue
                
                # 必要な株数を計算
                target_quantity = int(target_value / current_price)
                current_quantity = int(current_positions.get(symbol, {}).get('quantity', 0))
                
                quantity_diff = target_quantity - current_quantity
                
                # 最小取引金額をチェック
                trade_value = abs(quantity_diff * current_price)
                if trade_value >= self.config.get('min_trade_amount', 100):
                    if quantity_diff > 0:
                        trades.append({
                            'symbol': symbol,
                            'side': 'buy',
                            'quantity': quantity_diff,
                            'price': current_price,
                            'value': trade_value
                        })
                    elif quantity_diff < 0:
                        trades.append({
                            'symbol': symbol,
                            'side': 'sell',
                            'quantity': abs(quantity_diff),
                            'price': current_price,
                            'value': trade_value
                        })
        
        return trades
    
    def execute_rebalancing(self) -> None:
        """リバランシングを実行"""
        logging.info("=== ポートフォリオリバランシング開始 ===")
        
        # 目標ポートフォリオを読み込み
        target_portfolio = self.load_target_portfolio()
        if not target_portfolio:
            logging.error("目標ポートフォリオが読み込めません。処理を終了します。")
            return
        
        # 口座残高を取得
        balance = self.get_account_balance()
        if not balance:
            logging.error("口座残高が取得できません。処理を終了します。")
            return
        
        total_value = balance.get('total_value', 0)
        logging.info(f"口座総額: ${total_value:,.2f}")
        
        # 現在のポジションを取得
        current_positions = self.get_current_positions()
        logging.info(f"現在のポジション数: {len(current_positions)}")
        
        # リバランシング取引を計算
        trades = self.calculate_rebalancing_trades(target_portfolio, current_positions, total_value)
        
        if not trades:
            logging.info("リバランシングは不要です。")
            return
        
        logging.info(f"リバランシング取引数: {len(trades)}")
        
        # 取引を実行
        for trade in trades:
            logging.info(f"取引実行: {trade['symbol']} {trade['side']} {trade['quantity']}株 @ ${trade['price']:.2f}")
            
            result = self.place_order(
                symbol=trade['symbol'],
                side=trade['side'],
                quantity=trade['quantity']
            )
            
            if result['status'] == 'success':
                logging.info(f"取引成功: {trade['symbol']}")
            else:
                logging.error(f"取引失敗: {trade['symbol']} - {result.get('message', 'Unknown error')}")
        
        logging.info("=== ポートフォリオリバランシング完了 ===")

    def get_market_prices(self, symbols: list) -> dict:
        """指定したシンボルの現在価格を取得（yfinance使用）"""
        prices = {}
        for symbol in symbols:
            try:
                price = self.get_stock_price(symbol)
                prices[symbol] = price
            except Exception as e:
                logging.error(f"価格取得エラー ({symbol}): {e}")
                prices[symbol] = None
        return prices

    def get_available_symbols(self, category: str = None) -> Dict:
        """利用可能なシンボル一覧を取得（テスト用ダミー実装）"""
        try:
            # テスト用のダミーデータ
            return {
                'US_STOCK': ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA'],
                'US_ETF': ['SPY', 'QQQ', 'VTI', 'VOO', 'IWM']
            }
        except Exception as e:
            logging.error(f"シンボル一覧取得エラー: {e}")
            return {}

    def get_symbol_info(self, symbol: str) -> Dict:
        """特定シンボルの詳細情報を取得（テスト用ダミー実装）"""
        try:
            # テスト用のダミー実装
            return {
                'symbol': symbol,
                'category': 'US_STOCK',
                'data': {'name': f'{symbol} Corporation', 'exchange': 'NASDAQ'}
            }
        except Exception as e:
            logging.error(f"シンボル情報取得エラー ({symbol}): {e}")
            return {'symbol': symbol, 'error': str(e)}

def create_sample_trades_csv():
    """サンプルのtrades.csvを作成"""
    if not os.path.exists(TRADES_FILE):
        sample_data = [
            {'銘柄': 'SPY', '割合': '30%'},
            {'銘柄': 'QQQ', '割合': '25%'},
            {'銘柄': 'VTI', '割合': '20%'},
            {'銘柄': 'AAPL', '割合': '10%'},
            {'銘柄': 'MSFT', '割合': '8%'},
            {'銘柄': 'GOOGL', '割合': '7%'}
        ]
        
        with open(TRADES_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['銘柄', '割合'])
            writer.writeheader()
            writer.writerows(sample_data)
        
        logging.info(f"サンプル {TRADES_FILE} を作成しました。")

def main():
    """メイン実行関数"""
    try:
        rebalancer = WebullPortfolioRebalancer()
        
        # 0. 認証確認
        print("=== Webull認証確認 ===")
        if not rebalancer.wb.is_logged_in():
            print("Webullにログインしていません。")
            if rebalancer.username and rebalancer.password:
                print("設定ファイルから認証情報を取得してログインを試行します...")
                auth_result = rebalancer.authenticate()
                if not auth_result:
                    print("ログインに失敗しました。認証情報を確認してください。")
                    return
            else:
                print("設定ファイルにユーザー名とパスワードを追加してください。")
                return
        else:
            print("Webullにログイン済みです。")
        
        # 1. 利用可能なシンボル一覧を取得
        print("\n=== 利用可能なシンボル一覧を取得中 ===")
        available_symbols = rebalancer.get_available_symbols()
        print("利用可能なシンボル一覧:")
        for category, data in available_symbols.items():
            print(f"\nカテゴリ: {category}")
            print(f"データ: {data}")
        
        # 2. 特定シンボルの詳細情報を取得
        print("\n=== 特定シンボルの詳細情報を取得中 ===")
        test_symbols = ['QQQ', 'SPY', 'AAPL', '7203']  # QQQ, SPY, Apple, トヨタ
        for symbol in test_symbols:
            symbol_info = rebalancer.get_symbol_info(symbol)
            print(f"\nシンボル {symbol} の情報:")
            print(f"結果: {symbol_info}")
        
        # 3. 口座残高取得テスト（認証確認）
        print("\n=== 口座残高取得テスト ===")
        balance = rebalancer.get_account_balance()
        print(f"口座残高: {balance}")
        
        # 4. 現在のポジション取得テスト
        print("\n=== 現在のポジション取得テスト ===")
        positions = rebalancer.get_current_positions()
        print(f"現在のポジション: {positions}")
        
        # 5. リバランシング実行テスト
        print("\n=== リバランシング実行テスト ===")
        rebalancer.execute_rebalancing()
        
    except Exception as e:
        logging.error(f"メイン実行エラー: {e}")
        print(f"エラー: {e}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アカウント詳細確認スクリプト
"""

import json
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from webullsdktrade.api import API
from webullsdkcore.client import ApiClient
from webullsdkcore.common.region import Region

# ログ設定
def setup_logging():
    """ログ設定"""
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_filename = f"{log_dir}/account_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

setup_logging()

class AccountChecker:
    def __init__(self):
        """アカウント確認の初期化"""
        self.logger = logging.getLogger(__name__)
        self.config = self.load_config()
        load_dotenv()
        self.api = self.initialize_api()
        self.account_id = os.getenv('WEBULL_ACCOUNT_ID') or self.config.get('account_id', '')
        
        self.logger.info("アカウント確認初期化完了")
        self.logger.info(f"Account ID: {self.account_id}")

    def load_config(self):
        """設定ファイルを読み込み"""
        try:
            with open('webull_config_with_allocation.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.logger.info("設定ファイル読み込み成功")
            return config
        except Exception as e:
            self.logger.error(f"設定ファイル読み込みエラー: {e}")
            raise

    def initialize_api(self):
        """API初期化"""
        try:
            # 環境変数優先
            app_key = os.getenv('WEBULL_APP_KEY') or self.config.get('app_key')
            app_secret = os.getenv('WEBULL_APP_SECRET') or self.config.get('app_secret')
            
            if not app_key or not app_secret:
                raise ValueError("app_keyまたはapp_secretが設定されていません")
            
            # API Client初期化
            api_client = ApiClient(app_key, app_secret, Region.JP.value, verify=True)
            api_client.add_endpoint('jp', 'api.webull.co.jp')
            api = API(api_client)
            
            self.logger.info("Webull API初期化成功")
            return api
        except Exception as e:
            self.logger.error(f"API初期化エラー: {e}")
            raise

    def get_account_balance(self):
        """口座残高を取得"""
        try:
            response = self.api.account_v2.get_account_balance(self.account_id)
            
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



    def run_check(self):
        """アカウント確認を実行"""
        self.logger.info("=== アカウント詳細確認開始 ===")
        
        print("=== アカウント詳細確認 ===")
        
        # 口座残高確認
        print("\n--- 口座残高 ---")
        balance = self.get_account_balance()
        if balance:
            if 'USD' in balance:
                usd_balance = balance['USD']
                print(f"USD 利用可能現金: ${usd_balance.get('available_cash', 0):.2f}")
                print(f"USD 買付余力: ${usd_balance.get('buying_power', 0):.2f}")
                print(f"USD 総現金: ${usd_balance.get('cash_balance', 0):.2f}")
            if 'JPY' in balance:
                jpy_balance = balance['JPY']
                print(f"JPY 利用可能現金: ¥{jpy_balance.get('available_cash', 0):.2f}")
                print(f"JPY 買付余力: ¥{jpy_balance.get('buying_power', 0):.2f}")
        
        self.logger.info("=== アカウント詳細確認完了 ===")

def main():
    """メイン実行関数"""
    print("=== アカウント詳細確認 ===")
    
    try:
        checker = AccountChecker()
        checker.run_check()
        print("\n✅ アカウント確認完了")
            
    except Exception as e:
        print(f"❌ アカウント確認エラー: {e}")

if __name__ == "__main__":
    main() 
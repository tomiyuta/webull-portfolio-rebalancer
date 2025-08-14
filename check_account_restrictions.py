#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アカウント制限詳細確認スクリプト
提供されたコードを参考に、買付余力、口座制限フラグ、ETF取引資格などを詳細確認
"""

import json
import logging
import decimal
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
    
    log_filename = f"{log_dir}/account_restrictions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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

class AccountRestrictionsChecker:
    def __init__(self):
        """アカウント制限確認の初期化"""
        self.logger = logging.getLogger(__name__)
        self.config = self.load_config()
        load_dotenv()
        self.api = self.initialize_api()
        self.account_id = os.getenv('WEBULL_ACCOUNT_ID') or self.config.get('account_id', '')
        
        self.logger.info("アカウント制限確認初期化完了")
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
            
            # 日本向けエンドポイントを明示設定
            api_client = ApiClient(app_key, app_secret, Region.JP.value, verify=True)
            api_client.add_endpoint('jp', 'api.webull.co.jp')
            api = API(api_client)
            
            self.logger.info("Webull API初期化成功")
            return api
        except Exception as e:
            self.logger.error(f"API初期化エラー: {e}")
            raise

    def check_buying_power_and_cash(self):
        """買付余力・口座フラグを詳細確認"""
        try:
            self.logger.info("=== 買付余力・口座フラグ詳細確認 ===")
            
            # メインスクリプトと同じ方法で買付余力を確認
            response = self.api.account_v2.get_account_balance(self.account_id)
            
            if response.status_code == 200:
                bal = response.json()
                self.logger.info(f"口座残高レスポンス: {bal}")
                
                # レスポンス構造を確認して適切なフィールドを取得
                if 'account_currency_assets' in bal and len(bal['account_currency_assets']) > 0:
                    # USD通貨の資産を探す
                    usd_asset = None
                    for asset in bal['account_currency_assets']:
                        if asset.get('currency') == 'USD':
                            usd_asset = asset
                            break
                    
                    if usd_asset:
                        # USDの買付余力とsettled_cashを取得
                        bp = decimal.Decimal(usd_asset.get('buying_power', '0'))
                        sc = decimal.Decimal(usd_asset.get('cash_balance', '0'))
                    else:
                        # USDが見つからない場合は最初の資産を使用
                        asset = bal['account_currency_assets'][0]
                        bp = decimal.Decimal(asset.get('buying_power', '0'))
                        sc = decimal.Decimal(asset.get('cash_balance', '0'))
                    
                    self.logger.info(f"buyingPower= {bp}, settledCash= {sc}")
                    
                    # 詳細情報を表示
                    print(f"買付余力 (buying_power): ${bp:,.2f}")
                    print(f"確定現金 (cash_balance): ${sc:,.2f}")
                    
                    # 差額を確認
                    difference = bp - sc
                    print(f"差額 (buying_power - cash_balance): ${difference:,.2f}")
                    
                    if difference < 0:
                        print("⚠️ 買付余力が確定現金を下回っています")
                    elif difference > 0:
                        print("✅ 買付余力が確定現金を上回っています")
                    else:
                        print("ℹ️ 買付余力と確定現金が同じです")
                    
                    return {
                        'buying_power': bp,
                        'settled_cash': sc,
                        'difference': difference
                    }
                else:
                    self.logger.error("口座通貨資産データが見つかりません")
                    return None
            else:
                self.logger.error(f"口座残高取得失敗: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"買付余力確認エラー: {e}")
            return None

    def check_account_restrictions(self):
        """Only-Close / 口座制限フラグを確認"""
        try:
            self.logger.info("=== 口座制限フラグ確認 ===")
            
            # 利用可能なAPIメソッドで口座情報を確認
            response = self.api.account.get_app_subscriptions()
            
            if response.status_code == 200:
                subscriptions = response.json()
                self.logger.info(f"口座情報レスポンス: {subscriptions}")
                
                # 口座情報から制限を確認
                account_info = None
                for sub in subscriptions:
                    if sub.get('account_id') == self.account_id:
                        account_info = sub
                        break
                
                if account_info:
                    account_type = account_info.get('account_type')
                    account_status = account_info.get('status')
                    
                    self.logger.info(f"account_type= {account_type}, status= {account_status}")
                    
                    print(f"口座タイプ (account_type): {account_type}")
                    print(f"口座ステータス (status): {account_status}")
                    
                    # 制限の詳細を確認
                    if account_status == 'CLOSED' or account_type == 'DEMO':
                        print("⚠️ 口座が制限されています - 新規購入が制限されている可能性があります")
                    else:
                        print("✅ 口座は通常状態です - 新規購入が可能です")
                    
                    return {
                        'account_type': account_type,
                        'status': account_status,
                        'account_info': account_info
                    }
                else:
                    self.logger.error("該当する口座情報が見つかりません")
                    return None
            else:
                self.logger.error(f"口座情報取得失敗: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"口座制限確認エラー: {e}")
            return None

    def check_etf_trading_eligibility(self):
        """ETF取引資格を確認"""
        try:
            self.logger.info("=== ETF取引資格確認 ===")
            
            # 利用可能なAPIメソッドで口座情報を確認
            response = self.api.account.get_app_subscriptions()
            
            if response.status_code == 200:
                subscriptions = response.json()
                
                # 口座情報からETF取引資格を確認
                account_info = None
                for sub in subscriptions:
                    if sub.get('account_id') == self.account_id:
                        account_info = sub
                        break
                
                if account_info:
                    # 口座タイプからETF取引資格を推測
                    account_type = account_info.get('account_type')
                    
                    if account_type == 'DEMO':
                        self.logger.warning("⚠️ デモ口座のためETF取引が制限されている可能性があります")
                        print("⚠️ デモ口座のためETF取引が制限されている可能性があります")
                        return False
                    else:
                        self.logger.info("✅ ETF取引資格あり（通常口座）")
                        print("✅ ETF取引資格あり（通常口座）")
                        return True
                else:
                    self.logger.warning("口座情報が見つからないため、ETF取引資格を確認できません")
                    print("⚠️ 口座情報が見つからないため、ETF取引資格を確認できません")
                    return None
            else:
                self.logger.error(f"口座情報取得失敗: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"ETF取引資格確認エラー: {e}")
            return None

    def check_trading_limits(self):
        """取引制限を総合確認"""
        try:
            self.logger.info("=== 取引制限総合確認 ===")
            
            print("\n=== 取引制限総合確認 ===")
            
            # 1. 買付余力確認
            cash_info = self.check_buying_power_and_cash()
            
            # 2. 口座制限確認
            restrictions = self.check_account_restrictions()
            
            # 3. ETF取引資格確認
            etf_eligible = self.check_etf_trading_eligibility()
            
            # 総合判定
            print("\n=== 総合判定 ===")
            
            can_trade = True
            issues = []
            
            if cash_info:
                if cash_info['buying_power'] < 100:  # 最小取引金額の目安
                    can_trade = False
                    issues.append("買付余力不足")
            
            if restrictions:
                if restrictions['status'] == 'CLOSED' or restrictions['account_type'] == 'DEMO':
                    can_trade = False
                    issues.append("口座制限")
            
            if etf_eligible is False:
                can_trade = False
                issues.append("ETF取引資格なし")
            
            if can_trade:
                print("✅ 取引可能")
            else:
                print("❌ 取引制限あり")
                print(f"   制限内容: {', '.join(issues)}")
            
            return {
                'can_trade': can_trade,
                'issues': issues,
                'cash_info': cash_info,
                'restrictions': restrictions,
                'etf_eligible': etf_eligible
            }
                
        except Exception as e:
            self.logger.error(f"取引制限総合確認エラー: {e}")
            return None

    def run_check(self):
        """制限確認を実行"""
        self.logger.info("=== アカウント制限詳細確認開始 ===")
        
        print("=== アカウント制限詳細確認 ===")
        
        # 取引制限を総合確認
        result = self.check_trading_limits()
        
        if result:
            print(f"\n=== 詳細結果 ===")
            print(f"取引可能: {result['can_trade']}")
            if result['issues']:
                print(f"制限事項: {result['issues']}")
        
        self.logger.info("=== アカウント制限詳細確認完了 ===")

def main():
    """メイン実行関数"""
    print("=== アカウント制限詳細確認 ===")
    
    try:
        checker = AccountRestrictionsChecker()
        checker.run_check()
        print("\n✅ 制限確認完了")
            
    except Exception as e:
        print(f"❌ 制限確認エラー: {e}")

if __name__ == "__main__":
    main() 
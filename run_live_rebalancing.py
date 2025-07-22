#!/usr/bin/env python3
"""
実際の取引を実行するリバランシングスクリプト
注意: このスクリプトは実際の取引を実行します
"""

import os
import sys
import logging
from webull_portfolio_rebalancer import WebullPortfolioRebalancer

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('webull_live_rebalancer.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def run_live_rebalancing():
    """実際の取引を実行するリバランシング"""
    
    print("=== 実際の取引リバランシング ===")
    print("警告: このスクリプトは実際の取引を実行します！")
    
    # 確認プロンプト
    confirm = input("実際の取引を実行しますか？ (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("取引をキャンセルしました。")
        return
    
    try:
        # 設定ファイルを実際の取引用に変更
        original_config = 'webull_config.json'
        live_config = 'webull_config_live.json'
        
        if os.path.exists(live_config):
            # バックアップを作成
            if os.path.exists(original_config):
                backup_config = 'webull_config_backup.json'
                os.rename(original_config, backup_config)
                print(f"元の設定ファイルを {backup_config} にバックアップしました。")
            
            # 実際の取引用設定ファイルを使用
            os.rename(live_config, original_config)
            print("実際の取引用設定ファイルを使用します。")
        else:
            print("実際の取引用設定ファイルが見つかりません。")
            return
        
        # リバランサーを初期化
        rebalancer = WebullPortfolioRebalancer()
        
        # 認証確認
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
        
        # 最終確認
        print("\n=== 最終確認 ===")
        print("以下の設定でリバランシングを実行します:")
        print(f"リバランシング閾値: {rebalancer.config.get('rebalance_threshold', 0.05) * 100}%")
        print(f"最小取引金額: ${rebalancer.config.get('min_trade_amount', 100)}")
        print(f"DRY RUN: {rebalancer.config.get('dry_run', True)}")
        
        final_confirm = input("実行しますか？ (yes/no): ").strip().lower()
        if final_confirm != 'yes':
            print("実行をキャンセルしました。")
            return
        
        # リバランシング実行
        print("\n=== リバランシング実行 ===")
        rebalancer.execute_rebalancing()
        
        print("\n=== リバランシング完了 ===")
        
    except Exception as e:
        logging.error(f"リバランシング実行エラー: {e}")
        print(f"エラー: {e}")
    
    finally:
        # 設定ファイルを元に戻す
        try:
            if os.path.exists('webull_config_backup.json'):
                if os.path.exists(original_config):
                    os.remove(original_config)
                os.rename('webull_config_backup.json', original_config)
                print("設定ファイルを元に戻しました。")
        except Exception as e:
            print(f"設定ファイルの復元エラー: {e}")

if __name__ == "__main__":
    run_live_rebalancing() 
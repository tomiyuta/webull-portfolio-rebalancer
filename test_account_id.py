#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os

def test_account_id_fix():
    """アカウントIDの修正をテスト"""
    
    # 設定ファイルを読み込み
    config_file = 'webull_config_docker.json'
    
    if not os.path.exists(config_file):
        print(f"❌ 設定ファイルが見つかりません: {config_file}")
        return False
    
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        print("=== Hirokaアカウント設定確認 ===")
        print(f"ユーザー名: {config.get('username', 'N/A')}")
        print(f"アカウントID: {config.get('account_id', 'N/A')}")
        print(f"ユーザーID: {config.get('user_id', 'N/A')}")
        print(f"APIキー: {config.get('app_key', 'N/A')[:10]}...") # 最初の10文字のみ表示
        print(f"APIシークレット: {config.get('app_secret', 'N/A')[:10]}...")
        print(f"ドライラン: {config.get('dry_run', True)}")
        print("=" * 40)
        
        # 必要な情報がすべて設定されているかチェック
        required_fields = ['username', 'password', 'app_key', 'app_secret', 'account_id', 'user_id']
        missing_fields = []
        
        for field in required_fields:
            if not config.get(field):
                missing_fields.append(field)
        
        if missing_fields:
            print(f"❌ 以下のフィールドが設定されていません: {', '.join(missing_fields)}")
            return False
        
        # アカウントIDとユーザーIDが一致しているかチェック
        if config.get('account_id') != config.get('user_id'):
            print(f"⚠️  アカウントIDとユーザーIDが異なります:")
            print(f"   アカウントID: {config.get('account_id')}")
            print(f"   ユーザーID: {config.get('user_id')}")
        else:
            print(f"✅ アカウントIDとユーザーIDが一致しています: {config.get('account_id')}")
        
        # 修正内容の確認
        expected_account_id = "08040224131"
        if config.get('account_id') == expected_account_id:
            print(f"✅ アカウントIDが正しく修正されています: {expected_account_id}")
            return True
        else:
            print(f"❌ アカウントIDが期待値と異なります:")
            print(f"   現在: {config.get('account_id')}")
            print(f"   期待: {expected_account_id}")
            return False
            
    except Exception as e:
        print(f"❌ 設定ファイルの読み込みエラー: {e}")
        return False

if __name__ == "__main__":
    print("Hirokaアカウント設定テスト開始...")
    
    success = test_account_id_fix()
    
    if success:
        print("\n✅ アカウント設定テスト完了: 正常")
        print("🔄 次のステップ: API認証テストを実行")
    else:
        print("\n❌ アカウント設定テスト完了: エラーあり")
        print("🔧 設定を修正してから再実行してください")
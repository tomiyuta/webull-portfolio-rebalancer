#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import sys
import os
from webull_complete_rebalancer import WebullCompleteRebalancer

def main():
    """メイン実行関数"""
    parser = argparse.ArgumentParser(description='Webull Portfolio Rebalancer')
    parser.add_argument('--config', '-c', default='webull_config_with_allocation.json',
                       help='設定ファイルのパス (default: webull_config_with_allocation.json)')
    parser.add_argument('--dry-run', action='store_true',
                       help='ドライランモード（実際の取引は実行しない）')
    parser.add_argument('--live', action='store_true',
                       help='本番モード（実際の取引を実行）')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='詳細ログ出力')
    
    args = parser.parse_args()
    
    # 設定ファイルの存在確認
    if not os.path.exists(args.config):
        print(f"❌ 設定ファイルが見つかりません: {args.config}")
        sys.exit(1)
    
    # 実行モードの確認
    if args.dry_run and args.live:
        print("❌ --dry-run と --live は同時に指定できません")
        sys.exit(1)
    
    # デフォルトはドライランモード
    dry_run = True if args.dry_run else (False if args.live else True)
    
    try:
        print("=== Webull Portfolio Rebalancer ===")
        print(f"設定ファイル: {args.config}")
        print(f"実行モード: {'DRY RUN' if dry_run else 'LIVE'}")
        print(f"詳細ログ: {'ON' if args.verbose else 'OFF'}")
        print("=" * 40)
        
        # リバランサーを初期化
        rebalancer = WebullCompleteRebalancer(
            config_file=args.config,
            dry_run=dry_run
        )
        
        # リバランシング実行
        rebalancer.rebalance()
        
        print("=" * 40)
        print("✅ リバランシング完了")
        
    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによって中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
# Webull Portfolio Rebalancer Bot

Webull APIを使用した自動ポートフォリオリバランシングボットです。指定されたポートフォリオ配分に基づいて、自動的に株式・ETFの売買を行い、ポートフォリオを最適化します。

## 機能

- **自動ポートフォリオリバランシング**: 設定された配分に基づく自動売買
- **保守的価格取得**: 複数のAPI（Webull、yfinance）を使用した信頼性の高い価格取得
- **安全な取引実行**: 買付余力チェック、注文監視、エラーハンドリング
- **ドライラン機能**: 実際の取引前にシミュレーション実行
- **詳細ログ**: 取引履歴とログの保存
- **クロスプラットフォーム**: Mac/Linux/Windows対応

## 前提条件

- Python 3.8以上
- Webullアカウント（APIアクセス権限）
- 必要なAPIキーとトークン

## セットアップ

### 1. リポジトリのクローン
```bash
git clone <repository-url>
cd webullbot
```

### 2. 環境セットアップ

**Mac/Linux:**
```bash
./setup_webullbot.sh
```

**Windows:**
```cmd
setup_webullbot.bat
```

### 3. 設定ファイルの編集

`webull_config_with_allocation.json`を編集して、Webull APIの認証情報を設定：

```json
{
  "webull": {
    "username": "your_username",
    "password": "your_password",
    "device_id": "your_device_id",
    "account_id": "your_account_id"
  },
  "dry_run": true,
  "portfolio_config_file": "portfolio.csv"
}
```

### 4. ポートフォリオ設定

`portfolio.csv`を編集して、目標ポートフォリオ配分を設定：

```csv
銘柄,配分(%)
XLU,32.2
TQQQ,32.2
TECL,21.5
GLD,14.1
```

## 使用方法

### ドライラン（テスト実行）

**Mac/Linux:**
```bash
./run_webullbot_dryrun.sh
```

**Windows:**
```cmd
run_webullbot_dryrun.bat
```

### 実際の取引実行

**Mac/Linux:**
```bash
./run_webullbot.sh
```

**Windows:**
```cmd
run_webullbot.bat
```

### 手動実行

```bash
# ドライラン
python run_rebalancing.py

# 実際の取引
python run_rebalancing.py --live
```

## ファイル構成

```
webullbot/
├── webull_complete_rebalancer.py  # メインのリバランシングロジック
├── run_rebalancing.py             # 実行スクリプト
├── webull_config_with_allocation.json  # 設定ファイル
├── portfolio.csv                  # ポートフォリオ配分設定
├── data/
│   └── trades.csv                 # 取引ログ
├── logs/                          # ログファイル
├── requirements.txt               # Python依存関係
├── setup_webullbot.sh            # Mac/Linuxセットアップ
├── setup_webullbot.bat           # Windowsセットアップ
├── run_webullbot.sh              # Mac/Linux実行
├── run_webullbot.bat             # Windows実行
├── run_webullbot_dryrun.sh       # Mac/Linuxドライラン
└── run_webullbot_dryrun.bat      # Windowsドライラン
```

## 主要機能の詳細

### 1. ポートフォリオリバランシング

- 現在のポジションと目標配分を比較
- 必要な売買注文を自動計算
- 買付余力を考慮した安全な取引実行

### 2. 保守的価格取得

- Webull API（プライマリ）
- yfinance（フォールバック）
- 複数APIの結果を比較・検証

### 3. 安全機能

- 買付余力チェック
- 注文監視とステータス確認
- エラーハンドリングとリトライ機能
- ドライラン機能

### 4. ログと監視

- 詳細な取引ログ
- エラーログ
- パフォーマンス追跡

## 設定オプション

### webull_config_with_allocation.json

```json
{
  "webull": {
    "username": "your_username",
    "password": "your_password", 
    "device_id": "your_device_id",
    "account_id": "your_account_id"
  },
  "dry_run": true,
  "portfolio_config_file": "portfolio.csv",
  "safety_margin": 0.0,
  "max_retries": 3,
  "retry_delay": 1
}
```

### portfolio.csv

```csv
銘柄,配分(%)
SYMBOL1,PERCENTAGE1
SYMBOL2,PERCENTAGE2
...
```

## トラブルシューティング

### よくある問題

1. **API認証エラー**
   - 設定ファイルの認証情報を確認
   - WebullアカウントのAPIアクセス権限を確認

2. **買付余力不足**
   - アカウントの利用可能資金を確認
   - ポートフォリオ配分の調整を検討

3. **価格取得エラー**
   - インターネット接続を確認
   - シンボルの正確性を確認

### ログの確認

```bash
# 最新のログを確認
tail -f logs/webullbot.log

# エラーログを確認
grep "ERROR" logs/webullbot.log
```

## セキュリティ

- API認証情報は設定ファイルに保存
- 本番環境では環境変数の使用を推奨
- 定期的なパスワード変更を推奨

## 免責事項

このボットは教育目的で作成されています。実際の取引には十分な注意を払い、リスクを理解した上で使用してください。作者は取引結果について一切の責任を負いません。

## ライセンス

このプロジェクトは個人使用目的で作成されています。

## サポート

問題や質問がある場合は、GitHubのIssuesページで報告してください。

## 更新履歴

- v1.0.0: 初期リリース
- v1.1.0: 安全機能の追加
- v1.2.0: クロスプラットフォーム対応
- v1.3.0: ログ機能の改善 
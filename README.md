# Webull Portfolio Rebalancer Bot

Webull APIを使用した自動ポートフォリオリバランシングボットです。米国株・ETFの価格情報を取得し、設定された目標配分に基づいて自動的にリバランシングを実行します。

## 🚀 機能

- **リアルタイム価格取得**: Webull APIを使用した高速な価格取得
- **自動リバランシング**: 設定された目標配分に基づく自動調整
- **ドライラン機能**: 実際の取引前にシミュレーション実行
- **複数銘柄対応**: 米国株・ETFの幅広い銘柄に対応
- **ログ機能**: 詳細な実行ログの記録

## 📋 必要条件

- Python 3.8以上
- Webullアカウント
- Webull API認証情報

## 🛠️ セットアップ

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd webullbot
```

### 2. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 3. 設定ファイルの準備

#### 認証情報の設定

`webullkey.txt`ファイルを作成し、以下の形式で認証情報を記載：

```
ID:your_username
PASS:your_password
口座：your_account_id
APIkey:your_app_key
API Secret:your_app_secret
```

#### 設定ファイルの作成

`webull_config.json`ファイルを作成：

```json
{
  "app_key": "your_app_key",
  "app_secret": "your_app_secret", 
  "account_id": "your_account_id",
  "username": "your_username",
  "password": "your_password",
  "rebalance_threshold": 0.05,
  "min_trade_amount": 100,
  "dry_run": true
}
```

#### 目標ポートフォリオの設定

`trades.csv`ファイルを作成：

```csv
symbol,allocation
SPY,0.3
QQQ,0.25
VTI,0.2
AAPL,0.1
MSFT,0.08
GOOGL,0.07
```

## 🎯 使用方法

### テスト実行

```bash
python3 webull_portfolio_rebalancer.py
```

### 実際の取引実行

```bash
python3 run_live_rebalancing.py
```

## 📁 ファイル構成

```
webullbot/
├── webull_portfolio_rebalancer.py  # メインのリバランシングプログラム
├── run_live_rebalancing.py         # 実際の取引用スクリプト
├── webull_config.json              # 設定ファイル
├── webullkey.txt                   # 認証情報
├── trades.csv                      # 目標ポートフォリオ設定
├── requirements.txt                # 依存関係
├── config_example.json             # 設定ファイル例
├── trades_example.csv              # ポートフォリオ設定例
├── .gitignore                      # Git除外設定
└── README.md                       # このファイル
```

## ⚙️ 設定項目

### webull_config.json

| 項目 | 説明 | デフォルト |
|------|------|------------|
| `app_key` | Webull APIキー | 必須 |
| `app_secret` | Webull APIシークレット | 必須 |
| `account_id` | アカウントID | 必須 |
| `username` | ユーザー名 | 必須 |
| `password` | パスワード | 必須 |
| `rebalance_threshold` | リバランシング閾値 | 0.05 |
| `min_trade_amount` | 最小取引金額 | 100 |
| `dry_run` | ドライランモード | true |

### trades.csv

| 項目 | 説明 |
|------|------|
| `symbol` | 銘柄シンボル |
| `allocation` | 目標配分（0.0-1.0） |

## 🔒 セキュリティ

- 認証情報は`webullkey.txt`と`webull_config.json`に保存
- これらのファイルはGitにコミットしないでください
- 実際の取引前に必ずドライランモードでテストしてください

## 📊 対応銘柄

### 米国株
- NASDAQ上場銘柄（AAPL, GOOGL, MSFT, AMZN, TSLA等）
- NYSE上場銘柄

### 米国ETF
- SPY（S&P 500 ETF）
- QQQ（NASDAQ-100 ETF）
- VTI（Total Stock Market ETF）
- その他主要ETF

## 🚨 注意事項

1. **リスク**: 投資にはリスクが伴います。損失の可能性があります
2. **テスト**: 実際の取引前に必ずドライランモードでテストしてください
3. **監視**: ボットの動作を定期的に監視してください
4. **認証**: 認証情報の管理には十分注意してください

## 📝 ログ

実行ログは`webull_rebalancer.log`に記録されます：

- 価格取得状況
- リバランシング計算結果
- 取引実行状況
- エラー情報

## 🤝 貢献

バグ報告や機能要望は、GitHubのIssuesでお知らせください。

## 📄 ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## ⚠️ 免責事項

このソフトウェアは教育目的で提供されています。実際の投資判断は自己責任で行ってください。作者は投資損失について一切責任を負いません。 
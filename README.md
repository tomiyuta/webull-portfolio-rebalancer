# WebullBot Unified - 統合版ポートフォリオリバランサー

Webull APIを使用した統合版ポートフォリオリバランサーボットです。残高確認、買い付け、売却、リバランシング機能を全て統合し、シンプルで保守しやすい構造になっています。

## 🚀 特徴

### ✅ 統合された機能
- **残高確認**: アカウント残高と買付余力の取得
- **ポジション確認**: 現在の保有ポジションの取得
- **買い付け**: サンプルコード準拠の購入機能
- **売却**: 成功コード準拠の売却機能
- **リバランシング**: 自動ポートフォリオ調整
- **情報表示**: 統合されたアカウント情報と投資分析

### 🔧 技術的特徴
- **単一ファイル**: 全ての機能が`webull_bot_unified.py`に統合
- **API統一**: 買い付け・売却で統一されたAPI呼び出し
- **エラーハンドリング**: 包括的なエラー処理とログ機能
- **キャッシュ機能**: 価格とinstrument_idの効率的なキャッシュ
- **ドライラン**: 安全なテスト実行モード
- **相場取得**: Webull MDATAを優先し、失敗時は`yfinance`にフォールバック（1分キャッシュ）

## 📋 必要要件

### システム要件
- Python 3.8以上
- Docker（推奨）
- Webull API アカウント

### Python依存関係（抜粋）
```
webull-python-sdk-core
webull-python-sdk-trade
webull-python-sdk-mdata
webull-python-sdk-trade-events-core
pandas
numpy
yfinance  # MDATA失敗時のフォールバック
```

## 🛠️ セットアップ

### 1. リポジトリのクローン
```bash
git clone <repository-url>
cd webull-portfolio-rebalancer
```

### 2. 設定ファイルの準備

#### `webull_config_with_allocation.json`の設定
```json
{
  "app_key": "your_app_key",
  "app_secret": "your_app_secret",
  "account_id": "your_account_id",
  "portfolio_config_file": "portfolio.csv",
  "dry_run": true,
  "api_settings": {
    "max_retries": 3,
    "retry_delay": 1,
    "rate_limit_delay": 2
  },
  "trading_settings": {
    "price_slippage": 0.01,
    "min_order_amount": 1,
    "max_order_amount": 5000,
    "order_timeout": 300,
    "conservative_price_margin": 0.03
  }
}
```

#### `portfolio.csv`の設定
```csv
symbol,allocation_percentage
XLU,30.0
TQQQ,30.0
TECL,20.0
GLD,15.0
NUGT,5.0
```

### 3. Docker環境での実行（推奨）

#### Dockerイメージのビルド
```bash
docker build -t webull-rebalancer .
```

#### 実行
```bash
# ドライラン実行
docker run --rm -v ${PWD}:/app webull-rebalancer python3 webull_bot_unified.py

# または実行スクリプト使用
./run_webullbot_dryrun.sh  # Linux/Mac
run_webullbot_dryrun.bat   # Windows
```

### 4. gRPC注文イベント購読（任意）

注文のステータス変更をリアルタイムに受信します。

- Dockerで購読（推奨）
```bash
docker build -t webull-rebalancer .
docker run --rm -e APP_MODE=events -v ${PWD}:/app webull-rebalancer
```

- ローカルで購読
```bash
python3 subscribe_trade_events.py
```

ログは`logs/trade_events_*.log`に出力されます。

## 📖 使用方法

### 基本的な実行

#### 1. ドライラン（推奨）
```bash
# 設定ファイルでdry_run: trueに設定
docker run --rm -v ${PWD}:/app webull-rebalancer python3 webull_bot_unified.py
```

#### 2. 実際の取引実行
```bash
# 設定ファイルでdry_run: falseに設定
docker run --rm -v ${PWD}:/app webull-rebalancer python3 webull_bot_unified.py
```

### 機能別実行

#### アカウント情報の表示
```python
from webull_bot_unified import WebullBotUnified

bot = WebullBotUnified(dry_run=True)
bot.show_account_info()
```

#### 投資分析の表示
```python
bot.show_investment_analysis()
```

#### リバランシングの実行
```python
success = bot.execute_rebalancing()
```

#### gRPCイベント購読のみを起動（Docker）
```bash
docker run --rm -e APP_MODE=events -v ${PWD}:/app webull-rebalancer
```

#### 個別取引の実行
```python
# 買い付け
success = bot.buy_stock("XLU", 10)

# 売却
success = bot.sell_stock("XLU", 5)

# 全ポジション売却
success = bot.sell_all_positions()
```

## 🔧 API呼び出し仕様

### 買い付け（v2 仕様）
```python
order = {
    "client_order_id": uuid.uuid4().hex,
    "symbol": symbol,
    "instrument_type": "EQUITY",
    "market": "US",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": str(int(quantity)),
    "limit_price": f"{limit_price:.2f}",
    "support_trading_session": "N",
    "time_in_force": "DAY",
    "entrust_type": "QTY",
    "account_tax_type": "SPECIFIC"
}
prev = self.api.order_v2.preview_order(self.account_id, order)
resp = self.api.order_v2.place_order(self.account_id, order)
```

### 売却（成功コード準拠）
```python
order = {
    "client_order_id": uuid.uuid4().hex,
    "symbol": symbol,
    "instrument_type": "EQUITY",
    "market": "US",
    "side": "SELL",
    "order_type": "MARKET",
    "quantity": str(int(quantity)),
    "support_trading_session": "N",
    "time_in_force": "DAY",
    "entrust_type": "QTY",
    "account_tax_type": "SPECIFIC"
}

# Preview → Place
preview_response = self.api.order_v2.preview_order(self.account_id, order)
response = self.api.order_v2.place_order(self.account_id, order)
```

## 📊 出力例

### アカウント情報
```
=== アカウント情報 ===
Account ID: 1099757484888625152
Dry Run Mode: True

--- USD残高 ---
利用可能現金: $10,896.76
買付余力: $10,896.76
総現金: $13,322.16

--- 現在のポジション ---
ポジションなし

--- 目標ポートフォリオ ---
XLU: 100.0%
```

### 投資分析
```
=== 投資分析 ===
総ポートフォリオ価値: $10,896.76
利用可能現金: $10,896.76
ポジション価値: $0.00

--- 目標投資額 ---
XLU: $10,896.76 (127.02株 @ $85.78)

--- リバランシング分析 ---
必要な取引数: 1
購入取引: 1件
総購入金額: $10,896.76
```

### リバランシング実行
```
=== リバランシング実行（DRY RUN） ===
✅ リバランシング完了
```

## 📁 ファイル構成

```
webull-portfolio-rebalancer/
├── webull_bot_unified.py          # 統合版メインファイル
├── webull_config_with_allocation.json  # メイン設定ファイル
├── portfolio.csv                   # ポートフォリオ設定
├── Dockerfile                      # Dockerイメージ定義
├── entrypoint.sh                   # APP_MODEで起動モード切替
├── requirements.txt                # Python依存関係
├── run_webullbot_dryrun.sh        # Linux/Mac実行スクリプト
├── run_webullbot_dryrun.bat       # Windows実行スクリプト
├── subscribe_trade_events.py       # gRPC注文イベント購読
├── README.md                       # このファイル
├── CHANGELOG.md                    # 変更履歴
├── logs/                           # ログディレクトリ
│   └── webull_bot_YYYYMMDD.log    # 実行ログ
└── data/                           # データディレクトリ
    └── trades.csv                  # 取引履歴
```

## ⚠️ 注意事項

### セキュリティ
- APIキーとシークレットは安全に管理してください
- 設定ファイルはGitにコミットしないでください
- 本番環境では適切なアクセス制御を設定してください

### リスク管理
- 必ずドライランでテストしてから実際の取引を実行してください
- 取引金額とリスク許容度を十分に検討してください
- 市場状況に応じて適切な設定調整を行ってください

### API制限
- Webull APIの利用制限に注意してください
- レート制限を考慮した適切な間隔でAPI呼び出しを行ってください

## 🐛 トラブルシューティング

### よくある問題

#### 1. API認証エラー
```
エラー: app_keyまたはapp_secretが設定されていません
解決策: webull_config_with_allocation.jsonの設定を確認
```

#### 2. アカウントIDエラー
```
エラー: アカウントIDの取得に失敗しました
解決策: 設定ファイルのaccount_idを確認
```

#### 3. 買付余力不足エラー
```
エラー: ORDER_BUYING_POWER_NOT_ENOUGH
解決策: 買付余力を確認し、取引金額を調整
```

#### 4. API互換性エラー
```
エラー: 'AccountV2' object has no attribute 'get_positions'
解決策: Webull SDKのバージョンを確認
```

### ログの確認
```bash
# 最新のログを確認
tail -f logs/webull_bot_$(date +%Y%m%d).log
```

## 🔄 更新履歴

### v2.0.0 (2025-08-01)
- 統合版リリース
- 全ての機能を単一ファイルに統合
- サンプルコード準拠の買い付け機能
- 成功コード準拠の売却機能
- 大幅なファイル構成の簡素化

### v1.x.x (以前のバージョン)
- 分散ファイル構成
- 個別機能別スクリプト
- 複雑なAPI呼び出し

## 📞 サポート

### 問題報告
- GitHub Issuesで問題を報告してください
- ログファイルとエラーメッセージを添付してください

### 機能要望
- 新機能の要望はGitHub Issuesで提案してください
- 具体的なユースケースを説明してください

## 📄 ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## ⚖️ 免責事項

このソフトウェアは教育・研究目的で提供されています。実際の取引での使用は自己責任で行ってください。作者は取引結果について一切の責任を負いません。

---

**WebullBot Unified** - シンプルで強力なポートフォリオリバランサー 
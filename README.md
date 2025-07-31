# Webull Portfolio Rebalancer Bot

Webull APIを使用した自動ポートフォリオリバランシングボットです。指定されたポートフォリオ配分に基づいて、自動的に株式・ETFの売買を行い、ポートフォリオを最適化します。

## 機能

- **自動ポートフォリオリバランシング**: 設定された配分に基づく自動売買
- **保守的価格取得**: 複数のAPI（Webull、yfinance）を使用した信頼性の高い価格取得
- **安全な取引実行**: 買付余力チェック、注文監視、エラーハンドリング
- **ドライラン機能**: 実際の取引前にシミュレーション実行
- **詳細ログ**: 取引履歴とログの保存
- **クロスプラットフォーム**: Mac/Linux/Windows対応
- **Docker対応**: 環境に依存しない実行
- **アカウントID自動取得**: 設定ファイルの手動更新不要
- **マルチアカウント対応**: 簡単なアカウント切り替え
- **設定ファイル自動更新**: 実行時に必要な情報を自動保存
- **データ品質管理**: 取引履歴の自動検証と修正
- **パフォーマンス分析**: 取引結果の詳細分析と改善提案
- **取引結果追跡**: 期間指定での取引結果追跡とトレンド分析

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

**Dockerを使用（推奨）:**
```bash
# Dockerイメージのビルド
docker build -t webullbot .

# または、直接実行（初回時に自動ビルド）
docker run --rm -v $(pwd):/app webullbot python3 run_rebalancing.py
```

**従来の方法（Mac/Linux）:**
```bash
./setup_webullbot.sh
```

**従来の方法（Windows）:**
```cmd
setup_webullbot.bat
```

### 3. 設定ファイルの編集

**初回セットアップ:**
```bash
# サンプル設定ファイルをコピー
cp webull_config_sample.json webull_config_with_allocation.json
```

`webull_config_with_allocation.json`を編集して、Webull APIの認証情報と取引設定を設定：

#### 必要な情報の取得方法

**Webullアプリから取得できる情報:**
1. **ユーザーID**: WebullアプリのログインID
2. **パスワード**: Webullアプリのログインパスワード
3. **口座番号**: Webullアプリの口座情報から取得（例: CJP0871702）

**Webull API開発者ポータルから取得:**
1. **API Key**: Webull開発者ポータルでアプリケーション作成時に取得
2. **API Secret**: Webull開発者ポータルでアプリケーション作成時に取得

**自動取得される情報（設定不要）:**
- **Account ID**: プログラム実行時に自動取得
- **Subscription ID**: プログラム実行時に自動取得
- **User ID**: プログラム実行時に自動取得

#### 設定ファイル例

```json
{
  "username": "your_webull_username",
  "password": "your_webull_password",
  "app_key": "your_api_key_from_webull_portal",
  "app_secret": "your_api_secret_from_webull_portal",
  "account_id": "",
  "account_number": "your_account_number_from_webull_app",
  "subscription_id": "",
  "user_id": "",
  "access_token": "",
  "refresh_token": "",
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
    "max_order_amount": 10000,
    "order_timeout": 300,
    "conservative_price_margin": 0.0
  },
  "rebalancing_settings": {
    "mode": "total_value",
    "include_existing_positions": true,
    "sell_existing_positions": true,
    "min_trade_amount": 100,
    "max_trade_amount": 10000,
    "rebalance_threshold": 0.05
  },
  "logging_settings": {
    "log_level": "DEBUG",
    "log_to_file": true,
    "log_to_console": true
  }
}
```

#### 新しいアカウントへの変更方法

1. **設定ファイルの更新**:
   ```json
   {
     "username": "新しいユーザーID",
     "password": "新しいパスワード",
     "app_key": "新しいAPIキー",
     "app_secret": "新しいAPIシークレット",
     "account_id": "",
     "account_number": "新しい口座番号",
     "subscription_id": "",
     "user_id": "",
     "access_token": "",
     "refresh_token": ""
   }
   ```

2. **プログラム実行**:
   - プログラムが自動的に新しいアカウントの`account_id`、`subscription_id`、`user_id`を取得
   - 設定ファイルが自動的に更新される

#### アカウント情報の例

**例1:**
```json
{
  "username": "08040224131",
  "password": "Hiroka103",
  "app_key": "ca0f603e7a6fde604a236a4db6ae1c05",
  "app_secret": "6acad5f331fe85bfb5ea59c385a27d13",
  "account_number": "CJP0871702"
}
```

**例2:**
```json
{
  "username": "08040040157",
  "password": "0157ppqQ",
  "app_key": "cfbd1361f55439c334268f072979b021",
  "app_secret": "14706cf44f4bddb708227951a68e3159",
  "account_number": "CJP0837276"
}
```

#### 保守的価格マージン設定

`trading_settings.conservative_price_margin`で保守的価格マージンを設定できます：

- **0.0** (デフォルト): 保守的マージンなし（基本価格をそのまま使用）
- **0.01**: 1%の保守的マージン（基本価格 × 1.01）
- **0.02**: 2%の保守的マージン（基本価格 × 1.02）

**保守的価格の目的**:
- 価格変動リスクの軽減
- 注文成功率の向上
- 資金不足の防止
- スリッページ対策

**初期設定について**:
- **推奨初期値**: `0.0` (0%)
- **理由**: 価格取得から実際の取引までの時間差が少ないため
- **必要に応じて調整**: 市場のボラティリティや取引頻度に応じて設定

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

### パフォーマンス分析と取引結果追跡

**パフォーマンス分析の実行:**
```bash
# 過去30日間のパフォーマンス分析
docker run --rm -v $(pwd):/app webullbot python3 -c "from webull_complete_rebalancer import WebullCompleteRebalancer; rebalancer = WebullCompleteRebalancer(); rebalancer.analyze_performance('30d')"

# 過去7日間のパフォーマンス分析
docker run --rm -v $(pwd):/app webullbot python3 -c "from webull_complete_rebalancer import WebullCompleteRebalancer; rebalancer = WebullCompleteRebalancer(); rebalancer.analyze_performance('7d')"
```

**取引結果追跡の実行:**
```bash
# 過去7日間の取引結果追跡
docker run --rm -v $(pwd):/app webullbot python3 -c "from webull_complete_rebalancer import WebullCompleteRebalancer; rebalancer = WebullCompleteRebalancer(); rebalancer.track_trade_results(days=7)"

# 特定の取引IDの追跡
docker run --rm -v $(pwd):/app webullbot python3 -c "from webull_complete_rebalancer import WebullCompleteRebalancer; rebalancer = WebullCompleteRebalancer(); rebalancer.track_trade_results(trade_id='TRADE_001')"
```

### Dockerを使用した実行（推奨）

**ドライラン（テスト実行）:**
```bash
# 総資産価値ベースリバランス（デフォルト）
docker run --rm -v $(pwd):/app webullbot python3 run_rebalancing.py

# 利用可能資金ベースリバランス
docker run --rm -v $(pwd):/app webullbot python3 run_rebalancing.py --mode available_cash
```

**実際の取引実行:**
```bash
# 設定ファイルで dry_run: false に変更後
# 総資産価値ベースリバランス（デフォルト）
docker run --rm -v $(pwd):/app webullbot python3 run_rebalancing.py

# 利用可能資金ベースリバランス
docker run --rm -v $(pwd):/app webullbot python3 run_rebalancing.py --mode available_cash
```

### 従来の方法

**ドライラン（テスト実行）:**

**Mac/Linux:**
```bash
./run_webullbot_dryrun.sh
```

**Windows:**
```cmd
run_webullbot_dryrun.bat
```

**実際の取引実行:**

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
# ドライラン（総資産価値ベース）
python run_rebalancing.py

# ドライラン（利用可能資金ベース）
python run_rebalancing.py --mode available_cash

# 実際の取引（総資産価値ベース）
python run_rebalancing.py --live

# 実際の取引（利用可能資金ベース）
python run_rebalancing.py --live --mode available_cash
```

## ファイル構成

```
webullbot/
├── webull_complete_rebalancer.py  # メインのリバランシングロジック
├── run_rebalancing.py             # 実行スクリプト
├── webull_config_sample.json      # サンプル設定ファイル
├── webull_config_with_allocation.json  # 実際の設定ファイル（.gitignoreで除外）
├── portfolio.csv                  # ポートフォリオ配分設定
├── data/
│   ├── trades.csv                 # 取引ログ（自動検証・修正機能付き）
│   ├── trades_example.csv         # サンプル取引ログ
│   ├── performance_analysis_*.json # パフォーマンス分析結果
│   └── *_trades_results_*.json    # 取引結果追跡データ
├── logs/                          # ログファイル（.gitignoreで除外）
├── requirements.txt               # Python依存関係
├── Dockerfile                     # Dockerコンテナ定義
├── setup_webullbot.sh            # Mac/Linuxセットアップ
├── setup_webullbot.bat           # Windowsセットアップ
├── run_webullbot.sh              # Mac/Linux実行
├── run_webullbot.bat             # Windows実行
├── run_webullbot_dryrun.sh       # Mac/Linuxドライラン
└── run_webullbot_dryrun.bat      # Windowsドライラン
```

## 主要機能の詳細

### 1. ポートフォリオリバランシング

#### 利用可能資金ベースリバランス（従来方式）
- 現在のポジションと目標配分を比較
- 利用可能資金のみを使用して購入
- 買付余力を考慮した安全な取引実行

#### 総資産価値ベースリバランス（改善方式）
- 既存ポジションを含む総資産価値を使用
- 段階的リバランス（売却→購入）
- より効率的な資金活用
- 目標配分に含まれない銘柄の自動売却
- 過剰ポジションの自動調整

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
- データ品質監視
- 取引履歴の自動検証

## 設定オプション

### リバランスモード設定

#### 総資産価値ベースリバランス（推奨）
```json
{
  "rebalancing_settings": {
    "mode": "total_value",
    "include_existing_positions": true,
    "sell_existing_positions": true,
    "min_trade_amount": 100,
    "max_trade_amount": 10000,
    "rebalance_threshold": 0.05
  }
}
```

#### 利用可能資金ベースリバランス（従来方式）
```json
{
  "rebalancing_settings": {
    "mode": "available_cash",
    "include_existing_positions": false,
    "sell_existing_positions": false,
    "min_trade_amount": 100,
    "max_trade_amount": 10000,
    "rebalance_threshold": 0.05
  }
}
```

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
   - アカウントIDが自動取得されているか確認

2. **買付余力不足**
   - アカウントの利用可能資金を確認
   - ポートフォリオ配分の調整を検討

3. **価格取得エラー**
   - インターネット接続を確認
   - シンボルの正確性を確認

4. **アカウントID取得エラー**
   - ユーザーID、パスワード、APIキーが正しいか確認
   - Webullアプリでログインできるか確認
   - 口座番号が正しいか確認

5. **Docker実行エラー**
   - Dockerがインストールされているか確認
   - Dockerデーモンが起動しているか確認
   - ポートが競合していないか確認

6. **取引履歴データ品質エラー**
   - `data/trades.csv`の構造を確認
   - 日付フォーマットの統一性を確認
   - 欠損値の処理状況を確認
   - データ検証機能が正常に動作しているか確認

7. **パフォーマンス分析エラー**
   - 分析期間内に取引データが存在するか確認
   - 取引履歴の日付フォーマットを確認
   - 必要なデータフィールドが存在するか確認

### ログの確認

```bash
# 最新のログを確認
tail -f logs/webullbot.log

# エラーログを確認
grep "ERROR" logs/webullbot.log

# Dockerログの確認
docker logs <container_id>

# 取引履歴の確認
head -10 data/trades.csv

# パフォーマンス分析結果の確認
ls -la data/performance_analysis_*.json

# 取引結果追跡データの確認
ls -la data/*_trades_results_*.json
```

### アカウント変更時の確認事項

1. **設定ファイルの更新**:
   - `username`: 新しいユーザーID
   - `password`: 新しいパスワード
   - `app_key`: 新しいAPIキー
   - `app_secret`: 新しいAPIシークレット
   - `account_number`: 新しい口座番号
   - `account_id`, `subscription_id`, `user_id`: 空文字列に設定

2. **実行確認**:
   - プログラムが正常に起動するか確認
   - アカウントIDが自動取得されるか確認
   - 口座残高が正しく取得されるか確認

## セキュリティ

- API認証情報は設定ファイルに保存
- 本番環境では環境変数の使用を推奨
- 定期的なパスワード変更を推奨
- **重要**: 個人情報を含むファイルは`.gitignore`で除外されています
  - `webull_config_with_allocation.json`: 実際の設定ファイル
  - `webullkey.txt`, `webullkey2.txt`: 個人のAPIキー情報
  - `logs/`: 実行ログ（個人情報が含まれる可能性）
  - `data/trades.csv`: 取引履歴（個人の取引情報）
  - `data/performance_analysis_*.json`: パフォーマンス分析結果
  - `data/*_trades_results_*.json`: 取引結果追跡データ
- **初回セットアップ**: `webull_config_sample.json`をコピーして使用してください

## 免責事項

このボットは教育目的で作成されています。実際の取引には十分な注意を払い、リスクを理解した上で使用してください。作者は取引結果について一切の責任を負いません。

## データ品質管理

### 取引履歴の自動検証

システムは取引履歴の保存時に自動的にデータ品質を検証し、以下の処理を行います：

- **フィールド数の統一**: 全取引レコードのフィールド数を統一
- **日付フォーマットの標準化**: 複数の日付フォーマットに対応
- **数値データの型変換**: 適切なデータ型への自動変換
- **欠損値の処理**: 空の値を適切なデフォルト値で補完
- **データの正規化**: action、symbolフィールドの統一

### パフォーマンス分析機能

- **取引パフォーマンス分析**: 成功率、取引サイズ、取引頻度の分析
- **ポートフォリオパフォーマンス分析**: 買い/売りボリューム、回転率の分析
- **リスク指標分析**: ボラティリティ、最大ドローダウン、シャープレシオの計算
- **実行品質分析**: 実行速度、価格精度、約定品質の評価
- **コスト分析**: 手数料、スリッページ、コスト効率の分析
- **ベンチマーク比較**: SPY等との相対パフォーマンス分析
- **改善提案の自動生成**: データ駆動の改善提案

### 取引結果追跡機能

- **期間指定追跡**: 任意の期間での取引結果追跡
- **特定取引追跡**: 取引ID指定での詳細追跡
- **セッション追跡**: セッション全体の結果追跡
- **トレンド分析**: 実行品質と成功率のトレンド分析
- **改善提案**: 取引結果に基づく改善提案の生成

## ライセンス

このプロジェクトは個人使用目的で作成されています。

## サポート

問題や質問がある場合は、GitHubのIssuesページで報告してください。

## 更新履歴

- v1.0.0: 初期リリース
- v1.1.0: 安全機能の追加
- v1.2.0: クロスプラットフォーム対応
- v1.3.0: ログ機能の改善
- v1.4.0: Docker対応とアカウントID自動取得機能の追加
  - Dockerコンテナでの実行に対応
  - アカウントID、Subscription ID、User IDの自動取得機能
  - 新しいアカウントへの簡単な切り替え機能
  - 設定ファイルの自動更新機能
  - エラーハンドリングの改善
- v1.5.0: 取引履歴の完全化とデータ品質改善
  - CSVファイル構造の修正とフィールド数の統一
  - 日付フォーマットの標準化（複数フォーマット対応）
  - 欠損値の適切な処理とデータ型の統一
  - データ検証機能の実装（`_validate_trade_data`メソッド）
  - 取引履歴保存機能の改善
  - パフォーマンス分析機能の動作確認
  - 取引結果追跡機能の動作確認
  - エラーハンドリングの強化 
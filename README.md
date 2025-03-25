# Amazon 割引商品検索 & SNS自動投稿ツール

Amazon PAAPIを使用して割引率の高い商品を検索し、X(Twitter)とThreadsに自動で投稿するツールです。GitHub Actionsで定期実行できます。

## 機能

- **キーワード検索**: 指定したキーワードで商品を検索
- **カテゴリ指定**: 特定のカテゴリに絞って検索可能
- **割引率計算**: 元の価格と現在価格から割引率を自動計算
- **割引率フィルタリング**: 指定した割引率以上の商品だけを抽出
- **割引率順表示**: 割引率の高い順に商品を表示
- **X(Twitter)自動投稿**: 割引商品情報をXに自動投稿
- **Threads自動投稿**: 割引商品情報をThreadsに自動投稿
- **重複投稿防止**: 同じ商品を複数回投稿しないように制御

## セットアップ方法

### 必要な情報

1. **Amazon PA-API設定**
   - PA-API-KEY
   - PA-API-SECRET
   - PARTNER-TAG (アソシエイトタグ)

2. **X(Twitter) API設定**
   - CONSUMER-KEY
   - CONSUMER-SECRET
   - ACCESS-TOKEN
   - ACCESS-TOKEN-SECRET

3. **Threads API設定** (オプション)
   - THREADS-ACCESS-TOKEN
   - THREADS-USER-ID

### ローカルでの実行

1. リポジトリをクローン
```bash
git clone https://github.com/yourusername/amazon-discount-finder.git
cd amazon-discount-finder
```

2. 仮想環境を作成して有効化
```bash
python -m venv venv
source venv/bin/activate  # Windowsの場合: venv\Scripts\activate
```

3. 依存パッケージをインストール
```bash
pip install tweepy python-dotenv requests
```

4. `.env`ファイルを作成して認証情報を設定
```
PA_API_KEY=あなたのPAAPIキー
PA_API_SECRET=あなたのPAAPIシークレット
PARTNER_TAG=あなたのアソシエイトタグ
TWITTER_CONSUMER_KEY=あなたのTwitterコンシューマーキー
TWITTER_CONSUMER_SECRET=あなたのTwitterコンシューマーシークレット
TWITTER_ACCESS_TOKEN=あなたのTwitterアクセストークン
TWITTER_ACCESS_TOKEN_SECRET=あなたのTwitterアクセストークンシークレット
THREADS_ACCESS_TOKEN=あなたのThreadsアクセストークン
THREADS_USER_ID=あなたのThreadsユーザーID
```

5. スクリプトを実行
```bash
python amazon_discount_finder.py
```

### GitHub Actionsでの設定

1. リポジトリの「Settings」→「Secrets and variables」→「Actions」で以下のシークレットを設定:
   - `PA_API_KEY`
   - `PA_API_SECRET`
   - `PARTNER_TAG`
   - `TWITTER_CONSUMER_KEY`
   - `TWITTER_CONSUMER_SECRET`
   - `TWITTER_ACCESS_TOKEN`
   - `TWITTER_ACCESS_TOKEN_SECRET`
   - `THREADS_ACCESS_TOKEN` (オプション)
   - `THREADS_USER_ID` (オプション)

2. GitHubのワークフローが自動的に実行されます（デフォルトでは1日2回）

## カスタマイズ

### 検索設定

`search_config.json`を編集して検索キーワードやカテゴリを追加・変更できます:

```json
{
  "min_discount_percent": 20,
  "search_items": [
    {
      "keyword": "ワイヤレスイヤホン",
      "category": "Electronics"
    },
    {
      "keyword": "スマートフォン",
      "category": "Electronics"
    }
  ]
}
```

### 主なカテゴリ

- `All` (すべて)
- `Electronics` (家電&カメラ)
- `Kitchen` (ホーム&キッチン)
- `Apparel` (服&ファッション小物)
- `Books` (本)
- `VideoGames` (ゲーム)
- `Beauty` (ビューティ)

## ライセンス

このプロジェクトはMITライセンスで提供されています。

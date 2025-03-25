import os
import json
import logging
import requests
import hashlib
import hmac
import argparse
import tweepy
import time
from datetime import datetime
from dotenv import load_dotenv

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("discount_finder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("discount-finder")

# 環境変数の読み込み
load_dotenv()

# PA-API設定
PA_API_KEY = os.getenv("PA_API_KEY")
PA_API_SECRET = os.getenv("PA_API_SECRET")
PARTNER_TAG = os.getenv("PARTNER_TAG")
MARKETPLACE = "www.amazon.co.jp"
REGION = "us-west-2"  # PA-APIのリージョン

# X API設定
TWITTER_CONSUMER_KEY = os.getenv("TWITTER_CONSUMER_KEY")
TWITTER_CONSUMER_SECRET = os.getenv("TWITTER_CONSUMER_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# Threads API設定（Meta Graph API）
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN")
THREADS_USER_ID = os.getenv("THREADS_USER_ID")

# 設定
CONFIG_FILE = "search_config.json"
RESULTS_FILE = "discount_results.json"
MIN_DISCOUNT_PERCENT = 20  # デフォルトの最小割引率

def sign_request(host, path, payload, target="GetItems"):
    """PA-APIリクエストに署名を生成"""
    # リクエスト日時
    amz_date = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    datestamp = datetime.utcnow().strftime('%Y%m%d')
    
    # 署名に必要な値
    service = 'ProductAdvertisingAPI'
    algorithm = 'AWS4-HMAC-SHA256'
    canonical_uri = path
    canonical_querystring = ''
    
    # ターゲットを設定
    api_target = f"com.amazon.paapi5.v1.ProductAdvertisingAPIv1.{target}"
    
    # ヘッダーの準備
    headers = {
        'host': host,
        'x-amz-date': amz_date,
        'content-encoding': 'amz-1.0',
        'content-type': 'application/json; charset=utf-8',
        'x-amz-target': api_target
    }
    
    # カノニカルリクエストの作成
    canonical_headers = '\n'.join([f"{k}:{v}" for k, v in sorted(headers.items())]) + '\n'
    signed_headers = ';'.join(sorted(headers.keys()))
    
    # ペイロードのSHA256ハッシュ
    payload_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    
    # カノニカルリクエスト
    canonical_request = '\n'.join([
        'POST',
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        signed_headers,
        payload_hash
    ])
    
    # 署名の作成
    credential_scope = f"{datestamp}/{REGION}/{service}/aws4_request"
    string_to_sign = '\n'.join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
    ])
    
    # 署名キーの生成
    def sign(key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
    
    signing_key = sign(('AWS4' + PA_API_SECRET).encode('utf-8'), datestamp)
    signing_key = sign(signing_key, REGION)
    signing_key = sign(signing_key, service)
    signing_key = sign(signing_key, 'aws4_request')
    
    # 署名の計算
    signature = hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
    
    # 認証ヘッダーの生成
    auth_header = (
        f"{algorithm} "
        f"Credential={PA_API_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    
    # ヘッダーに認証情報を追加
    headers['Authorization'] = auth_header
    
    return headers

def search_by_category(category, keyword=None):
    """カテゴリで商品を検索（キーワードはオプション）"""
    if not PA_API_KEY or not PA_API_SECRET or not PARTNER_TAG:
        logger.error("環境変数が正しく設定されていません")
        return None
    
    host = "webservices.amazon.co.jp"
    path = "/paapi5/searchitems"
    url = f"https://{host}{path}"
    
    # リクエストペイロード
    payload = {
        "Resources": [
            "ItemInfo.Title",
            "ItemInfo.ByLineInfo",
            "Offers.Listings.Price",
            "Images.Primary.Small"
        ],
        "PartnerTag": PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": MARKETPLACE,
        "SearchIndex": category,
        "ItemCount": 10  # 検索結果の最大数
    }
    
    # キーワードが指定されている場合は追加
    if keyword:
        payload["Keywords"] = keyword
    else:
        # キーワードが指定されていない場合は、カテゴリ内の一般的な検索を行う
        # セール商品に絞るため「セール」または「特価」を追加
        payload["Keywords"] = "セール OR 特価"
    
    # Availabilityフィルタを追加（在庫あり商品のみ）
    payload["Availability"] = "Available"
    
    # ソート順を価格の安い順に
    payload["SortBy"] = "Price:LowToHigh"
    
    payload_json = json.dumps(payload)
    headers = sign_request(host, path, payload_json, "SearchItems")
    
    try:
        search_type = "カテゴリのみ" if not keyword else f"キーワード: {keyword}, カテゴリ: {category}"
        logger.info(f"商品検索中... {search_type}")
        response = requests.post(url, headers=headers, data=payload_json)
        
        if response.status_code != 200:
            logger.error(f"PA-API エラー: ステータスコード {response.status_code}")
            logger.error(f"エラー詳細: {response.text}")
            return None
        
        data = response.json()
        
        # エラーチェック
        if "Errors" in data:
            logger.error(f"PA-API エラー: {data['Errors']}")
            return None
        
        # 検索結果がない場合
        if "SearchResult" not in data or "Items" not in data["SearchResult"] or len(data["SearchResult"]["Items"]) == 0:
            logger.error(f"検索結果が見つかりませんでした: {category}")
            return None
        
        # 検索結果を返す
        return data["SearchResult"]["Items"]
        
    except Exception as e:
        logger.error(f"商品検索エラー: {e}")
        return None

def get_product_info(asin):
    """指定したASINの商品情報を詳細に取得"""
    host = "webservices.amazon.co.jp"
    path = "/paapi5/getitems"
    url = f"https://{host}{path}"
    
    # リクエストペイロード
    payload = {
        "ItemIds": [asin],
        "Resources": [
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "Offers.Listings.SavePrice",
            "Images.Primary.Medium"
        ],
        "PartnerTag": PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": MARKETPLACE
    }
    
    payload_json = json.dumps(payload)
    headers = sign_request(host, path, payload_json, "GetItems")
    
    try:
        logger.info(f"商品情報取得中... ASIN: {asin}")
        response = requests.post(url, headers=headers, data=payload_json)
        
        if response.status_code != 200:
            logger.error(f"PA-API エラー: ステータスコード {response.status_code}")
            logger.error(f"エラー詳細: {response.text}")
            return None
        
        data = response.json()
        
        if "Errors" in data:
            logger.error(f"PA-API エラー: {data['Errors']}")
            return None
        
        if "ItemsResult" not in data or "Items" not in data["ItemsResult"] or len(data["ItemsResult"]["Items"]) == 0:
            logger.error(f"商品情報が見つかりませんでした: {asin}")
            return None
        
        return data["ItemsResult"]["Items"][0]
        
    except Exception as e:
        logger.error(f"商品情報取得エラー: {e}")
        return None

def filter_discounted_items(items):
    """割引商品をフィルタリング"""
    discounted_items = []
    
    for item in items:
        asin = item.get("ASIN")
        
        # 詳細情報を取得
        product_info = get_product_info(asin)
        if not product_info:
            continue
        
        # タイトルを取得
        title = product_info.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", "不明")
        
        # 価格情報を取得
        current_price = None
        save_price = None
        
        if "Offers" in product_info and "Listings" in product_info["Offers"] and len(product_info["Offers"]["Listings"]) > 0:
            listing = product_info["Offers"]["Listings"][0]
            
            if "Price" in listing and "Amount" in listing["Price"]:
                current_price = float(listing["Price"]["Amount"])
            
            if "SavePrice" in listing and "Amount" in listing["SavePrice"]:
                save_price = float(listing["SavePrice"]["Amount"])
        
        # 価格情報がなければスキップ
        if current_price is None or save_price is None or save_price <= 0:
            continue
        
        # 元の価格と割引率を計算
        original_price = current_price + save_price
        discount_percent = (save_price / original_price) * 100
        
        # 最小割引率以上ならリストに追加
        if discount_percent >= MIN_DISCOUNT_PERCENT:
            # 商品情報を辞書に格納
            product_info = {
                "asin": asin,
                "title": title,
                "current_price": current_price,
                "original_price": original_price,
                "discount_amount": save_price,
                "discount_percent": discount_percent,
                "url": product_info.get("DetailPageURL", f"https://www.amazon.co.jp/dp/{asin}?tag={PARTNER_TAG}")
            }
            
            # 画像URLがあれば追加
            if "Images" in product_info and "Primary" in product_info["Images"] and "Medium" in product_info["Images"]["Primary"]:
                product_info["image_url"] = product_info["Images"]["Primary"]["Medium"]["URL"]
            
            discounted_items.append(product_info)
        
        # API制限を考慮して少し待機
        time.sleep(1)
    
    # 割引率の高い順にソート
    discounted_items.sort(key=lambda x: x["discount_percent"], reverse=True)
    
    return discounted_items

def setup_twitter_api():
    """Twitter APIの設定"""
    try:
        auth = tweepy.OAuthHandler(TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET)
        auth.set_access_token(TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET)
        api = tweepy.API(auth)
        logger.info("Twitter API認証成功")
        return api
    except Exception as e:
        logger.error(f"Twitter API認証エラー: {e}")
        return None

def post_to_twitter(api, product):
    """Xに商品情報を投稿"""
    if not api:
        logger.error("Twitter APIが初期化されていません")
        return False
    
    try:
        # 投稿文を作成
        discount_percent = product["discount_percent"]
        current_price = product["current_price"]
        original_price = product["original_price"]
        discount_amount = product["discount_amount"]
        
        post = f"🔥【{discount_percent:.1f}%オフ】Amazon割引情報🔥\n\n"
        post += f"{product['title']}\n\n"
        post += f"✅ 現在価格: {current_price:,.0f}円\n"
        post += f"❌ 元の価格: {original_price:,.0f}円\n"
        post += f"💰 割引額: {discount_amount:,.0f}円\n\n"
        post += f"🛒 商品ページ: {product['url']}\n\n"
        post += f"#Amazonセール #お買い得 #タイムセール"
        
        # 投稿が280文字を超える場合は調整
        if len(post) > 280:
            title_max = len(product['title']) - (len(post) - 270)
            short_title = product['title'][:title_max] + "..."
            post = post.replace(product['title'], short_title)
        
        # Xに投稿
        api.update_status(post)
        logger.info(f"Xに投稿しました: {product['title'][:30]}...")
        return True
        
    except Exception as e:
        logger.error(f"X投稿エラー: {e}")
        return False

def post_to_threads(product):
    """Threadsに投稿（Meta Graph API経由）"""
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        logger.error("Threads APIの認証情報が不足しています")
        return False
    
    try:
        # Meta Graph API エンドポイント
        url = f"https://graph.facebook.com/v17.0/{THREADS_USER_ID}/media"
        
        # 投稿文を作成
        discount_percent = product["discount_percent"]
        current_price = product["current_price"]
        original_price = product["original_price"]
        discount_amount = product["discount_amount"]
        
        caption = f"🔥【{discount_percent:.1f}%オフ】Amazon割引情報🔥\n\n"
        caption += f"{product['title']}\n\n"
        caption += f"✅ 現在価格: {current_price:,.0f}円\n"
        caption += f"❌ 元の価格: {original_price:,.0f}円\n"
        caption += f"💰 割引額: {discount_amount:,.0f}円\n\n"
        caption += f"🛒 商品ページ: {product['url']}\n\n"
        caption += f"#Amazonセール #お買い得 #タイムセール"
        
        # メディア投稿用パラメータ
        params = {
            "access_token": THREADS_ACCESS_TOKEN,
            "caption": caption
        }
        
        # 画像URLがある場合は追加
        if "image_url" in product:
            params["image_url"] = product["image_url"]
        
        # 投稿リクエスト
        response = requests.post(url, data=params)
        
        if response.status_code != 200:
            logger.error(f"Threads投稿エラー: {response.status_code}")
            logger.error(f"エラー詳細: {response.text}")
            return False
        
        logger.info(f"Threadsに投稿しました: {product['title'][:30]}...")
        return True
        
    except Exception as e:
        logger.error(f"Threads投稿エラー: {e}")
        return False

def load_search_config():
    """検索設定ファイルを読み込む"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info(f"{CONFIG_FILE}が見つかりません。デフォルト設定を使用します。")
        # デフォルト設定
        default_config = {
            "min_discount_percent": MIN_DISCOUNT_PERCENT,
            "search_items": [
                {"category": "Electronics"},
                {"category": "Kitchen"},
                {"category": "VideoGames"},
                {"category": "Apparel"},
                {"category": "Beauty"}
            ]
        }
        # 設定ファイルを保存
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config

def save_results(results):
    """検索結果を保存"""
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"検索結果を {RESULTS_FILE} に保存しました")

def load_previous_results():
    """前回の検索結果を読み込む（重複投稿防止用）"""
    try:
        with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='Amazon割引商品検索 & SNS投稿ツール')
    parser.add_argument('--dry-run', action='store_true', help='投稿せずに実行（テスト用）')
    parser.add_argument('--min-discount', type=float, help=f'最小割引率（デフォルト: {MIN_DISCOUNT_PERCENT}%）')
    args = parser.parse_args()
    
    # 設定を読み込む
    config = load_search_config()
    
    # 最小割引率を設定
    global MIN_DISCOUNT_PERCENT
    if args.min_discount:
        MIN_DISCOUNT_PERCENT = args.min_discount
    elif "min_discount_percent" in config:
        MIN_DISCOUNT_PERCENT = config["min_discount_percent"]
    
    logger.info(f"最小割引率: {MIN_DISCOUNT_PERCENT}%")
    
    # Twitter APIを初期化
    twitter_api = setup_twitter_api()
    
    # 前回の検索結果を読み込む（重複投稿防止）
    previous_results = load_previous_results()
    previous_asins = [item["asin"] for item in previous_results]
    
    # 新しい検索結果
    all_discounted_items = []
    
    # 各カテゴリで検索
    for search_item in config["search_items"]:
        category = search_item.get("category", "All")
        keyword = search_item.get("keyword")  # キーワードはオプション
        
        logger.info(f"検索開始: カテゴリ={category}" + (f", キーワード={keyword}" if keyword else ""))
        
        # 商品検索
        items = search_by_category(category, keyword)
        if not items:
            logger.warning(f"検索結果なし: カテゴリ={category}")
            continue
        
        # 割引商品をフィルタリング
        discounted_items = filter_discounted_items(items)
        
        # 重複を除外
        new_items = [item for item in discounted_items if item["asin"] not in previous_asins]
        
        if not new_items:
            logger.info(f"新しい割引商品はありませんでした: カテゴリ={category}")
            continue
        
        logger.info(f"割引商品発見: {len(new_items)}件 (カテゴリ={category})")
        all_discounted_items.extend(new_items)
    
    # 結果がなければ終了
    if not all_discounted_items:
        logger.info("新しい割引商品は見つかりませんでした")
        return
    
    # 割引率順にソート
    all_discounted_items.sort(key=lambda x: x["discount_percent"], reverse=True)
    
    # 結果を保存
    all_results = all_discounted_items + previous_results
    save_results(all_results[:100])  # 最新100件だけ保存
    
    # 結果表示
    logger.info(f"合計 {len(all_discounted_items)}件の新しい割引商品が見つかりました")
    
    # SNSに投稿（ドライランでなければ）
    if not args.dry_run:
        # 投稿する商品数を制限（API制限やスパム防止のため）
        post_limit = min(5, len(all_discounted_items))
        
        for i, product in enumerate(all_discounted_items[:post_limit]):
            logger.info(f"商品 {i+1}/{post_limit} を投稿: {product['title'][:30]}...")
            
            # Xに投稿
            if twitter_api:
                post_to_twitter(twitter_api, product)
            
            # Threadsに投稿
            if THREADS_ACCESS_TOKEN and THREADS_USER_ID:
                post_to_threads(product)
            
            # 連続投稿を避けるために待機
            time.sleep(5)
    else:
        logger.info("ドライラン: SNSへの投稿はスキップされました")

if __name__ == "__main__":
    main()
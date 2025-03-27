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
THREADS_APP_ID = os.getenv("THREADS_APP_ID")
THREADS_APP_SECRET = os.getenv("THREADS_APP_SECRET")
THREADS_LONG_LIVED_TOKEN = os.getenv("THREADS_LONG_LIVED_TOKEN")
THREADS_INSTAGRAM_ACCOUNT_ID = os.getenv("THREADS_INSTAGRAM_ACCOUNT_ID")

# 設定
CONFIG_FILE = "search_config.json"
RESULTS_FILE = "discount_results.json"
MIN_DISCOUNT_PERCENT = 20  # デフォルトの最小割引率
API_WAIT_TIME = 3  # APIリクエスト間の待機時間（秒）

# 日本のAmazonで使用可能なカテゴリマッピング（全カテゴリー対応）
VALID_CATEGORIES = {
    "All": "All",
    "Apparel": "Fashion",  # 修正：ApparelではなくFashion
    "Appliances": "Appliances",
    "Automotive": "Automotive",
    "Baby": "Baby",
    "Beauty": "Beauty",
    "Books": "Books",
    "Classical": "Classical",
    "Computers": "Computers",
    "CreditCards": "CreditCards",
    "DigitalMusic": "DigitalMusic",
    "Electronics": "Electronics",
    "EverythingElse": "EverythingElse",
    "Fashion": "Fashion",
    "FashionBaby": "FashionBaby",
    "FashionMen": "FashionMen",
    "FashionWomen": "FashionWomen",
    "ForeignBooks": "ForeignBooks",
    "GiftCards": "GiftCards",
    "GroceryAndGourmetFood": "GroceryAndGourmetFood",
    "HealthPersonalCare": "HealthPersonalCare",
    "Hobbies": "Hobbies",
    "HomeAndKitchen": "HomeAndKitchen",
    "Industrial": "Industrial",
    "Jewelry": "Jewelry",
    "KindleStore": "KindleStore",
    "Kitchen": "HomeAndKitchen",  # 修正：KitchenではなくHomeAndKitchen
    "MobileApps": "MobileApps",
    "MoviesAndTV": "MoviesAndTV",
    "Music": "Music",
    "MusicalInstruments": "MusicalInstruments",
    "OfficeProducts": "OfficeProducts",
    "PetSupplies": "PetSupplies",
    "Shoes": "Shoes",
    "Software": "Software",
    "SportsAndOutdoors": "SportsAndOutdoors",
    "ToolsAndHomeImprovement": "ToolsAndHomeImprovement",
    "Toys": "Toys",
    "VideoGames": "VideoGames",
    "Watches": "Watches"
}

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

def search_items(keyword, category="All"):
    """キーワードで商品を検索"""
    if not PA_API_KEY or not PA_API_SECRET or not PARTNER_TAG:
        logger.error("環境変数が正しく設定されていません")
        return None
    
    # カテゴリ名のマッピングを使用
    mapped_category = VALID_CATEGORIES.get(category, "All")
    
    host = "webservices.amazon.co.jp"
    path = "/paapi5/searchitems"
    url = f"https://{host}{path}"
    
    # リクエストペイロード - SearchItems APIで有効なリソースのみを指定
    payload = {
        "Keywords": keyword,
        "Resources": [
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "Images.Primary.Small"
        ],
        "PartnerTag": PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": MARKETPLACE,
        "SearchIndex": mapped_category,
        "ItemCount": 10  # 検索結果の最大数
    }
    
    payload_json = json.dumps(payload)
    headers = sign_request(host, path, payload_json, "SearchItems")
    
    try:
        logger.info(f"商品検索中... キーワード: {keyword}, カテゴリ: {mapped_category}")
        response = requests.post(url, headers=headers, data=payload_json)
        
        # デバッグ用にリクエスト内容を表示
        logger.debug(f"リクエストURL: {url}")
        logger.debug(f"リクエストペイロード: {payload_json}")
        
        logger.info(f"レスポンスステータス: {response.status_code}")
        if response.status_code == 429:
            logger.warning("API制限に達しました。しばらく待ってから再試行します。")
            time.sleep(API_WAIT_TIME * 2)  # 制限に達した場合は長めに待機
            return None
        
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
            logger.warning(f"検索結果が見つかりませんでした: {keyword}")
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
    
    # リクエストペイロード - GetItems APIで有効なリソースのみを指定
    payload = {
        "ItemIds": [asin],
        "Resources": [
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "Offers.Listings.SavingBasis",  # 修正: SavePriceではなくSavingBasis
            "Images.Primary.Large"  # 修正: MediumではなくLarge
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
        
        if response.status_code == 429:
            logger.warning("API制限に達しました。しばらく待ってから再試行します。")
            time.sleep(API_WAIT_TIME * 2)  # 制限に達した場合は長めに待機
            return None
            
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
    finally:
        # API制限を避けるために待機
        time.sleep(API_WAIT_TIME)

def filter_discounted_items(items, min_discount_percent=MIN_DISCOUNT_PERCENT):
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
        original_price = None
        
        if "Offers" in product_info and "Listings" in product_info["Offers"] and len(product_info["Offers"]["Listings"]) > 0:
            listing = product_info["Offers"]["Listings"][0]
            
            if "Price" in listing and "Amount" in listing["Price"]:
                current_price = float(listing["Price"]["Amount"])
            
            if "SavingBasis" in listing and "Amount" in listing["SavingBasis"]:
                original_price = float(listing["SavingBasis"]["Amount"])
        
        # 価格情報がなければスキップ
        if current_price is None or original_price is None or original_price <= current_price:
            continue
        
        # 割引額と割引率を計算
        discount_amount = original_price - current_price
        discount_percent = (discount_amount / original_price) * 100
        
        # 最小割引率以上ならリストに追加
        if discount_percent >= min_discount_percent:
            # 商品情報を辞書に格納
            product_info = {
                "asin": asin,
                "title": title,
                "current_price": current_price,
                "original_price": original_price,
                "discount_amount": discount_amount,
                "discount_percent": discount_percent,
                "url": product_info.get("DetailPageURL", f"https://www.amazon.co.jp/dp/{asin}?tag={PARTNER_TAG}")
            }
            
            # 画像URLがあれば追加
            if "Images" in product_info and "Primary" in product_info["Images"] and "Large" in product_info["Images"]["Primary"]:
                product_info["image_url"] = product_info["Images"]["Primary"]["Large"]["URL"]
            
            discounted_items.append(product_info)
    
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
        
        post = f"🔥【{discount_percent:.1f}%オフ】Amazon割引情報🔥#PR\n\n"
        post += f"{product['title']}\n\n"
        post += f"✅ 現在価格: {current_price:,.0f}円\n"
        post += f"❌ 元の価格: {original_price:,.0f}円\n"
        post += f"💰 割引額: {discount_amount:,.0f}円\n\n"
        post += f"🛒 商品ページ: {product['url']}\n\n"
        
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

def get_threads_access_token():
    """Threads APIのアクセストークンを取得"""
    try:
        # 長期アクセストークンが既に存在する場合はそれを使用
        if THREADS_LONG_LIVED_TOKEN:
            logger.info("Threads認証: 長期アクセストークンを使用します")
            return THREADS_LONG_LIVED_TOKEN
        
        # クライアント認証情報が不足している場合はエラー
        if not THREADS_APP_ID or not THREADS_APP_SECRET:
            raise ValueError("Threads API認証情報が不足しています")
        
        # アクセストークンリクエストURL
        token_url = "https://graph.facebook.com/v18.0/oauth/access_token"
        
        # リクエストパラメータ
        params = {
            "client_id": THREADS_APP_ID,
            "client_secret": THREADS_APP_SECRET,
            "grant_type": "client_credentials"
        }
        
        # POSTリクエストを送信
        logger.info("Threads認証: アクセストークンをリクエスト中...")
        response = requests.get(token_url, params=params)
        
        # レスポンスを確認
        if response.status_code == 200:
            response_data = response.json()
            access_token = response_data.get("access_token")
            logger.info("Threads認証: クライアントアクセストークンを取得しました")
            return access_token
        else:
            error_msg = f"アクセストークン取得エラー: ステータスコード {response.status_code}, レスポンス: {response.text}"
            logger.error(f"Threads認証: {error_msg}")
            raise ValueError(error_msg)
            
    except Exception as e:
        logger.error(f"Threads認証エラー: {e}")
        return None

def post_to_threads(product):
    """Threadsに投稿（Meta Graph API経由）"""
    try:
        # Threadsの認証情報確認
        if not THREADS_INSTAGRAM_ACCOUNT_ID:
            logger.error("Threads投稿: Instagram アカウントID が設定されていません")
            return False
        
        # アクセストークン取得
        access_token = get_threads_access_token()
        if not access_token:
            logger.error("Threads投稿: アクセストークンが取得できません")
            return False
        
        logger.info("Threads投稿: ステップ1 - コンテナID作成中...")
        
        # 投稿文を作成
        discount_percent = product["discount_percent"]
        current_price = product["current_price"]
        original_price = product["original_price"]
        discount_amount = product["discount_amount"]
        
        text = f"🔥【{discount_percent:.1f}%オフ】Amazon割引情報🔥\n\n"
        text += f"{product['title']}\n\n"
        text += f"✅ 現在価格: {current_price:,.0f}円\n"
        text += f"❌ 元の価格: {original_price:,.0f}円\n"
        text += f"💰 割引額: {discount_amount:,.0f}円\n\n"
        text += f"🛒 商品ページ: {product['url']}\n\n"
        text += f"#Amazonセール #お買い得 #タイムセール #PR"
        
        # ステップ1: コンテナID作成
        upload_url = f"https://graph.threads.net/v1.0/{THREADS_INSTAGRAM_ACCOUNT_ID}/threads"
        upload_params = {
            "access_token": access_token,
            "media_type": "TEXT",
            "text": text
        }
        
        # 画像URLがある場合は追加
        if "image_url" in product:
            upload_params["media_type"] = "IMAGE"
            upload_params["image_url"] = product["image_url"]
        
        # リクエスト送信
        upload_response = requests.post(upload_url, data=upload_params)
        
        if upload_response.status_code != 200:
            error_msg = f"コンテナ作成エラー: ステータスコード {upload_response.status_code}, レスポンス: {upload_response.text}"
            logger.error(f"Threads投稿: {error_msg}")
            return False
        
        # コンテナIDの取得
        try:
            creation_data = upload_response.json()
            container_id = creation_data.get("id")
            if not container_id:
                logger.error("Threads投稿: コンテナIDが取得できませんでした")
                return False
        except Exception as e:
            logger.error(f"Threads投稿: コンテナIDの解析に失敗 - {e}")
            return False
        
        logger.info(f"Threads投稿: コンテナID取得成功: {container_id}")
        
        # ステップ2: 投稿の公開
        logger.info("Threads投稿: ステップ2 - 投稿公開中...")
        publish_url = f"https://graph.threads.net/v1.0/{THREADS_INSTAGRAM_ACCOUNT_ID}/threads_publish"
        publish_params = {
            "access_token": access_token,
            "creation_id": container_id
        }
        
        # リクエスト送信
        publish_response = requests.post(publish_url, data=publish_params)
        
        if publish_response.status_code != 200:
            error_msg = f"公開エラー: ステータスコード {publish_response.status_code}, レスポンス: {publish_response.text}"
            logger.error(f"Threads投稿: {error_msg}")
            return False
        
        # 公開成功
        logger.info(f"Threadsに投稿しました: {product['title'][:30]}...")
        return True
        
    except Exception as e:
        logger.error(f"Threads投稿エラー: {e}")
        return False

def load_search_config():
    """検索設定ファイルを読み込む"""
    # デフォルト設定
    default_config = {
        "min_discount_percent": MIN_DISCOUNT_PERCENT,
        "search_items": [
            {"category": "Electronics", "keyword": "セール"},
            {"category": "HomeAndKitchen", "keyword": "セール"},
            {"category": "VideoGames", "keyword": "セール"},
            {"category": "Beauty", "keyword": "セール"},
            {"category": "Fashion", "keyword": "セール"}
        ]
    }
    
    try:
        # ファイルが存在し、正しいJSON形式であれば読み込む
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:  # 空ファイルの場合
                raise json.JSONDecodeError("Empty file", "", 0)
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # ファイルが存在しないか、不正なJSON形式の場合
        error_type = "見つかりません" if isinstance(e, FileNotFoundError) else "不正な形式です"
        logger.warning(f"{CONFIG_FILE}が{error_type}。デフォルト設定を使用します。")
        
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
            content = f.read().strip()
            if not content:  # 空ファイルの場合
                return []
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
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
    min_discount = MIN_DISCOUNT_PERCENT
    if args.min_discount:
        min_discount = args.min_discount
    elif "min_discount_percent" in config:
        min_discount = config["min_discount_percent"]
    
    logger.info(f"最小割引率: {min_discount}%")
    
    twitter_api = setup_twitter_api()
    
    # 前回の検索結果を読み込む（重複投稿防止）
    previous_results = load_previous_results()
    previous_asins = [item["asin"] for item in previous_results] if previous_results else []
    
    # 新しい検索結果
    all_discounted_items = []
    
    # 各カテゴリで検索
    for search_item in config.get("search_items", []):
        category = search_item.get("category", "All")
        keyword = search_item.get("keyword", "セール")  # デフォルトキーワード
        
        # カテゴリマッピングを使用
        if category in VALID_CATEGORIES:
            mapped_category = VALID_CATEGORIES[category]
        else:
            logger.warning(f"無効なカテゴリ: {category}、Allを使用します")
            mapped_category = "All"
        
        logger.info(f"検索開始: カテゴリ={mapped_category}, キーワード={keyword}")
        
        # 商品検索
        items = search_items(keyword, mapped_category)
        if not items:
            logger.warning(f"検索結果なし: カテゴリ={mapped_category}, キーワード={keyword}")
            continue
        
        # 割引商品をフィルタリング
        discounted_items = filter_discounted_items(items, min_discount)
        
        # 重複を除外
        new_items = [item for item in discounted_items if item["asin"] not in previous_asins]
        
        if not new_items:
            logger.info(f"新しい割引商品はありませんでした: カテゴリ={mapped_category}")
            continue
        
        logger.info(f"割引商品発見: {len(new_items)}件 (カテゴリ={mapped_category})")
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
                post_result = post_to_twitter(twitter_api, product)
                logger.info(f"Twitter投稿結果: {'成功' if post_result else '失敗'}")
            else:
                logger.info("Twitter APIの制限により投稿をスキップします")
            
            # Threadsに投稿
            threads_credentials = THREADS_INSTAGRAM_ACCOUNT_ID and (THREADS_LONG_LIVED_TOKEN or (THREADS_APP_ID and THREADS_APP_SECRET))
            if threads_credentials:
                threads_result = post_to_threads(product)
                logger.info(f"Threads投稿結果: {'成功' if threads_result else '失敗'}")
            
            # 連続投稿を避けるために待機
            time.sleep(5)
    else:
        logger.info("ドライラン: SNSへの投稿はスキップされました")
        
        # ドライラン時は商品情報を表示
        print("\n" + "="*70)
        print(f"【割引商品検索結果: {len(all_discounted_items)}件】")
        print("="*70)
        
        for i, product in enumerate(all_discounted_items[:10], 1):  # 最大10件表示
            print(f"\n{i}. {product['title']}")
            print(f"   ASIN: {product['asin']}")
            print(f"   現在価格: {product['current_price']:,.0f}円")
            print(f"   元の価格: {product['original_price']:,.0f}円")
            print(f"   割引額: {product['discount_amount']:,.0f}円 ({product['discount_percent']:.1f}%オフ)")
            print(f"   URL: {product['url']}")
            
            if "image_url" in product:
                print(f"   画像: {product['image_url']}")
        
        print("\n" + "="*70)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("ユーザーによる中断を検出しました。プログラムを終了します。")
    except Exception as e:
        logger.error(f"予期しないエラーが発生しました: {e}", exc_info=True)
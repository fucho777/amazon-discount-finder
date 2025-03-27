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
MIN_DISCOUNT_PERCENT = 15  # デフォルトの最小割引率
MAX_DISCOUNT_PERCENT = 80  # 最大許容割引率（偽の割引を除外）
API_WAIT_TIME = 3  # APIリクエスト間の待機時間（秒）

# 日本のAmazonで使用可能なカテゴリマッピング（全カテゴリー対応）
VALID_CATEGORIES = {
    "All": "All",
    "Apparel": "Fashion",
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
    "Kitchen": "HomeAndKitchen",
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
            "ItemInfo.ByLineInfo",
            "Offers.Listings.Price",
            "Offers.Listings.MerchantInfo",
            "Images.Primary.Small"
        ],
        "PartnerTag": PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": MARKETPLACE,
        "SearchIndex": mapped_category,
        "ItemCount": 10,  # 検索結果の最大数
        "Merchant": "Amazon"  # Amazon直販の商品のみに限定
    }
    
    payload_json = json.dumps(payload)
    headers = sign_request(host, path, payload_json, "SearchItems")
    
    try:
        logger.info(f"商品検索中... キーワード: {keyword}, カテゴリ: {mapped_category}, 出品者: Amazon")
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
            "ItemInfo.ByLineInfo",
            "Offers.Listings.Price",
            "Offers.Listings.SavingBasis",
            "Offers.Listings.MerchantInfo",
            "Images.Primary.Large"
        ],
        "PartnerTag": PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": MARKETPLACE,
        "Merchant": "Amazon"  # Amazon直販の商品のみに限定
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

def is_amazon_merchant(product_info):
    """商品がAmazon直販かチェック"""
    try:
        if "Offers" in product_info and "Listings" in product_info["Offers"] and len(product_info["Offers"]["Listings"]) > 0:
            listing = product_info["Offers"]["Listings"][0]
            
            if "MerchantInfo" in listing and "Name" in listing["MerchantInfo"]:
                merchant_name = listing["MerchantInfo"]["Name"]
                return merchant_name.lower() == "amazon" or "amazon.co.jp" in merchant_name.lower()
        
        return False
    except Exception as e:
        logger.error(f"出品者チェックエラー: {e}")
        return False

def is_reasonable_discount(current_price, original_price):
    """割引率が合理的かどうかをチェック"""
    if original_price <= current_price:
        return False
    
    discount_percent = ((original_price - current_price) / original_price) * 100
    
    # 割引率が異常に高い場合はフラグを立てる（例: 80%以上）
    if discount_percent >= MAX_DISCOUNT_PERCENT:
        logger.warning(f"不合理な割引率を検出: {discount_percent:.1f}% (元価格: {original_price:,.0f}円, 現在価格: {current_price:,.0f}円)")
        return False
    
    # 極端に元価格が高い場合は不審
    if original_price > current_price * 3:  # 元価格が現在価格の3倍以上
        logger.warning(f"不審な元価格を検出: 元価格が現在価格の{original_price/current_price:.1f}倍 (元価格: {original_price:,.0f}円, 現在価格: {current_price:,.0f}円)")
        return False
    
    return True

def filter_discounted_items(items, min_discount_percent=MIN_DISCOUNT_PERCENT):
    """割引商品をフィルタリング"""
    discounted_items = []
    
    for item in items:
        asin = item.get("ASIN")
        
        # 詳細情報を取得
        product_info = get_product_info(asin)
        if not product_info:
            continue
        
        # Amazon直販チェック
        if not is_amazon_merchant(product_info):
            logger.info(f"Amazon直販ではないためスキップ: {asin}")
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
        
        # 割引率チェック - 最小割引率以上かつ合理的な割引率
        if discount_percent >= min_discount_percent and is_reasonable_discount(current_price, original_price):
            # 商品情報を辞書に格納
            product_data = {
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
                product_data["image_url"] = product_info["Images"]["Primary"]["Large"]["URL"]
            
            discounted_items.append(product_data)
    
    # 割引率の高い順にソート
    discounted_items.sort(key=lambda x: x["discount_percent"], reverse=True)
    
    return discounted_items

def setup_twitter_api():
    """Twitter APIの設定"""
    try:
        # API認証情報のチェック
        if not all([TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
            logger.warning("Twitter認証情報が不足しています。Twitter投稿はスキップされます。")
            return None
            
        # v2 API用の設定
        client = tweepy.Client(
            consumer_key=TWITTER_CONSUMER_KEY,
            consumer_secret=TWITTER_CONSUMER_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_TOKEN_SECRET
        )
        
        # 認証テスト - v2 APIのユーザー情報取得で検証
        me = client.get_me()
        if me.data:
            logger.info(f"Twitter API v2認証成功: @{me.data.username}")
            return client
        else:
            logger.error("Twitter認証に失敗しました")
            return None
    except Exception as e:
        logger.error(f"Twitter API認証エラー: {e}")
        return None

def post_to_twitter(client, product):
    """Xに商品情報を投稿"""
    if not client:
        logger.error("Twitter APIクライアントが初期化されていません")
        return False
    
    try:
        # 投稿文を作成
        discount_percent = product["discount_percent"]
        current_price = product["current_price"]
        original_price = product["original_price"]
        discount_amount = product["discount_amount"]
        
        post = f"🔥【{discount_percent:.1f}%オフ】Amazon直販商品割引情報🔥#PR\n\n"
        post += f"{product['title'][:80]}...\n\n"
        post += f"✅ 現在価格: {current_price:,.0f}円\n"
        post += f"❌ 元の価格: {original_price:,.0f}円\n"
        post += f"💰 割引額: {discount_amount:,.0f}円\n\n"
        post += f"🛒 商品ページ: {product['url']}\n\n"
        
        # 投稿が280文字を超える場合は調整
        if len(post) > 280:
            title_max = 50  # タイトルを固定で50文字に制限
            short_title = product['title'][:title_max] + "..."
            post = post.replace(f"{product['title'][:80]}...", short_title)
        
        # v2 APIでツイート
        response = client.create_tweet(text=post)
        if response.data and 'id' in response.data:
            tweet_id = response.data['id']
            logger.info(f"Xに投稿しました: ID={tweet_id} {product['title'][:30]}...")
            return True
        else:
            logger.error("X投稿に失敗: レスポンスにツイートIDがありません")
            return False
            
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
        
        text = f"🔥【{discount_percent:.1f}%オフ】Amazon直販商品割引情報🔥\n\n"
        text += f"{product['title'][:80]}...\n\n"
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
    # デフォルト設定 - より有効なキーワードを使用
    default_config = {
        "min_discount_percent": MIN_DISCOUNT_PERCENT,
        "max_discount_percent": MAX_DISCOUNT_PERCENT,
        "search_items": [
            {"category": "Electronics", "keyword": "セール"},
            {"category": "HomeAndKitchen", "keyword": "タイムセール"},
            {"category": "VideoGames", "keyword": "割引"},
            {"category": "Beauty", "keyword": "お買い得"},
            {"category": "Fashion", "keyword": "特価"},
            {"category": "Books", "keyword": "クーポン"},
            {"category": "HealthPersonalCare", "keyword": "限定価格"},
            {"category": "Toys", "keyword": "SALE"}
        ]
    }
    
    try:
        # ファイルが存在し、正しいJSON形式であれば読み込む
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:  # 空ファイルの場合
                raise json.JSONDecodeError("Empty file", "", 0)
            config = json.loads(content)
            
            # 最大割引率設定がなければ追加
            if "max_discount_percent" not in config:
                config["max_discount_percent"] = MAX_DISCOUNT_PERCENT
                logger.info(f"設定に最大割引率を追加: {MAX_DISCOUNT_PERCENT}%")
            
            # 設定ファイルから読み込んだ後、無効なカテゴリをフィルタリング
            if "search_items" in config:
                filtered_items = []
                for item in config["search_items"]:
                    category = item.get("category", "All")
                    keyword = item.get("keyword", "セール")
                    
                    # 無効なキーワードをチェック（単なる記号は除外）
                    if keyword in ["¥", "$", "円"]:
                        logger.warning(f"無効なキーワードを検出: '{keyword}' を 'セール' に変更します")
                        keyword = "セール"
                        item["keyword"] = keyword
                    
                    # カテゴリが有効かチェック
                    if category in VALID_CATEGORIES:
                        # カテゴリが有効ならそのまま追加
                filtered_items.append(item)
                    else:
                        logger.warning(f"無効なカテゴリをスキップ: {category}")
                        # 有効なカテゴリで置き換える
                        item["category"] = "All"
                        filtered_items.append(item)

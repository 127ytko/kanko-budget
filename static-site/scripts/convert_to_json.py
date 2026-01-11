"""
CSVデータをJSON形式に変換するスクリプト
静的サイトのビルド前に実行
"""

import csv
import json
import os
import hashlib
from datetime import datetime

# パス設定
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

# 入力ファイル（プロジェクトルート）
TARGETS_CSV = os.path.join(BASE_DIR, '..', 'target_urls.csv')
TAGS_CSV = os.path.join(BASE_DIR, '..', 'tags.csv')
ITEMS_CSV = os.path.join(BASE_DIR, '..', 'multi_municipality_budget_analysis.csv')
LAST_UPDATED_FILE = os.path.join(BASE_DIR, '..', 'last_updated.txt')

# 関西6府県
PREFECTURES = ["滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"]

# 府県と市町村のマッピング
PREFECTURE_MAPPING = {
    "滋賀県": ["滋賀県", "大津市", "彦根市", "長浜市", "近江八幡市", "草津市", "守山市", "栗東市", "甲賀市", "野洲市", "湖南市", "高島市", "東近江市", "米原市"],
    "京都府": ["京都府", "京都市", "京都市観光協会", "福知山市", "舞鶴市", "綾部市", "宇治市", "宮津市", "亀岡市", "城陽市", "向日市", "長岡京市", "八幡市", "京田辺市", "京丹後市", "南丹市", "木津川市"],
    "大阪府": ["大阪府", "大阪市", "堺市", "岸和田市", "豊中市", "池田市", "吹田市", "泉大津市", "高槻市", "貝塚市", "守口市", "枚方市", "茨木市", "八尾市", "泉佐野市", "富田林市", "寝屋川市", "河内長野市", "松原市", "大東市", "和泉市", "箕面市", "柏原市", "羽曳野市", "門真市", "摂津市", "高石市", "藤井寺市", "東大阪市", "泉南市", "四條畷市", "交野市", "大阪狭山市", "阪南市"],
    "兵庫県": ["兵庫県", "神戸市", "姫路市", "尼崎市", "明石市", "西宮市", "洲本市", "芦屋市", "伊丹市", "相生市", "豊岡市", "加古川市", "赤穂市", "西脇市", "宝塚市", "三木市", "高砂市", "川西市", "小野市", "三田市", "加西市", "丹波篠山市", "養父市", "丹波市", "南あわじ市", "朝来市", "淡路市", "宍粟市", "加東市", "たつの市"],
    "奈良県": ["奈良県", "奈良市", "大和高田市", "大和郡山市", "天理市", "橿原市", "桜井市", "五條市", "御所市", "生駒市", "香芝市", "葛城市", "宇陀市"],
    "和歌山県": ["和歌山県", "和歌山市", "海南市", "橋本市", "有田市", "御坊市", "田辺市", "新宮市", "紀の川市", "岩出市"]
}

def get_prefecture_for_municipality(municipality):
    """市町村名から所属県を取得"""
    for pref, cities in PREFECTURE_MAPPING.items():
        if municipality in cities:
            return pref
    return None

def load_tags():
    """タグ一覧を読み込み"""
    tags = []
    if os.path.exists(TAGS_CSV):
        with open(TAGS_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('Tag'):
                    tags.append(row['Tag'])
    return tags

def extract_tags(text, tag_list):
    """テキストからタグを抽出"""
    found_tags = []
    if text:
        for tag in tag_list:
            if tag in text:
                found_tags.append(tag)
    return found_tags

def convert_targets():
    """target_urls.csv → targets.json"""
    targets = []
    if os.path.exists(TARGETS_CSV):
        with open(TARGETS_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('Target_URL'):
                    targets.append({
                        'id': row.get('ID', ''),
                        'municipality': row.get('Municipality', ''),
                        'url': row.get('Target_URL', ''),
                        'pageTitle': row.get('Page_Title', '')
                    })
    
    output_path = os.path.join(DATA_DIR, 'targets.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(targets, f, ensure_ascii=False, indent=2)
    print(f"✅ targets.json 作成: {len(targets)}件")

def convert_tags():
    """tags.csv → tags.json"""
    tags = []
    if os.path.exists(TAGS_CSV):
        with open(TAGS_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('Tag'):
                    tags.append({
                        'id': row.get('ID', ''),
                        'tag': row.get('Tag', ''),
                        'color': row.get('Color', '#8B5CF6')
                    })
    
    output_path = os.path.join(DATA_DIR, 'tags.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(tags, f, ensure_ascii=False, indent=2)
    print(f"✅ tags.json 作成: {len(tags)}件")

def convert_items():
    """multi_municipality_budget_analysis.csv → items.json"""
    items = []
    tag_list = load_tags()
    
    # 県ごとの市町村リスト
    prefecture_municipalities = {pref: set() for pref in PREFECTURES}
    
    if os.path.exists(ITEMS_CSV):
        with open(ITEMS_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            # 日付で降順ソート
            rows.sort(key=lambda x: x.get('Detected_Date', ''), reverse=True)
            
            for i, row in enumerate(rows, 1):
                municipality = row.get('Municipality', '')
                prefecture = get_prefecture_for_municipality(municipality)
                excerpt = row.get('Excerpt_Summary', '')
                tags = extract_tags(excerpt, tag_list)
                
                # 県ごとの市町村リストに追加
                if prefecture and prefecture in prefecture_municipalities:
                    prefecture_municipalities[prefecture].add(municipality)
                
                items.append({
                    'id': hashlib.md5(row.get('Page_URL', '').encode()).hexdigest()[:8],
                    'date': row.get('Detected_Date', ''),
                    'municipality': municipality,
                    'prefecture': prefecture or '',
                    'title': row.get('Title', ''),
                    'url': row.get('Page_URL', row.get('PDF_URL', '')),  # 新旧両方に対応
                    'tags': tags,
                    'hasTourismKeyword': row.get('Has_Tourism_Keyword', '') == 'TRUE',
                    'excerpt': excerpt
                })
    
    # 最終更新日時を取得
    last_updated = None
    if os.path.exists(LAST_UPDATED_FILE):
        try:
            with open(LAST_UPDATED_FILE, 'r', encoding='utf-8') as f:
                last_updated = f.read().strip()
        except UnicodeDecodeError:
            with open(LAST_UPDATED_FILE, 'r', encoding='utf-16') as f:
                last_updated = f.read().strip()
    
    # 県→市町村マッピングをリストに変換
    pref_muni_list = {k: sorted(list(v)) for k, v in prefecture_municipalities.items()}
    
    output = {
        'lastUpdated': last_updated,
        'prefectures': PREFECTURES,
        'prefectureMunicipalities': pref_muni_list,
        'items': items
    }
    
    output_path = os.path.join(DATA_DIR, 'items.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ items.json 作成: {len(items)}件")

def main():
    print("=" * 50)
    print("CSVデータをJSONに変換中...")
    print("=" * 50)
    
    # dataディレクトリがなければ作成
    os.makedirs(DATA_DIR, exist_ok=True)
    
    convert_targets()
    convert_tags()
    convert_items()
    
    print("=" * 50)
    print("変換完了！")
    print("=" * 50)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自治体予算情報スクレイピング・分析スクリプト（ページベース版）

このスクリプトは登録された自治体のWebサイトから予算関連のページを取得し、
そのページ内のPDFを分析して観光・物価高騰対策に関連するキーワードを検出します。

【重要な変更点】
- PDFではなく、HTMLページ（記事ページ）のURLとタイトルを収集
- ページ内のPDFを分析してキーワード検出
- 表示されるのはページタイトルとページURL

設定ファイル:
- target_urls.csv: スクレイピング対象の自治体URL
- tags.csv: 検索キーワード
"""

import requests
import time
import csv
import re
import io
import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
import hashlib
from bs4 import BeautifulSoup

# pdfminer.sixを使用
from pdfminer.high_level import extract_text
from pdfminer.pdfparser import PDFSyntaxError

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

# ============================================
# 設定ファイルのパス（静的サイト用：親ディレクトリを参照）
# ============================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # kanko-budget/

TARGET_URLS_CSV = os.path.join(ROOT_DIR, 'target_urls.csv')  # 自治体URL設定ファイル
TAGS_CSV = os.path.join(ROOT_DIR, 'tags.csv')  # キーワード設定ファイル
HISTORY_FILE = os.path.join(ROOT_DIR, 'processed_history.csv')  # 処理済みURL履歴ファイル
OUTPUT_FILE = os.path.join(ROOT_DIR, 'multi_municipality_budget_analysis.csv')  # 分析結果出力ファイル
LAST_UPDATED_FILE = os.path.join(ROOT_DIR, 'last_updated.txt')  # 最終更新日時ファイル

# 定数設定（2025年以降のみ対象）
TARGET_YEARS = ['令和7年度', '令和8年度', '令和9年度', 'R7', 'R8', 'R9', '2025', '2026', '2027']
MIN_YEAR = 2025  # これ以前の年度はスキップ
BUDGET_KEYWORDS = ['予算', '補正', '当初', '概要', '方針', '要領', '決算']

# リクエストヘッダー
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
}


# ============================================
# 設定ファイル読み込み関数
# ============================================

def load_municipalities_from_csv() -> list:
    """
    target_urls.csv から自治体情報を読み込む
    """
    municipalities = []
    
    if not os.path.exists(TARGET_URLS_CSV):
        logger.warning(f"設定ファイルが見つかりません: {TARGET_URLS_CSV}")
        return municipalities
    
    try:
        with open(TARGET_URLS_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get('Target_URL'):
                    continue
                
                url = row['Target_URL']
                parsed = urlparse(url)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                
                municipalities.append({
                    'id': row.get('ID', ''),
                    'name': row.get('Municipality', '不明'),
                    'base_url': base_url,
                    'start_urls': [url],
                })
        
        logger.info(f"📋 自治体設定読み込み完了: {len(municipalities)}件")
    except Exception as e:
        logger.error(f"自治体設定読み込みエラー: {e}")
    
    return municipalities


def load_keywords_from_csv() -> list:
    """
    tags.csv からキーワードを読み込む
    """
    keywords = []
    
    if not os.path.exists(TAGS_CSV):
        logger.warning(f"キーワード設定ファイルが見つかりません: {TAGS_CSV}")
        return ["観光", "インバウンド", "誘客", "クーポン", "物価高騰"]
    
    try:
        with open(TAGS_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tag = row.get('Tag', '').strip()
                if tag:
                    keywords.append(tag)
        
        logger.info(f"📋 キーワード設定読み込み完了: {len(keywords)}件")
    except Exception as e:
        logger.error(f"キーワード設定読み込みエラー: {e}")
    
    return keywords


# キーワードリストを動的に読み込み
TOURISM_KEYWORDS = load_keywords_from_csv()
INFLATION_KEYWORDS = ["物価高騰", "重点支援地方創生臨時交付金", "給付金"]
ALL_KEYWORDS = TOURISM_KEYWORDS + INFLATION_KEYWORDS


# ============================================
# 履歴管理機能（ハッシュ比較による更新検知）
# ============================================

# 日本時間（JST）
JST = timezone(timedelta(hours=9))

def get_jst_now() -> datetime:
    """現在の日本時間を取得"""
    return datetime.now(JST)


def calculate_page_hash(page_info: dict) -> str:
    """
    ページ内容のハッシュを計算する
    タイトル、PDF数、PDFリストを元に変更を検知
    """
    content = f"{page_info.get('title', '')}"
    content += f"_{len(page_info.get('pdfs', []))}"
    for pdf in page_info.get('pdfs', []):
        content += f"_{pdf.get('url', '')}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def load_history() -> dict:
    """
    処理済みURLの履歴を読み込む（ハッシュ比較版）
    戻り値: {URL: {'hash': ハッシュ値, 'date': 検出日}}
    """
    history = {}
    
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('URL'):
                        history[row['URL']] = {
                            'hash': row.get('Hash', ''),
                            'date': row.get('Detected_Date', '')
                        }
            logger.info(f"📋 履歴ファイル読み込み完了: {len(history)}件の処理済みURL")
        except Exception as e:
            logger.warning(f"履歴ファイル読み込みエラー: {e}")
    else:
        logger.info("📋 履歴ファイルが存在しません。新規作成します。")
    
    return history


def save_history(history: dict):
    """
    履歴ファイルを上書き保存する
    """
    try:
        with open(HISTORY_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=['URL', 'Hash', 'Detected_Date'])
            writer.writeheader()
            for url, data in history.items():
                writer.writerow({
                    'URL': url,
                    'Hash': data.get('hash', ''),
                    'Detected_Date': data.get('date', '')
                })
        logger.info(f"📋 履歴ファイル保存完了: {len(history)}件")
    except Exception as e:
        logger.error(f"履歴ファイル保存エラー: {e}")


def append_to_output_csv(result: dict):
    """分析結果を出力CSVに追記する"""
    columns = ['Detected_Date', 'Municipality', 'Title', 'Page_URL', 
               'Has_Tourism_Keyword', 'Has_Inflation_Keyword', 'Excerpt_Summary']
    
    file_exists = os.path.exists(OUTPUT_FILE)
    
    try:
        with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            if not file_exists:
                writer.writeheader()
            writer.writerow(result)
    except Exception as e:
        logger.error(f"結果CSV追記エラー: {e}")


# ============================================
# PDF分析関連
# ============================================

def download_pdf(url: str) -> bytes:
    """PDFをダウンロードする"""
    try:
        # URL補正（京都市パターン等）
        fixed_url = url
        if '/page/' in url:
            fixed_url = url.replace('/page/', '/')
        
        response = requests.get(fixed_url, headers=HEADERS, timeout=30)
        
        # 元のURLで404の場合、補正URLを試す
        if response.status_code == 404 and fixed_url != url:
            logger.info(f"URL補正再試行: {fixed_url}")
            response = requests.get(fixed_url, headers=HEADERS, timeout=30)
        
        if response.status_code == 200:
            return response.content
        else:
            logger.warning(f"PDFダウンロード失敗 ({response.status_code}): {url}")
            return b""
    except Exception as e:
        logger.error(f"PDFダウンロードエラー: {url} - {e}")
        return b""


def extract_text_from_pdf(pdf_content: bytes) -> str:
    """PDFからテキストを抽出する"""
    try:
        text = extract_text(io.BytesIO(pdf_content))
        if text and len(text.strip()) > 50:
            return text
        else:
            return ""
    except PDFSyntaxError as e:
        logger.error(f"PDF構文エラー: {e}")
        return ""
    except Exception as e:
        logger.error(f"PDF読み込みエラー: {e}")
        return ""


def find_keywords_in_text(text: str, keywords: list) -> list:
    """テキスト内でキーワードを検索する"""
    found_keywords = []
    for keyword in keywords:
        if keyword in text:
            found_keywords.append(keyword)
    return found_keywords


def extract_keyword_context(text: str, keyword: str, context_length: int = 50) -> str:
    """キーワード周辺のテキストを抽出する"""
    text = text.replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r'\s+', ' ', text)
    
    idx = text.find(keyword)
    if idx == -1:
        return ""
    
    start = max(0, idx - context_length)
    end = min(len(text), idx + len(keyword) + context_length)
    
    context = text[start:end]
    if start > 0:
        context = "..." + context
    if end < len(text):
        context = context + "..."
    
    return context


# ============================================
# ページスクレイピング関連
# ============================================

# 除外する過去の年度パターン
EXCLUDE_YEARS = [
    '平成', 'H2', 'H3', '2015', '2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024',
    '令和元年', '令和2年', '令和3年', '令和4年', '令和5年', '令和6年',
    'R1', 'R2', 'R3', 'R4', 'R5', 'R6'
]


def is_exclude_year(text: str) -> bool:
    """除外対象の年度が含まれているかチェック"""
    for year_pat in EXCLUDE_YEARS:
        if year_pat in text:
            return True
    return False


def is_target_year(text: str) -> bool:
    """対象年度が含まれているかチェック"""
    for year in TARGET_YEARS:
        if year in text:
            return True
    return False


def is_budget_related(text: str) -> bool:
    """予算関連のテキストかどうかをチェック"""
    for keyword in BUDGET_KEYWORDS:
        if keyword in text:
            return True
    return False


def get_page_title(soup: BeautifulSoup) -> str:
    """ページタイトルを取得"""
    # <title>タグから取得
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        # サイト名を除去（「｜」や「|」以降を削除）
        for sep in ['｜', '|', ' - ', '／']:
            if sep in title:
                title = title.split(sep)[0].strip()
        return title
    
    # <h1>タグから取得
    h1 = soup.find('h1')
    if h1:
        return h1.get_text(strip=True)
    
    return ""


def scrape_budget_pages(municipality: dict, max_depth: int = 3) -> list:
    """
    自治体サイトから予算関連のHTMLページを収集する
    
    Returns:
        ページ情報のリスト（各要素は辞書: title, url, pdfs）
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"{municipality['name']} のスクレイピングを開始")
    logger.info(f"{'='*60}")
    
    budget_pages = []
    visited = set()
    found_page_urls = set()
    
    urls_to_visit = [(url, 0) for url in municipality['start_urls']]
    
    # [追加] 開始URL自体も対象ページかチェック（京都市観光協会などのリストページ対策）
    for start_url in municipality['start_urls']:
        try:
            # ページ情報を取得
            page_info = get_page_details(start_url, municipality['base_url'])
            if page_info and len(page_info['pdfs']) > 0:
                # PDFが含まれていれば、開始ページ自体も候補とする
                # ただしタイトル条件は緩める（「情報公開」などは予算キーワードでない場合があるため）
                # ここでは「PDFがある」ことを強いシグナルとする
                logger.info(f"  📄 開始ページを候補として追加: {page_info['title']} -> {start_url}")
                budget_pages.append(page_info)
                visited.add(start_url) # 訪問済みに追加して、ループ内での再取得を防ぐ
        except Exception as e:
            logger.warning(f"開始ページの評価に失敗: {e}")

    while urls_to_visit:
        current_url, depth = urls_to_visit.pop(0)
        
        if depth > max_depth:
            continue
        
        if current_url in visited:
            continue
        
        visited.add(current_url)
        
        try:
            logger.info(f"ページをスクレイピング中: {current_url}")
            response = requests.get(current_url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            
            if response.encoding is None or response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # リンクを探索
            for link in soup.find_all('a', href=True):
                href = link['href']
                text = link.get_text(strip=True)
                
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue
                
                # 明らかに過去の年度を含むリンクは除外
                if is_exclude_year(text):
                    continue
                
                full_url = urljoin(current_url, href)
                
                # 同一ドメインのリンクのみを対象
                if not full_url.startswith(municipality['base_url']):
                    continue
                
                # PDFリンクはスキップ（ページを探している）
                if href.lower().endswith('.pdf'):
                    continue
                
                # 予算関連かつ対象年度のページを発見（保存対象）
                is_budget = is_budget_related(text)
                is_year = is_target_year(text)
                
                if is_budget and is_year:
                    if full_url not in found_page_urls and full_url not in visited:
                        logger.info(f"  📄 予算ページ発見(Keyword+Year): {text} -> {full_url}")
                        found_page_urls.add(full_url)
                        
                        # このページの詳細情報を取得
                        page_info = get_page_details(full_url, municipality['base_url'])
                        if page_info:
                            # [追加] ページタイトル自体にも予算キーワードが含まれているか最終確認
                            # リンクテキストだけでなく、実際のページタイトルで判定することで精度を高める
                            if is_budget_related(page_info['title']):
                                budget_pages.append(page_info)
                            else:
                                logger.info(f"    × タイトルに予算キーワードなし、除外: {page_info['title']}")
                
                # サブページとして探索（予算関連キーワード OR 年度関連）
                # 京丹後市などのように「令和7年度」だけのリンクを辿る必要がある
                elif (is_budget or is_year) and full_url not in visited:
                    urls_to_visit.append((full_url, depth + 1))
            
            # --- ページ内PDFチェックによる救済措置 ---
            # もしこのページ自体が対象ページかもしれない場合（探索過程で訪れたページ）
            # ページタイトルを取得して再判定すると精度が上がるが、ここでは簡易的に
            # 「PDFを含んでいて、URLやタイトルに年度が含まれる」なら保存するロジックを追加検討
            # 現状はリンク探索時の判定のみで進める
            
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"ページ取得エラー: {current_url} - {e}")
    
    logger.info(f"{municipality['name']}: {len(budget_pages)}件の予算ページを発見")
    return budget_pages


def get_page_details(page_url: str, base_url: str) -> dict:
    """
    予算ページの詳細情報（タイトル、PDF一覧）を取得する
    """
    try:
        response = requests.get(page_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        
        if response.encoding is None or response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # ページタイトル取得
        title = get_page_title(soup)
        if not title:
            title = page_url.split('/')[-1]
        
        # ページ内のPDFリンクを収集
        pdf_urls = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.pdf'):
                pdf_url = urljoin(page_url, href)
                if pdf_url.startswith(base_url):
                    pdf_urls.append(pdf_url)
        
        logger.info(f"    タイトル: {title}, PDF数: {len(pdf_urls)}")
        
        return {
            'title': title,
            'url': page_url,
            'pdfs': pdf_urls
        }
        
    except Exception as e:
        logger.error(f"ページ詳細取得エラー: {page_url} - {e}")
        return None


def analyze_page(page_info: dict, municipality_name: str) -> dict:
    """
    ページを分析（ページ内のPDFからキーワードを検索）
    """
    result = {
        'Detected_Date': datetime.now().strftime('%Y/%m/%d'),
        'Municipality': municipality_name,
        'Title': page_info['title'],
        'Page_URL': page_info['url'],
        'Has_Tourism_Keyword': 'FALSE',
        'Has_Inflation_Keyword': 'FALSE',
        'Excerpt_Summary': ''
    }
    
    all_text = ""
    found_tourism = []
    found_inflation = []
    
    # ページ内の各PDFを分析
    for pdf_url in page_info['pdfs'][:5]:  # 最大5つまで
        pdf_content = download_pdf(pdf_url)
        if pdf_content:
            text = extract_text_from_pdf(pdf_content)
            if text:
                all_text += text + "\n"
                found_tourism.extend(find_keywords_in_text(text, TOURISM_KEYWORDS))
                found_inflation.extend(find_keywords_in_text(text, INFLATION_KEYWORDS))
        time.sleep(0.5)
    
    # 重複を除去
    found_tourism = list(set(found_tourism))
    found_inflation = list(set(found_inflation))
    
    if found_tourism:
        result['Has_Tourism_Keyword'] = 'TRUE'
        logger.info(f"  観光関連キーワード発見: {found_tourism}")
    
    if found_inflation:
        result['Has_Inflation_Keyword'] = 'TRUE'
        logger.info(f"  物価高騰関連キーワード発見: {found_inflation}")
    
    # 抜粋サマリーの作成
    excerpts = []
    all_found = found_tourism + found_inflation
    for keyword in all_found[:3]:
        context = extract_keyword_context(all_text, keyword)
        if context:
            excerpts.append(f"【{keyword}】{context}")
    
    if excerpts:
        result['Excerpt_Summary'] = ' | '.join(excerpts)
    elif page_info['pdfs']:
        result['Excerpt_Summary'] = f"PDF {len(page_info['pdfs'])}件を含むページ"
    else:
        result['Excerpt_Summary'] = "PDFなし"
    
    return result


# ============================================
# メイン処理
# ============================================

def main():
    """メイン処理（ページベース版・ハッシュ比較による更新検知）"""
    logger.info("=" * 70)
    logger.info("自治体予算情報スクレイピング・分析スクリプト（ページベース版）開始")
    logger.info("【ハッシュ比較モード】ページ内容の変更を検知します")
    logger.info("=" * 70)
    logger.info(f"対象年度: {', '.join(TARGET_YEARS)}")
    logger.info(f"観光キーワード数: {len(TOURISM_KEYWORDS)}件")
    
    municipalities = load_municipalities_from_csv()
    
    if not municipalities:
        logger.error("スクレイピング対象の自治体が登録されていません。")
        return []
    
    logger.info(f"スクレイピング対象: {', '.join([m['name'] for m in municipalities])}")
    
    # 履歴を読み込み（ハッシュ比較用）
    history = load_history()
    
    new_results = []
    updated_results = []
    unchanged_count = 0
    all_results = []  # 全ての結果（CSV再生成用）
    
    for municipality in municipalities:
        try:
            # 予算ページを収集
            budget_pages = scrape_budget_pages(municipality)
            
            if not budget_pages:
                logger.warning(f"{municipality['name']}: 予算ページが見つかりませんでした")
                continue
            
            # 各ページを分析
            for page_info in budget_pages:
                page_url = page_info['url']
                current_hash = calculate_page_hash(page_info)
                
                # 履歴と比較
                if page_url in history:
                    old_data = history[page_url]
                    old_hash = old_data.get('hash', '')
                    old_date = old_data.get('date', '')
                    
                    if current_hash == old_hash:
                        # ハッシュが同じ = 変更なし → 前回の日付を維持
                        logger.info(f"[UNCHANGED] {page_info['title']}")
                        unchanged_count += 1
                        
                        # 前回のデータを流用（日付は変えない）
                        result = analyze_page(page_info, municipality['name'])
                        result['Detected_Date'] = old_date  # 前回の日付を維持
                        all_results.append(result)
                        
                        # 履歴を更新（ハッシュは同じだが念のため）
                        history[page_url] = {'hash': current_hash, 'date': old_date}
                        continue
                    else:
                        # ハッシュが異なる = 更新あり → 新しい日付
                        logger.info(f"\n--- [UPDATED] {municipality['name']} ページ更新検知: {page_info['title']} ---")
                        
                        result = analyze_page(page_info, municipality['name'])
                        result['Detected_Date'] = get_jst_now().strftime('%Y/%m/%d')
                        updated_results.append(result)
                        all_results.append(result)
                        
                        # 履歴を更新
                        history[page_url] = {'hash': current_hash, 'date': result['Detected_Date']}
                else:
                    # 新規ページ
                    logger.info(f"\n--- [NEW] {municipality['name']} 新規ページ: {page_info['title']} ---")
                    
                    result = analyze_page(page_info, municipality['name'])
                    result['Detected_Date'] = get_jst_now().strftime('%Y/%m/%d')
                    new_results.append(result)
                    all_results.append(result)
                    
                    # 履歴に追加
                    history[page_url] = {'hash': current_hash, 'date': result['Detected_Date']}
                
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"{municipality['name']} の処理中にエラーが発生: {e}")
            continue
    
    # CSVを全件で上書き保存（重複防止）
    if all_results:
        columns = ['Detected_Date', 'Municipality', 'Title', 'Page_URL', 
                   'Has_Tourism_Keyword', 'Has_Inflation_Keyword', 'Excerpt_Summary']
        try:
            with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for result in all_results:
                    writer.writerow(result)
            logger.info(f"📊 結果CSV保存完了: {len(all_results)}件")
        except Exception as e:
            logger.error(f"結果CSV保存エラー: {e}")
    
    # 履歴を保存
    save_history(history)
    
    # サマリー出力
    logger.info("\n" + "=" * 70)
    logger.info("処理結果サマリー")
    logger.info("=" * 70)
    logger.info(f"📊 変更なし: {unchanged_count}件")
    logger.info(f"🔄 更新検知: {len(updated_results)}件")
    logger.info(f"🆕 新規検出: {len(new_results)}件")
    
    changed_results = new_results + updated_results
    if changed_results:
        tourism_count = sum(1 for r in changed_results if r['Has_Tourism_Keyword'] == 'TRUE')
        inflation_count = sum(1 for r in changed_results if r['Has_Inflation_Keyword'] == 'TRUE')
        logger.info(f"   ├─ 観光関連キーワード含有: {tourism_count}件")
        logger.info(f"   └─ 物価高騰関連キーワード含有: {inflation_count}件")
        
        logger.info("\n📋 新規/更新ページ:")
        for r in changed_results:
            kw_flag = "✓" if r['Has_Tourism_Keyword'] == 'TRUE' else "-"
            logger.info(f"   [{kw_flag}] {r['Municipality']}: {r['Title']}")
    else:
        logger.info("   → 新着・更新ページはありませんでした")
    
    logger.info("\n" + "=" * 70)
    logger.info("処理完了")
    logger.info("=" * 70)
    
    # 最終更新日時を保存（日本時間）
    try:
        with open(LAST_UPDATED_FILE, 'w', encoding='utf-8') as f:
            f.write(get_jst_now().strftime('%Y-%m-%d %H:%M'))
        logger.info("📅 最終更新日時を保存しました（JST）")
    except Exception as e:
        logger.error(f"最終更新日時の保存に失敗: {e}")
    
    # JSON変換を実行
    try:
        import subprocess
        convert_script = os.path.join(SCRIPT_DIR, 'convert_to_json.py')
        if os.path.exists(convert_script):
            logger.info("\n" + "=" * 70)
            logger.info("データ変換処理（JSON化）を開始")
            subprocess.run([sys.executable, convert_script], check=True)
    except Exception as e:
        logger.error(f"JSON変換実行エラー: {e}")
    
    return changed_results


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スクレイパーのテストスクリプト - 完全コピー"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

TARGET_YEARS = [
    '令和7年度', '令和8年度', '令和9年度',
    '令和７年度', '令和８年度', '令和９年度',
    'R7', 'R8', 'R9', '2025', '2026', '2027'
]
BUDGET_KEYWORDS = ['予算', '補正', '当初', '概要', '方針', '要領', '決算']

EXCLUDE_YEARS = [
    '平成', 'H2', 'H3', 
    '2015', '2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024',
    '令和元年', '令和2年', '令和3年', '令和4年', '令和5年', '令和6年',
    '令和２年', '令和３年', '令和４年', '令和５年', '令和６年',
    'R1', 'R2', 'R3', 'R4', 'R5', 'R6'
]

def is_exclude_year(text):
    for year_pat in EXCLUDE_YEARS:
        if year_pat in text:
            return True
    return False

def is_target_year(text):
    for year in TARGET_YEARS:
        if year in text:
            return True
    return False

def is_budget_related(text):
    for keyword in BUDGET_KEYWORDS:
        if keyword in text:
            return True
    return False

def simulate_scrape(name, start_url):
    print(f"\n{'='*60}")
    print(f"シミュレート: {name}")
    print(f"URL: {start_url}")
    print(f"{'='*60}")
    
    parsed = urlparse(start_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    print(f"Base URL: {base_url}")
    
    try:
        response = requests.get(start_url, headers=HEADERS, timeout=30)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')
        
        found_pages = []
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True)
            
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            
            # 除外年度チェック
            if is_exclude_year(text):
                continue
            
            full_url = urljoin(start_url, href)
            
            # 同一ドメインチェック
            if not full_url.startswith(base_url):
                continue
            
            # PDFスキップ
            if href.lower().endswith('.pdf'):
                continue
            
            is_budget = is_budget_related(text)
            is_year = is_target_year(text)
            
            if is_budget and is_year:
                print(f"  [FOUND] {text}")
                print(f"          URL: {full_url}")
                found_pages.append({'text': text, 'url': full_url})
        
        print(f"\n検出ページ数: {len(found_pages)}")
        return found_pages
        
    except Exception as e:
        print(f"  エラー: {e}")
        return []

if __name__ == "__main__":
    simulate_scrape("京都府", "https://www.pref.kyoto.jp/yosan/")
    simulate_scrape("兵庫県", "https://web.pref.hyogo.lg.jp/kk20/pa02_000000112.html")
    simulate_scrape("南あわじ市", "https://www.city.minamiawaji.hyogo.jp/site/sub-site-zaimu/list140-186.html")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スクレイパーのテストスクリプト"""

import requests
from bs4 import BeautifulSoup

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

def test_url(name, url, base_url):
    print(f"\n{'='*60}")
    print(f"テスト: {name}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')
        
        found_links = []
        for link in soup.find_all('a', href=True):
            text = link.get_text(strip=True)
            href = link['href']
            
            # 除外年度チェック
            if is_exclude_year(text):
                continue
                
            budget = is_budget_related(text)
            year = is_target_year(text)
            
            if budget and year:
                print(f"  [MATCH] {text}")
                print(f"          -> {href}")
                found_links.append(text)
            elif year or budget:
                # 部分マッチを表示（デバッグ用）
                if '令和7' in text or '令和8' in text or '令和７' in text or '令和８' in text:
                    print(f"  [PARTIAL] {text} (budget={budget}, year={year})")
        
        if not found_links:
            print("  -> マッチするリンクが見つかりませんでした")
            print("\n  リンク一覧（予算関連のみ）:")
            for link in soup.find_all('a', href=True):
                text = link.get_text(strip=True)
                if is_budget_related(text) and not is_exclude_year(text):
                    print(f"    - {text}")
                    
    except Exception as e:
        print(f"  エラー: {e}")

if __name__ == "__main__":
    # テスト対象URL
    test_url("京都府", "https://www.pref.kyoto.jp/yosan/", "https://www.pref.kyoto.jp")
    test_url("兵庫県", "https://web.pref.hyogo.lg.jp/kk20/pa02_000000112.html", "https://web.pref.hyogo.lg.jp")
    test_url("南あわじ市", "https://www.city.minamiawaji.hyogo.jp/site/sub-site-zaimu/list140-186.html", "https://www.city.minamiawaji.hyogo.jp")

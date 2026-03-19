"""
行政予算・プロポーザル モニタリングシステム
================================================
対象スプレッドシート: budget-proposal-collector
  - target-list シート: 監視対象URL一覧
      A: 都道府県  B: 自治体名  C: 種別  D: 監視URL  E: 備考
      F: ページハッシュ（スクリプトが自動管理）
      G: 最終確認日時（スクリプトが自動管理）
  - collection  シート: 収集データ保存先
  - log         シート: 実行ログ（自動作成）

収集ルール:
  【公募（プロポーザル）】
    - 補助・助成・入札はスキップ（SKIP_KEYWORDS_KOUBO で事前除外）
    - それ以外はすべて取り込み（委託・プロポーザル・公募）
    - 予算額は常に取得
    - AI要約は観光関連のもののみ生成（非観光は案件名＋予算額のみ）
  【予算】
    - 対象年度（令和7年度以降）かつ観光関連のリンクのみ取り込む
    - Gemini で要約・予算額を抽出

処理フロー（予算）:
  1. 監視URLのページハッシュを前回と比較 → 変更なしならスキップ
  2. 変更あり/初回: ページ内リンクを最大3階層まで探索
  3. 「年度フィルタ（令和7年度/R7/2025以降）」でリンクを絞り込む
  4. 観光キーワードスコアリングで関連リンクを抽出
  5. Gemini AI で要約・予算額を抽出してスプレッドシートに保存

処理フロー（公募）:
  1. 監視URLの直下リンクを毎回収集
  2. SKIP_KEYWORDS_KOUBO で補助・助成・入札を除外
  3. 観光スコアリングで要約生成の要否を判断
  4. 観光関連 → Gemini でフル要約（案件名＋要約＋予算額）
     非観光  → Gemini で案件名＋予算額のみ取得（要約なし）
  5. すべてスプレッドシートに保存

必要ライブラリ:
  pip install requests beautifulsoup4 gspread google-generativeai python-dotenv pdfminer.six
"""

import hashlib
import io
import os
import re
import time
import uuid
import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import gspread
import google.generativeai as genai
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# 初期設定
# ─────────────────────────────────────────────
load_dotenv()

GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY")
SERVICE_ACCOUNT  = os.getenv("SERVICE_ACCOUNT_FILE", "/tmp/service_account.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "budget-proposal-collector")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

# ── Gemini フォールバックモデル ──────────────────
GEMINI_MODELS = [
    "gemini-2.5-flash-lite-preview-06-17",
    "gemini-2.5-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
]
_exhausted_models: set = set()

# ── 予算ページ：年度フィルタ ─────────────────────
TARGET_YEARS = [
    "令和7年度", "令和8年度", "令和9年度",
    "令和７年度", "令和８年度", "令和９年度",
    "R7", "R8", "R9", "2025", "2026", "2027",
]
EXCLUDE_YEARS = [
    "平成", "H2", "H3",
    "2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024",
    "令和元年", "令和2年", "令和3年", "令和4年", "令和5年", "令和6年",
    "令和２年", "令和３年", "令和４年", "令和５年", "令和６年",
    "R1", "R2", "R3", "R4", "R5", "R6",
]
BUDGET_KEYWORDS = ["予算", "補正", "当初", "概要", "方針", "要領", "決算"]
MAX_CRAWL_DEPTH = 3

# ── 観光関連キーワード ────────────────────────────
TOURISM_KEYWORDS = {
    "観光":       5, "インバウンド": 5, "訪日":       5, "宿泊":       5,
    "ガストロノミー": 5, "地域活性":   5, "地方創生":   5, "観光庁":     5,
    "観光振興":   5, "観光地":      5, "観光客":      5, "旅行":       5,
    "ツーリズム": 3, "dmo":        3, "DMO":        3, "体験":       3,
    "まちづくり": 3, "地域資源":   3, "周遊":        3, "着地型":     3,
    "ホテル":     3, "旅館":       3, "温泉":        3, "クルーズ":    3,
    "文化":       1, "歴史":       1, "自然":        1, "イベント":   1,
    "キャンプ":   1, "アウトドア": 1, "スポーツ":    1, "祭り":       1,
}
TOURISM_THRESHOLD = 3

# ── 公募ページ：事前除外キーワード ──────────────────
SKIP_KEYWORDS_KOUBO = [
    "補助金", "助成金", "補助事業", "助成事業",
    "入札", "入札公告", "指名競争", "一般競争入札", "随意契約",
    "物品調達", "購入", "買入", "リース",
    "人事", "採用", "求人", "職員募集", "訃報", "お知らせ",
]


# ─────────────────────────────────────────────
# スプレッドシート接続・データ取得
# ─────────────────────────────────────────────

def get_spreadsheet():
    """スプレッドシートオブジェクトを返す。失敗時は None。"""
    try:
        gc = gspread.service_account(filename=SERVICE_ACCOUNT)
        return gc.open(SPREADSHEET_NAME)
    except Exception as e:
        print(f"❌ スプレッドシート接続エラー: {e}")
        return None


def get_target_list(sh) -> tuple[list[dict], gspread.Worksheet]:
    """target-list シートから有効な監視URL一覧を返す。"""
    ws   = sh.worksheet("target-list")
    rows = ws.get_all_records()
    valid = [r for r in rows if str(r.get("監視URL", "")).startswith("http")]
    print(f"📋 監視URL: {len(valid)} 件")
    return valid, ws


def get_existing_urls(sh) -> set:
    """collection シートのG列（参照URL）を重複チェック用セットで返す。"""
    try:
        ws = sh.worksheet("collection")
        return set(ws.col_values(7)[1:])
    except Exception as e:
        print(f"⚠️ 既存URL取得エラー: {e}")
        return set()


def update_target_hash(ws: gspread.Worksheet, row_index: int,
                       new_hash: str, checked_at: str):
    """target-list の F・G列を更新する。"""
    try:
        ws.update(f"F{row_index}:G{row_index}", [[new_hash, checked_at]])
    except Exception as e:
        print(f"   ⚠️ ハッシュ更新エラー (行{row_index}): {e}")


def ensure_headers(sh):
    """
    target-list の F1:G1 ヘッダーが未設定なら自動追記する。
    collection の J1:K1 ヘッダーも同様。
    """
    try:
        tl = sh.worksheet("target-list")
        headers = tl.row_values(1)
        # F1, G1 が空なら書き込む
        updates = []
        if len(headers) < 6 or not headers[5]:
            updates.append({"range": "F1", "values": [["ページハッシュ"]]})
        if len(headers) < 7 or not headers[6]:
            updates.append({"range": "G1", "values": [["最終確認日時"]]})
        if updates:
            for u in updates:
                tl.update(u["range"], u["values"])
            print("   ✅ target-list ヘッダー補完完了")
    except Exception as e:
        print(f"   ⚠️ ヘッダー確認エラー: {e}")

    try:
        col = sh.worksheet("collection")
        headers = col.row_values(1)
        updates = []
        if len(headers) < 10 or not headers[9]:
            updates.append({"range": "J1", "values": [["自治体名"]]})
        if len(headers) < 11 or not headers[10]:
            updates.append({"range": "K1", "values": [["都道府県"]]})
        if updates:
            for u in updates:
                col.update(u["range"], u["values"])
            print("   ✅ collection ヘッダー補完完了")
    except Exception as e:
        print(f"   ⚠️ collection ヘッダー確認エラー: {e}")


# ─────────────────────────────────────────────
# ハッシュ計算・更新検知
# ─────────────────────────────────────────────

def calculate_page_hash(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    links = set()
    for a in soup.find_all("a", href=True):
        abs_url = urljoin(base_url, a["href"])
        if urlparse(abs_url).netloc == base_domain:
            links.add(abs_url)
    content = title + "|" + ",".join(sorted(links))
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def is_page_updated(html: str, base_url: str, stored_hash: str) -> tuple[bool, str]:
    new_hash = calculate_page_hash(html, base_url)
    return (new_hash != stored_hash, new_hash)


# ─────────────────────────────────────────────
# 年度フィルタ
# ─────────────────────────────────────────────

def is_exclude_year(text: str) -> bool:
    return any(y in text for y in EXCLUDE_YEARS)

def is_target_year(text: str) -> bool:
    return any(y in text for y in TARGET_YEARS)

def is_budget_related(text: str) -> bool:
    return any(kw in text for kw in BUDGET_KEYWORDS)


# ─────────────────────────────────────────────
# スクレイピング
# ─────────────────────────────────────────────

def fetch_html(url: str, timeout: int = 15) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        if resp.encoding is None or resp.encoding.upper() == "ISO-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text
    except Exception as e:
        print(f"   ⚠️ HTML取得失敗 ({url}): {e}")
        return None


def scrape_budget_links(monitor_url: str, existing_urls: set,
                        max_depth: int = MAX_CRAWL_DEPTH) -> list[dict]:
    """【予算専用】最大 max_depth 階層まで辿り、対象年度×予算キーワードのリンクを収集。"""
    visited      = set()
    found_urls   = set()
    new_links    = []
    base_domain  = urlparse(monitor_url).netloc
    to_visit     = [(monitor_url, 0)]

    while to_visit:
        current_url, depth = to_visit.pop(0)
        if depth > max_depth or current_url in visited:
            continue
        visited.add(current_url)

        html = fetch_html(current_url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        time.sleep(1)

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            link_text = a.get_text(strip=True)
            abs_url   = urljoin(current_url, href)
            parsed    = urlparse(abs_url)

            if parsed.netloc and parsed.netloc != base_domain:
                continue
            ext = parsed.path.lower().rsplit(".", 1)[-1] if "." in parsed.path else ""
            if ext in ("jpg", "jpeg", "png", "gif", "svg", "css", "js", "ico"):
                continue

            if is_exclude_year(link_text):
                continue

            is_budget = is_budget_related(link_text)
            is_year   = is_target_year(link_text)
            is_pdf    = ext == "pdf"

            if (is_budget and is_year) or (is_pdf and is_year):
                if abs_url not in existing_urls and abs_url not in found_urls:
                    found_urls.add(abs_url)
                    new_links.append({"url": abs_url, "text": link_text, "is_pdf": is_pdf})
                    print(f"   📄 予算リンク発見: {link_text[:50]} → {abs_url}")
            elif (is_budget or is_year) and abs_url not in visited:
                to_visit.append((abs_url, depth + 1))

    return new_links


def scrape_proposal_links(monitor_url: str, existing_urls: set) -> list[dict]:
    """【公募専用】監視URLの直下リンクを1階層収集（年度フィルタなし）。"""
    html = fetch_html(monitor_url)
    if not html:
        return []

    base_domain = urlparse(monitor_url).netloc
    seen        = set()
    new_links   = []

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        abs_url   = urljoin(monitor_url, href)
        parsed    = urlparse(abs_url)
        link_text = a.get_text(strip=True)

        if parsed.netloc and parsed.netloc != base_domain:
            continue
        ext = parsed.path.lower().rsplit(".", 1)[-1] if "." in parsed.path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "svg", "css", "js", "ico"):
            continue
        if abs_url in existing_urls or abs_url in seen:
            continue
        if not link_text:
            continue
        seen.add(abs_url)

        new_links.append({"url": abs_url, "text": link_text, "is_pdf": ext == "pdf"})

    return new_links


def fetch_page_text(url: str, max_chars: int = 4000) -> str:
    return (_fetch_pdf_text(url, max_chars)
            if url.lower().endswith(".pdf")
            else _fetch_html_text(url, max_chars))


def _fetch_html_text(url: str, max_chars: int) -> str:
    html = fetch_html(url)
    if not html:
        return ""
    soup  = BeautifulSoup(html, "html.parser")
    paras = soup.find_all(["p", "li", "td", "h1", "h2", "h3", "dt", "dd"])
    return "\n".join(p.get_text(strip=True) for p in paras
                     if p.get_text(strip=True))[:max_chars]


def _fetch_pdf_text(url: str, max_chars: int) -> str:
    try:
        from pdfminer.high_level import extract_text
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = extract_text(io.BytesIO(resp.content))
        return (text or "")[:max_chars]
    except ImportError:
        print("   ⚠️ pdfminer.six 未インストール")
        return ""
    except Exception as e:
        print(f"   ⚠️ PDF取得失敗 ({url}): {e}")
        return ""


# ─────────────────────────────────────────────
# 観光関連スコアリング
# ─────────────────────────────────────────────

def is_tourism_related(link_text: str, url: str) -> tuple[bool, int]:
    text  = (link_text + " " + url).lower()
    score = sum(pts for kw, pts in TOURISM_KEYWORDS.items() if kw.lower() in text)
    return (score >= TOURISM_THRESHOLD, score)


# ─────────────────────────────────────────────
# Gemini AI 処理
# ─────────────────────────────────────────────

def summarize_with_gemini(link_text: str, url: str, municipality: str,
                          category: str, page_text: str = "",
                          include_summary: bool = True) -> dict:
    """
    Gemini で案件名・要約・予算額を抽出する。

    include_summary=False の場合（非観光の公募）:
      - 案件名 + 予算額 のみ取得（要約は生成しない）
      - SKIP 判定は行わない（すべて保存対象）

    返り値: {"案件名": str, "要約": str, "予算額": str, "skip": bool}
    """
    body_section = f"【ページ本文】\n{page_text}\n" if page_text else ""
    note = "" if page_text else "※本文取得できず。リンクテキストとURLから推測してください。\n"

    # ── 公募 × 非観光: 案件名＋予算額のみ取得（要約なし・SKIP判定なし）──
    if category == "公募" and not include_summary:
        prompt = (
            "あなたは行政の委託・プロポーザル・公募情報を専門とするアナリストです。\n"
            "以下の行政情報から案件名と予算額のみを抽出してください。\n\n"
            "【出力フォーマット（厳守）】\n"
            "案件名：（正式名称。不明ならリンクテキストをそのまま使用）\n"
            "予算額：（業務委託費・事業予算規模。不明なら「不明」）\n\n"
            "※要約行は出力不要です。上記2項目のみ出力してください。\n"
            f"{note}"
            f"\n自治体名：{municipality}\n種別：{category}\n"
            f"リンクテキスト：{link_text}\nURL：{url}\n{body_section}"
        )
        for model_name in GEMINI_MODELS:
            if model_name in _exhausted_models:
                continue
            for attempt in range(3):
                try:
                    model    = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    raw      = response.text.strip().replace("**", "").replace("*", "")
                    return _parse_gemini_output(raw, link_text, include_summary=False)
                except Exception as e:
                    err = str(e)
                    if "404" in err or "not found" in err.lower():
                        _exhausted_models.add(model_name); break
                    if "429" in err or "exhausted" in err.lower():
                        if "limit: 0" in err:
                            _exhausted_models.add(model_name); break
                        wait = 20 * (2 ** attempt)
                        print(f"   ⚠️ レート制限 ({model_name}) → {wait}秒待機...")
                        time.sleep(wait)
                    else:
                        print(f"   ❌ Geminiエラー ({model_name}): {e}"); break
        return {"案件名": link_text, "要約": "", "予算額": "不明", "skip": False}

    # ── 公募 × 観光 / 予算: フル処理 ──
    if category == "公募":
        role_prompt = (
            "あなたは行政の委託・プロポーザル・公募情報を専門とするアナリストです。\n"
            "委託、プロポーザル、公募（業務委託の公募含む）を対象に処理します。\n"
        )
        skip_cond = (
            "① 補助金・助成金・入札（物品調達）に明らかに該当する\n"
            "② 本文が取得できず内容が判断できない\n"
        )
    else:  # 予算
        role_prompt = (
            "あなたは観光誘客・地域活性化・インバウンド施策を専門とするアナリストです。\n"
            "行政の予算情報の中から観光・宿泊・地域活性化に関係する情報を抽出します。\n"
        )
        skip_cond = (
            "① 観光・宿泊・インバウンド・地域活性化・まちづくりと無関係\n"
            "② 本文が取得できず内容が判断できない\n"
        )

    prompt = (
        f"{role_prompt}\n"
        "以下の行政情報リンクについて処理してください。\n\n"
        "【除外条件】次のいずれかに該当する場合は「SKIP」の4文字だけ出力してください。\n"
        f"{skip_cond}\n"
        "【対象の場合の出力フォーマット（厳守）】\n"
        "案件名：（正式名称。不明ならリンクテキストをそのまま使用）\n"
        "要約：・（内容・目的を1〜2行で簡潔に）\n"
        "　　　・（応募条件・対象者など必要に応じて1行追加）\n"
        "予算額：（補助上限額・事業予算規模。不明なら「不明」）\n\n"
        "※「・」以外の箇条書き記号・マークダウン記号は不要。5行以内で出力。\n"
        f"{note}"
        f"\n自治体名：{municipality}\n種別：{category}\n"
        f"リンクテキスト：{link_text}\nURL：{url}\n{body_section}"
    )

    for model_name in GEMINI_MODELS:
        if model_name in _exhausted_models:
            continue
        for attempt in range(3):
            try:
                model    = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                raw      = response.text.strip().replace("**", "").replace("*", "")
                if raw.strip() == "SKIP":
                    return {"案件名": "", "要約": "", "予算額": "", "skip": True}
                return _parse_gemini_output(raw, link_text)
            except Exception as e:
                err = str(e)
                if "404" in err or "not found" in err.lower():
                    _exhausted_models.add(model_name); break
                if "429" in err or "exhausted" in err.lower():
                    if "limit: 0" in err:
                        _exhausted_models.add(model_name); break
                    wait = 20 * (2 ** attempt)
                    print(f"   ⚠️ レート制限 ({model_name}) → {wait}秒待機...")
                    time.sleep(wait)
                else:
                    print(f"   ❌ Geminiエラー ({model_name}): {e}"); break

    return {"案件名": link_text, "要約": "", "予算額": "", "skip": False}


def _parse_gemini_output(raw: str, fallback_name: str,
                         include_summary: bool = True) -> dict:
    案件名 = fallback_name
    要約行 = []
    予算額 = "不明"
    in_summary = False

    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("案件名："):
            案件名 = line.replace("案件名：", "").strip(); in_summary = False
        elif line.startswith("要約："):
            text = line.replace("要約：", "").strip()
            if text: 要約行.append(text)
            in_summary = True
        elif in_summary and line.startswith("・"):
            要約行.append(line)
        elif line.startswith("予算額："):
            予算額 = line.replace("予算額：", "").strip(); in_summary = False

    要約 = ("\n".join(要約行) if 要約行 else raw[:300]) if include_summary else ""
    return {"案件名": 案件名, "要約": 要約, "予算額": 予算額, "skip": False}


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def collect():
    print("=" * 60)
    print("  行政予算・プロポーザル モニタリング 開始")
    print(f"  実行日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  対象年度: {', '.join(TARGET_YEARS[:6])} ...")
    print("=" * 60)

    sh = get_spreadsheet()
    if not sh:
        return

    # ヘッダー自動補完
    ensure_headers(sh)

    target_list, target_ws = get_target_list(sh)
    existing_urls          = get_existing_urls(sh)
    print(f"📂 収集済みURL: {len(existing_urls)} 件\n")

    new_rows   = []
    stat       = {"検出": 0, "ハッシュ変化なし": 0, "年度除外": 0,
                  "観光フィルタ除外": 0, "AI_SKIP": 0, "保存": 0, "エラー": 0}
    error_urls = []
    now_str    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    row_offset = 2

    for idx, target in enumerate(target_list):
        municipality = target.get("自治体名", "")
        prefecture   = target.get("都道府県", "")
        category     = target.get("種別", "")
        monitor_url  = target.get("監視URL", "")
        stored_hash  = str(target.get("ページハッシュ", ""))
        sheet_row    = idx + row_offset

        print(f"\n{'─'*55}")
        print(f"🔍 {municipality}【{category}】")
        print(f"   {monitor_url}")

        html = fetch_html(monitor_url)
        if not html:
            error_urls.append(monitor_url)
            stat["エラー"] += 1
            continue

        if category == "予算":
            updated, new_hash = is_page_updated(html, monitor_url, stored_hash)
            if not updated and stored_hash:
                print("   ✅ ページ変化なし（ハッシュ一致）→ スキップ")
                stat["ハッシュ変化なし"] += 1
                update_target_hash(target_ws, sheet_row, new_hash, now_str)
                continue
            status = "初回" if not stored_hash else "更新あり"
            print(f"   🔄 {status}（ハッシュ変化）→ クロール開始")
            update_target_hash(target_ws, sheet_row, new_hash, now_str)
            new_links = scrape_budget_links(monitor_url, existing_urls)
        else:
            new_links = scrape_proposal_links(monitor_url, existing_urls)
            update_target_hash(target_ws, sheet_row,
                               calculate_page_hash(html, monitor_url), now_str)

        print(f"   ✨ 新着リンク: {len(new_links)} 件")
        if not new_links:
            print("   → 新着なし。次へ。")
            continue

        for lk in new_links:
            lk_url  = lk["url"]
            lk_text = lk["text"] or urlparse(lk_url).path.split("/")[-1]
            is_pdf  = lk["is_pdf"]
            stat["検出"] += 1

            print(f"\n   [{stat['検出']}] {'📄' if is_pdf else '🌐'} {lk_text[:55]}")

            include_summary = True

            if category == "予算":
                related, score = is_tourism_related(lk_text, lk_url)
                if not related:
                    print(f"       ⏭️ 観光スコア {score}点 → スキップ")
                    existing_urls.add(lk_url)
                    stat["観光フィルタ除外"] += 1
                    continue
                print(f"       ✅ 観光スコア: {score}点")

            elif category == "公募":
                matched = next((kw for kw in SKIP_KEYWORDS_KOUBO if kw in lk_text), None)
                if matched:
                    print(f"       ⏭️ 除外キーワード「{matched}」→ スキップ")
                    existing_urls.add(lk_url)
                    stat["観光フィルタ除外"] += 1
                    continue
                related, score = is_tourism_related(lk_text, lk_url)
                include_summary = related
                if related:
                    print(f"       ✅ 観光スコア: {score}点 → AI要約あり")
                else:
                    print(f"       ℹ️ 観光スコア: {score}点 → 予算額のみ取得")

            page_text = fetch_page_text(lk_url)
            if page_text:
                print(f"       📝 本文: {len(page_text)} 文字")

            print("       🤖 Gemini 処理中...")
            result = summarize_with_gemini(lk_text, lk_url, municipality,
                                           category, page_text,
                                           include_summary=include_summary)

            if category == "予算" and result["skip"]:
                print("       ⏭️ Gemini SKIP（観光無関係）")
                existing_urls.add(lk_url)
                stat["AI_SKIP"] += 1
                time.sleep(10)
                continue

            if category == "公募" and result["skip"]:
                print("       ⚠️ Gemini はSKIPと判断したが公募のため保存を継続")

            row = [
                f"ID-{uuid.uuid4().hex[:16]}",
                datetime.date.today().strftime("%Y/%m/%d"),
                category,
                result["案件名"] or lk_text,
                result["予算額"],
                result["要約"],
                lk_url,
                "未読",
                "N",
                municipality,
                prefecture,
            ]
            new_rows.append(row)
            existing_urls.add(lk_url)
            stat["保存"] += 1

            print(f"       💾 保存予定: {(result['案件名'] or lk_text)[:45]}")
            print(f"       ⏳ 15秒待機中...")
            time.sleep(15)

    # ── スプレッドシートへ一括保存 ─────────────────
    print(f"\n{'='*55}")
    print("📊 処理結果サマリー")
    for k, v in stat.items():
        print(f"   {k}: {v} 件")

    if new_rows:
        print("\n💾 スプレッドシートへ書き込み中...")
        try:
            ws = sh.worksheet("collection")
            ws.append_rows(new_rows, value_input_option="USER_ENTERED")
            print(f"✅ {len(new_rows)} 件を保存しました。")
        except Exception as e:
            print(f"❌ 書き込みエラー: {e}")
    else:
        print("\n✅ 新着データなし。終了します。")

    _write_log(sh, stat, error_urls)
    print(f"\n🎉 完了: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def _write_log(sh, stat: dict, error_urls: list):
    """実行ログを log シートへ追記する（シートがなければ自動作成）"""
    try:
        try:
            ws = sh.worksheet("log")
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title="log", rows=1000, cols=9)
            ws.append_row(["実行日時", "検出数", "ハッシュ変化なし",
                           "年度除外", "観光フィルタ除外", "AI_SKIP",
                           "保存数", "エラー数", "エラーURL"])
        ws.append_row([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            stat["検出"], stat["ハッシュ変化なし"], stat.get("年度除外", 0),
            stat["観光フィルタ除外"], stat["AI_SKIP"],
            stat["保存"], stat["エラー"],
            " / ".join(error_urls) if error_urls else "",
        ])
    except Exception as e:
        print(f"⚠️ ログ書き込みエラー: {e}")


if __name__ == "__main__":
    collect()

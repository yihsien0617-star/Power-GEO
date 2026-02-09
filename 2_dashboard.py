# 檔案名稱：2_dashboard.py
# 升級版：完全對應最新版 powergeo.py（Keyword_Source / Seed_Term / Evidence / Trends_Score...）
# 新增：系主任一頁式（競品Top5、決策問題Top10、內容缺口、下月行動清單）+ 原戰情室 + Prompt 注入

import os
import re
import json
import hashlib
from collections import Counter
from urllib.parse import urlparse

import streamlit as st
import pandas as pd
import plotly.express as px

# ---- 可選：requests / bs4（深度解析用）----
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


# =========================
# 0) 基本設定
# =========================
st.set_page_config(page_title="全台招生 GEO/AI 戰情室", layout="wide")

CACHE_DIR = "serp_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
}

FAQ_HINTS = ["常見問題", "FAQ", "問答", "Q&A", "QA", "問題"]
SELF_BRAND_TOKENS = ["中華醫事", "華醫", "中華醫事科技大學"]


# =========================
# 1) 工具函數
# =========================
def safe_str(x, default="無"):
    if x is None:
        return default
    s = str(x)
    return s if s.strip() else default

def clip_text(s, n=180):
    s = safe_str(s, "")
    return (s[:n] + "…") if len(s) > n else s

def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def _dedup_keep_order(items, max_n=10):
    seen = set()
    out = []
    for x in items:
        x = str(x).strip()
        if not x or x in seen:
            continue
        out.append(x)
        seen.add(x)
        if len(out) >= max_n:
            break
    return out

def _to_int_safe(s):
    try:
        return int(s)
    except Exception:
        return None

def _to_float_safe(s):
    try:
        return float(s)
    except Exception:
        return 0.0

def prefer_volume_col(scope_df: pd.DataFrame) -> str:
    """優先用 Trends_Score（新版主要指標），沒有再 fallback Search_Volume"""
    if "Trends_Score" in scope_df.columns and scope_df["Trends_Score"].sum() > 0:
        return "Trends_Score"
    return "Search_Volume"

def source_tag(s: str) -> str:
    s = safe_str(s, "無").lower()
    if s == "autocomplete":
        return "🧠 Autocomplete"
    if s == "trends_related":
        return "📈 Trends"
    if s == "serp_mined":
        return "⛏️ SERP挖詞"
    if s == "competitor_compare":
        return "⚔️ 競品比較"
    if s == "base_template":
        return "🧩 保底模板"
    if s == "無":
        return "—"
    return s


# =========================
# 2) 可選外部真實數據（不用也能跑）
#    你未來若有 GA4/表單/活動數據，放同資料夾就會自動吃進來
# =========================
# funnel_data.csv 建議欄位（任選）：Department, Exposure, Click, Lead, Visit, Enroll
FUNNEL_FILE = "funnel_data.csv"
# gsc_queries.csv 建議欄位（任選）：Department, Query, Impressions, Clicks, Position
GSC_FILE = "gsc_queries.csv"

def load_optional_csv(path: str):
    if os.path.exists(path):
        try:
            return pd.read_csv(path)
        except Exception:
            return None
    return None

funnel_df = load_optional_csv(FUNNEL_FILE)
gsc_df = load_optional_csv(GSC_FILE)


# =========================
# 3) 深度解析（可選）：抓 Top3 頁面，挖「數字線索」與「結構」
# =========================
def cache_key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()

def load_cached_page(url: str):
    fp = os.path.join(CACHE_DIR, cache_key(url) + ".json")
    if os.path.exists(fp):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_cached_page(url: str, data: dict):
    fp = os.path.join(CACHE_DIR, cache_key(url) + ".json")
    try:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def fetch_html(url: str, timeout=10) -> str:
    if not HAS_REQUESTS:
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        ct = (r.headers.get("Content-Type") or "").lower()
        if r.status_code >= 400:
            return ""
        if "text/html" not in ct and "application/xhtml" not in ct:
            return ""
        return r.text or ""
    except Exception:
        return ""

NUM_PATTERN = r"\d+(?:\.\d+)?%?"
MONEY_PATTERN = r"(\d+(?:\.\d+)?)(\s*萬|\s*元|\s*[kK])"
RANGE_PATTERN = r"(\d+(?:\.\d+)?)[\s]*[~～\-–—][\s]*(\d+(?:\.\d+)?)"

KW_SALARY = ["薪", "薪資", "月薪", "年薪", "起薪", "待遇", "元", "萬", "k", "K"]
KW_SCORE = ["分數", "級分", "錄取", "門檻", "最低", "統測", "繁星", "甄選", "落點", "PR", "倍率", "級距"]
KW_CREDITS = ["學分", "必修", "選修", "總學分", "畢業學分", "課程地圖", "課表"]
KW_PASS = ["及格", "通過", "合格", "及格率", "通過率", "合格率", "錄取率", "國考", "證照", "考科"]

def classify_number_clues(text: str) -> dict:
    clues = {"salary": [], "score": [], "credits": [], "passrate": []}
    if not text:
        return clues
    t = text.replace("％", "%")

    for m in re.finditer(NUM_PATTERN, t):
        val = m.group(0)
        s = max(0, m.start() - 26)
        e = min(len(t), m.end() + 26)
        ctx = t[s:e].strip()
        if len(ctx) > 95:
            ctx = ctx[:95] + "…"

        if ("%" in val or "%" in ctx) and any(k in ctx for k in KW_PASS):
            clues["passrate"].append(ctx)
            continue
        if any(k in ctx for k in KW_CREDITS) or ("學分" in ctx):
            clues["credits"].append(ctx)
            continue
        if any(k in ctx for k in KW_SALARY):
            clues["salary"].append(ctx)
            continue
        if any(k in ctx for k in KW_SCORE):
            clues["score"].append(ctx)
            continue

    for k in clues:
        clues[k] = _dedup_keep_order(clues[k], max_n=12)
    return clues

def _normalize_money(num_str, unit):
    try:
        x = float(num_str)
    except Exception:
        return None
    u = unit.lower()
    if "萬" in u:
        return int(x * 10000)
    if "k" in u:
        return int(x * 1000)
    if "元" in u:
        return int(x)
    return None

def summarize_salary(clues_salary: list) -> dict:
    if not clues_salary:
        return {"found": False, "type": "無", "range": None, "points": [], "note": ""}

    types = {"月薪": 0, "年薪": 0, "起薪": 0}
    ranges = []
    points = []

    for ctx in clues_salary[:12]:
        points.append(ctx)
        for t in types:
            if t in ctx:
                types[t] += 1

        rm = re.search(RANGE_PATTERN, ctx)
        if rm and any(k in ctx for k in ["萬", "元", "k", "K", "薪", "月薪", "年薪", "起薪"]):
            a, b = rm.group(1), rm.group(2)
            unit = "元" if "元" in ctx else ("萬" if "萬" in ctx else ("k" if ("k" in ctx or "K" in ctx) else "元"))
            va = _normalize_money(a, unit)
            vb = _normalize_money(b, unit)
            if va and vb:
                lo, hi = min(va, vb), max(va, vb)
                if 15000 <= lo <= 200000 and 15000 <= hi <= 200000:
                    ranges.append((lo, hi, ctx))

    best_type = max(types, key=lambda k: types[k])
    if types[best_type] == 0:
        best_type = "薪資"

    summary_range = None
    if ranges:
        lo, hi, _ = ranges[0]
        summary_range = (lo, hi)

    return {
        "found": True,
        "type": best_type,
        "range": summary_range,
        "points": _dedup_keep_order(points, max_n=6),
        "note": "用『區間 + 年資/職務』寫法最像人，也最不容易被質疑。"
    }

def summarize_score(clues_score: list) -> dict:
    if not clues_score:
        return {"found": False, "points": [], "note": ""}
    points = _dedup_keep_order(clues_score, max_n=6)
    return {
        "found": True,
        "points": points,
        "note": "門檻會浮動，最穩的寫法是『近 2–3 年區間』＋標註入學管道＋引用官方簡章。"
    }

def summarize_credits(clues_credits: list) -> dict:
    if not clues_credits:
        return {"found": False, "total": None, "required": None, "elective": None, "points": [], "note": ""}

    text = " ".join(clues_credits[:10])
    total = required = elective = None
    m_total = re.search(r"(總學分|畢業學分)[^\d]{0,6}(\d{2,3})", text)
    if m_total:
        total = _to_int_safe(m_total.group(2))
    m_req = re.search(r"(必修)[^\d]{0,6}(\d{2,3})", text)
    if m_req:
        required = _to_int_safe(m_req.group(2))
    m_ele = re.search(r"(選修)[^\d]{0,6}(\d{2,3})", text)
    if m_ele:
        elective = _to_int_safe(m_ele.group(2))

    return {
        "found": True,
        "total": total,
        "required": required,
        "elective": elective,
        "points": _dedup_keep_order(clues_credits, max_n=6),
        "note": "學分/課程用『課程地圖 + 表格』呈現最有效，並標註來源（系網/課程系統）。"
    }

def summarize_passrate(clues_pass: list) -> dict:
    if not clues_pass:
        return {"found": False, "rates": [], "points": [], "note": ""}
    points = _dedup_keep_order(clues_pass, max_n=6)
    rates = []
    for ctx in points:
        for p in re.findall(r"\d+(?:\.\d+)?%", ctx):
            rates.append(p)
    rates = _dedup_keep_order(rates, max_n=6)
    return {
        "found": True,
        "rates": rates,
        "points": points,
        "note": "通過率/及格率要交代『年份、口徑、母數』並標註來源（考選部/校方公開成果）。"
    }

def humanize_number_output(agg_clues: dict) -> dict:
    return {
        "salary": summarize_salary(agg_clues.get("salary", [])),
        "score": summarize_score(agg_clues.get("score", [])),
        "credits": summarize_credits(agg_clues.get("credits", [])),
        "passrate": summarize_passrate(agg_clues.get("passrate", [])),
    }

def build_rational_citation_paragraphs(human: dict) -> str:
    paras = []

    sal = human.get("salary", {})
    if sal.get("found"):
        r = sal.get("range")
        if r:
            lo, hi = r
            lo_w = round(lo / 10000, 1)
            hi_w = round(hi / 10000, 1)
            line = f"薪資不要寫成單點：比較像人會寫的方式是『區間』，大概 **{lo_w}～{hi_w} 萬/月**（依地區、班別、職務而動）。"
        else:
            line = "薪資建議用『區間 + 年資/職務』描述，避免單一數字造成誤解。"

        paras.append(
            "### 薪資（建議引用段落）\n"
            f"{line}\n"
            "- **引用建議**：104 職缺薪資區間、醫院/機構徵才公告（註明年份/職務）。"
        )

    sc = human.get("score", {})
    if sc.get("found"):
        paras.append(
            "### 分數/門檻（建議引用段落）\n"
            "錄取門檻每年會動，最穩的寫法是：**整理近 2–3 年區間**，並標註『入學管道』（統測分發/甄選/繁星）。\n"
            "- **引用建議**：官方招生簡章、分發/甄選入學公告。"
        )

    cr = human.get("credits", {})
    if cr.get("found"):
        t = cr.get("total")
        req = cr.get("required")
        ele = cr.get("elective")
        rows = []
        if t: rows.append(f"- 畢業總學分：{t}")
        if req: rows.append(f"- 必修：{req}")
        if ele: rows.append(f"- 選修：{ele}")
        detail = "\n".join(rows) if rows else "- 建議直接貼『學分結構表 + 課程地圖』，讀者會更安心。"

        paras.append(
            "### 學分/課程（建議引用段落）\n"
            "課程資訊用表格最清楚：把『學分結構』＋『年級學習路徑』講清楚。\n"
            f"{detail}\n"
            "- **引用建議**：系網課程規劃、課程查詢系統、招生簡章附錄。"
        )

    pr = human.get("passrate", {})
    if pr.get("found"):
        rates = pr.get("rates") or []
        rate_line = "片段出現的 % 包含：" + "、".join(rates) + "（仍需核對年份與口徑）。" if rates else \
                    "若要寫通過率/及格率，務必補齊年份與來源，否則容易被質疑。"

        paras.append(
            "### 國考/證照通過率（建議引用段落）\n"
            f"{rate_line}\n"
            "- **引用建議**：考選部/官方公告、校方公開成果（附年份/母數）。"
        )

    if not paras:
        return (
            "### 建議引用段落（通用）\n"
            "如果 Top3 缺少可查證數據，建議用『官方來源 + 表格整理 + FAQ』補齊，文章更容易被 AI 摘錄。"
        )

    return "\n\n".join(paras)

@st.cache_data(show_spinner=False)
def parse_competitor_page(url: str) -> dict:
    cached = load_cached_page(url)
    if cached:
        return cached

    html = fetch_html(url)
    if not html:
        data = {"url": url, "ok": 0, "reason": "fetch_failed"}
        save_cached_page(url, data)
        return data

    # 沒 bs4 → 退化版
    if not HAS_BS4:
        text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        has_faq = 1 if any(h.lower() in text.lower() for h in FAQ_HINTS) else 0
        number_clues = classify_number_clues(text)

        data = {
            "url": url, "ok": 1,
            "title": "", "meta_desc": "",
            "h1": "", "h2": [], "h3": [],
            "has_table": 0,
            "has_list": 0,
            "has_faq": has_faq,
            "number_clues": number_clues,
            "bullets": [],
            "text_preview": text[:900],
        }
        save_cached_page(url, data)
        return data

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": "description"})
    meta_desc = meta.get("content", "").strip() if meta else ""

    h1_tag = soup.find("h1")
    h1 = h1_tag.get_text(" ", strip=True) if h1_tag else ""
    h2 = [x.get_text(" ", strip=True) for x in soup.find_all("h2")][:25]
    h3 = [x.get_text(" ", strip=True) for x in soup.find_all("h3")][:25]

    has_table = 1 if soup.find("table") else 0
    has_list = 1 if soup.find(["ul", "ol"]) else 0

    text = soup.get_text(" ", strip=True)
    has_faq = 1 if any(h in text for h in FAQ_HINTS) else 0

    bullets = []
    for ul in soup.find_all(["ul", "ol"])[:3]:
        for li in ul.find_all("li")[:8]:
            t = li.get_text(" ", strip=True)
            if 8 <= len(t) <= 90:
                bullets.append(t)
    bullets = _dedup_keep_order(bullets, max_n=14)

    number_clues = classify_number_clues(text)

    data = {
        "url": url, "ok": 1,
        "title": title,
        "meta_desc": meta_desc,
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "has_table": has_table,
        "has_list": has_list,
        "has_faq": has_faq,
        "number_clues": number_clues,
        "bullets": bullets,
        "text_preview": text[:900],
    }
    save_cached_page(url, data)
    return data


# =========================
# 4) 讀取 school_data.csv（對齊新版 powergeo.py）
# =========================
try:
    df = pd.read_csv("school_data.csv")
except FileNotFoundError:
    st.error("❌ 找不到 school_data.csv，請先執行 powergeo.py 產生資料。")
    st.stop()

TEXT_DEFAULTS = {
    "College": "無",
    "Department": "無",
    "Keyword": "無",
    "Keyword_Source": "無",
    "Seed_Term": "無",
    "Evidence": "無",
    "Keyword_Type": "一般",
    "Strategy_Tag": "無",
    "Rank1_Title": "無", "Rank1_Link": "#", "Rank1_Snippet": "",
    "Rank2_Title": "無", "Rank2_Link": "#", "Rank2_Snippet": "",
    "Rank3_Title": "無", "Rank3_Link": "#", "Rank3_Snippet": "",
}

NUM_DEFAULTS = {
    "Trends_Score": 0.0,
    "Trends_Fetched": 0,
    "Search_Volume": 0,
    "Opportunity_Score": 0.0,
    "AI_Potential": 0,
    "Authority_Count": 0,
    "Forum_Count": 0,
    "Answerable_Avg": 0.0,
    "Citable_Score": 0.0,
    "Fetch_OK_Count": 0,
    "Schema_Hit_Count": 0,
    "Has_FAQ": 0,
    "Has_Table": 0,
    "Has_List": 0,
    "Has_Headings": 0,
    "Page_Word_Count_Max": 0,
    "Result_Count": 0,
}

for c, v in TEXT_DEFAULTS.items():
    if c not in df.columns:
        df[c] = v

for c, v in NUM_DEFAULTS.items():
    if c not in df.columns:
        df[c] = v

for c in TEXT_DEFAULTS.keys():
    df[c] = df[c].fillna(TEXT_DEFAULTS[c]).astype(str)

for c in NUM_DEFAULTS.keys():
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(NUM_DEFAULTS[c])

df = df.sort_values(["College", "Department", "Opportunity_Score"], ascending=[True, True, False])


# =========================
# 5) 從 SERP Title 抽「學校名」→ 競品Top5
# =========================
SCHOOL_SUFFIX = r"(?:大學|科技大學|醫學院|學院|專科學校|護理健康大學|護理專科學校|醫護管理專科學校|護專|醫專)"
SCHOOL_REGEX = re.compile(rf"([\u4e00-\u9fff]{{2,12}}{SCHOOL_SUFFIX})")

def extract_school_names(text: str):
    if not text:
        return []
    found = SCHOOL_REGEX.findall(text)
    out = []
    for f in found:
        f = f.strip()
        if not f:
            continue
        # 排除自己
        if any(t in f for t in SELF_BRAND_TOKENS):
            continue
        out.append(f)
    return out

def competitor_top5_from_dept(dept_df: pd.DataFrame):
    counter = Counter()
    examples = {}

    for _, r in dept_df.iterrows():
        for i in range(1, 4):
            t = safe_str(r.get(f"Rank{i}_Title", ""))
            link = safe_str(r.get(f"Rank{i}_Link", "#"))
            d = domain_of(link)

            for name in extract_school_names(t):
                counter[name] += 2
                examples.setdefault(name, []).append(t)

            # domain 也算競品線索（沒抓到校名時）
            if d and d not in ["#", ""]:
                counter[d] += 1
                examples.setdefault(d, []).append(t)

    # 把明顯不是競品的 domain 先壓掉
    noise_domains = ["dcard.tw", "ptt.cc", "facebook.com", "youtube.com", "104.com.tw", "instagram.com"]
    for nd in noise_domains:
        for k in list(counter.keys()):
            if nd in k:
                counter[k] -= 2

    items = []
    for name, cnt in counter.most_common(20):
        if cnt <= 0:
            continue
        # 排除本校字樣
        if any(t in name for t in SELF_BRAND_TOKENS):
            continue
        items.append({
            "Competitor": name,
            "Mentions": int(cnt),
            "Example_Title": clip_text(examples.get(name, [""])[0], 90)
        })

    # 只取 Top5（避免太雜）
    return items[:5]


# =========================
# 6) 學生決策問題 Top10（從 Keyword/Evidence 來）
#    目的：系主任要看到「學生為什麼選/不選」的原文問題類型
# =========================
CAT_RULES = {
    "薪資": ["薪", "薪資", "月薪", "年薪", "起薪", "待遇", "多少錢", "幾萬", "k", "K"],
    "分數": ["分數", "級分", "錄取", "門檻", "最低", "統測", "繁星", "甄選", "落點", "倍率", "PR"],
    "學分": ["學分", "課程", "課表", "必修", "選修", "畢業學分", "課程地圖"],
    "及格率": ["及格率", "通過率", "合格率", "國考", "證照", "考科", "通過", "及格", "合格"],
    "實習": ["實習", "醫院", "機構", "臨床", "見習", "輪訓"],
    "出路": ["出路", "工作內容", "好找工作", "就業", "職務", "能做什麼", "職涯"],
    "生活": ["宿舍", "租屋", "交通", "通勤", "學費", "獎學金", "打工", "生活費"],
    "社群疑慮": ["dcard", "ptt", "靠北", "心得", "評價", "很累", "爆肝", "後悔", "雷"],
}

QUESTION_TOKENS = ["嗎", "怎麼", "如何", "要不要", "值得", "好不好", "難不難", "會不會", "適合", "可以"]

def categorize_question(q: str):
    ql = q.lower()
    for cat, keys in CAT_RULES.items():
        if any(k.lower() in ql for k in keys):
            return cat
    return "其他"

def looks_like_question(q: str):
    if any(tok in q for tok in QUESTION_TOKENS):
        return True
    # 也把「X 分數」「X 薪水」這種算問題（決策型）
    if any(k in q for k in ["分數", "門檻", "錄取", "薪水", "起薪", "年薪", "國考", "及格率", "學分", "實習"]):
        return True
    return False

def decision_questions_top10(dept_df: pd.DataFrame):
    """
    優先用 Keyword_Source=autocomplete，因為最像真人輸入；再補其他來源
    """
    qs = []

    ac = dept_df[dept_df["Keyword_Source"].str.lower() == "autocomplete"]
    other = dept_df[dept_df["Keyword_Source"].str.lower() != "autocomplete"]

    for _, r in pd.concat([ac, other], axis=0).iterrows():
        kw = safe_str(r["Keyword"])
        if looks_like_question(kw):
            qs.append(kw)

    # 頻率
    counter = Counter([q.strip() for q in qs if q.strip()])
    top = counter.most_common(30)

    # 做 category 彙整 + 每類挑代表句
    cat_counter = Counter()
    cat_examples = {}
    for q, cnt in top:
        cat = categorize_question(q)
        cat_counter[cat] += cnt
        cat_examples.setdefault(cat, []).append(q)

    # Top10 問題（原句）
    top10 = [{"Question": q, "Count": int(cnt), "Category": categorize_question(q)} for q, cnt in counter.most_common(10)]

    # 分類表
    cat_rows = []
    total = sum(cat_counter.values()) if cat_counter else 0
    for cat, cnt in cat_counter.most_common(10):
        ex = cat_examples.get(cat, [])
        cat_rows.append({
            "Category": cat,
            "Share": round((cnt / total) * 100, 1) if total else 0.0,
            "Example": clip_text(ex[0], 80) if ex else "—"
        })

    return top10, cat_rows


# =========================
# 7) 內容缺口 + 下月行動清單（讓系主任能做事）
# =========================
def content_gap_suggestions(dept_df: pd.DataFrame):
    """
    用你現有欄位先做『可行動』缺口；若有深度解析，還會再加強
    """
    # 用平均值看整體弱點
    faq_rate = dept_df["Has_FAQ"].mean() if len(dept_df) else 0
    table_rate = dept_df["Has_Table"].mean() if len(dept_df) else 0
    list_rate = dept_df["Has_List"].mean() if len(dept_df) else 0
    authority = dept_df["Authority_Count"].mean() if len(dept_df) else 0
    forum = dept_df["Forum_Count"].mean() if len(dept_df) else 0
    citable = dept_df["Citable_Score"].mean() if len(dept_df) else 0

    gaps = []

    # 結構化缺口
    if faq_rate < 0.4:
        gaps.append("FAQ 沒做滿：補一段『常見問題 8–12 題』，每題 2–4 行，AI 很愛摘。")
    if table_rate < 0.35:
        gaps.append("缺少表格：至少做 1 張『課程/實習/證照/出路』整理表或對照表。")
    if list_rate < 0.5:
        gaps.append("缺少步驟化清單：把『如何準備/如何實習/如何考照』寫成 6–10 步驟。")

    # 引用缺口
    if citable < 45 or authority < 0.8:
        gaps.append("引用不足：涉及薪資/門檻/通過率，務必附『年份+來源類型』（官方/104/招生簡章）。")

    # 社群風險
    if forum >= 0.7:
        gaps.append("論壇占比偏高：加一段『理性澄清』，把主觀抱怨轉成可查資訊（流程/口徑/FAQ）。")

    # 決策四大硬題（永遠要有）
    must_have = [
        "薪資：用『區間 + 職務/年資』寫法，不要單一數字。",
        "門檻：整理『近 2–3 年區間』＋入學管道＋引用簡章。",
        "學分：貼『學分結構表 + 課程地圖』。",
        "及格率/考照：交代『年份、口徑、母數』並附來源。"
    ]
    gaps.extend(must_have)

    return _dedup_keep_order(gaps, max_n=10)

def next_30_days_action_plan(dept_df: pd.DataFrame, top_questions: list, top_competitors: list):
    """
    用規則產生系主任看得懂的行動清單（你不用先有 GA4 也能先跑）
    """
    actions = []

    # 1) 直接對應學生最常問
    cats = Counter([x.get("Category") for x in top_questions])
    top_cat = cats.most_common(1)[0][0] if cats else "其他"

    if top_cat in ["薪資", "分數", "學分", "及格率"]:
        actions.append(f"做一篇『{top_cat} 一次講清楚』：用表格整理 + 在文中交代年份/來源口徑。")
    else:
        actions.append("做一篇『新生懶人包』：課程地圖、實習流程、證照/出路、FAQ 一次到位。")

    # 2) 競品對照
    if top_competitors:
        actions.append("做一張『本系 vs 主要競品』對照表（課程/實習/證照/出路/資源），放在文章前半段。")

    # 3) FAQ/可摘錄
    actions.append("補 FAQ 12 題：直接用學生的原句改寫，答案控制 2–4 行，方便 AI 摘錄。")

    # 4) 引用資料盤點
    actions.append("盤點可引用資料清單：招生簡章（門檻/管道）、課程地圖（學分）、實習單位、證照/國考成果、就業/薪資佐證。")

    # 5) 社群風險處理
    if dept_df["Forum_Count"].mean() >= 0.7:
        actions.append("加『理性澄清』段：針對 Dcard/PTT 常見焦慮（累不累/好不好考/值不值得）逐點回答。")

    return _dedup_keep_order(actions, max_n=6)

def build_onepager_markdown(dept_name: str, snapshot: dict, comp_items: list, cat_rows: list, top10_q: list, gaps: list, actions: list):
    md = []
    md.append(f"# {dept_name}｜系主任一頁式（招生決策依據）")
    md.append("")
    md.append("## 1) 招生快照")
    md.append(f"- 關鍵字筆數：{snapshot.get('n',0)}")
    md.append(f"- 平均 Opportunity：{snapshot.get('opp',0)}｜平均 AI：{snapshot.get('ai',0)}｜平均 Citable：{snapshot.get('citable',0)}")
    md.append(f"- 平均聲量指標：{snapshot.get('vol_label','')} = {snapshot.get('vol',0)}")
    md.append("")
    md.append("## 2) 主要競品 Top5（來自 Top3 SERP 標題/網域）")
    for x in comp_items:
        md.append(f"- {x['Competitor']}（提及 {x['Mentions']}）例：{x['Example_Title']}")
    md.append("")
    md.append("## 3) 學生決策問題（分類）")
    for r in cat_rows:
        md.append(f"- {r['Category']}：{r['Share']}%｜例：{r['Example']}")
    md.append("")
    md.append("## 4) Top10 原句問題（最像學生真的會問的）")
    for q in top10_q:
        md.append(f"- [{q['Category']}] {q['Question']}（{q['Count']}）")
    md.append("")
    md.append("## 5) 內容缺口（現在網路上容易缺的）")
    for g in gaps:
        md.append(f"- {g}")
    md.append("")
    md.append("## 6) 下月行動清單（30 天內做得完）")
    for a in actions:
        md.append(f"- {a}")
    md.append("")
    return "\n".join(md)


# =========================
# 8) Sidebar：篩選與模式
# =========================
st.sidebar.title("🏫 全台招生 GEO/AI 戰情室")

mode = st.sidebar.radio(
    "選擇視角",
    ["📌 系主任一頁式", "🧭 全校/學院總覽", "🔍 單系戰情室（Top3+Prompt）"],
    index=0
)

college_list = ["全部學院"] + sorted(df["College"].unique().tolist())
selected_college = st.sidebar.selectbox("STEP 1: 選擇學院", college_list)

if selected_college == "全部學院":
    dept_options = sorted(df["Department"].unique().tolist())
else:
    dept_options = sorted(df[df["College"] == selected_college]["Department"].unique().tolist())

selected_dept = st.sidebar.selectbox("STEP 2: 選擇科系", dept_options)

kw_types = ["全部意圖"] + sorted(df["Keyword_Type"].unique().tolist())
selected_kw_type = st.sidebar.selectbox("STEP 3: 篩選搜尋意圖", kw_types)

source_list = ["全部來源"] + sorted(df["Keyword_Source"].unique().tolist())
selected_source = st.sidebar.selectbox("STEP 4: 篩選 Keyword 來源", source_list)

min_ai = st.sidebar.slider("AI_Potential 最低門檻", 0, 100, 0, 5)
min_opp_max = int(max(1, df["Opportunity_Score"].max()))
min_opp = st.sidebar.slider("Opportunity_Score 最低門檻", 0, min_opp_max, 0, 10)

st.sidebar.divider()
st.sidebar.caption("✅ 想看最像真人輸入：來源選 Autocomplete。")

if funnel_df is None:
    st.sidebar.caption("（可選）放入 funnel_data.csv 可顯示漏斗轉換。")
if gsc_df is None:
    st.sidebar.caption("（可選）放入 gsc_queries.csv 可顯示 Search Console 真實 query。")


# 套用篩選
target_df = df.copy()
if selected_college != "全部學院":
    target_df = target_df[target_df["College"] == selected_college]

if selected_kw_type != "全部意圖":
    target_df = target_df[target_df["Keyword_Type"] == selected_kw_type]

if selected_source != "全部來源":
    target_df = target_df[target_df["Keyword_Source"] == selected_source]

target_df = target_df[target_df["AI_Potential"] >= min_ai]
target_df = target_df[target_df["Opportunity_Score"] >= min_opp]


# =========================
# 9) 全校/學院總覽
# =========================
def overview_page(scope_df: pd.DataFrame, title_prefix: str):
    st.title(f"🧭 {title_prefix}｜總覽（GEO/AI 指標 + 來源結構）")

    vcol = prefer_volume_col(scope_df)
    vlabel = "Trends 相對聲量" if vcol == "Trends_Score" else "聲量指標"

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("關鍵字筆數", int(len(scope_df)))
    with c2: st.metric("平均 Opportunity", round(scope_df["Opportunity_Score"].mean(), 1) if len(scope_df) else 0)
    with c3: st.metric("平均 AI", round(scope_df["AI_Potential"].mean(), 1) if len(scope_df) else 0)
    with c4: st.metric("平均 Citable", round(scope_df["Citable_Score"].mean(), 1) if len(scope_df) else 0)
    with c5: st.metric(f"平均 {vlabel}", round(scope_df[vcol].mean(), 2) if len(scope_df) else 0)

    st.divider()

    left, right = st.columns([2, 1])
    with left:
        dept_rank = (
            scope_df.groupby("Department", as_index=False)["Opportunity_Score"]
            .mean()
            .sort_values("Opportunity_Score", ascending=False)
        )
        fig = px.bar(dept_rank, x="Department", y="Opportunity_Score", color="Department",
                     title="各系 GEO 機會值排行（平均 Opportunity）")
        st.plotly_chart(fig, use_container_width=True)

    with right:
        fig2 = px.pie(scope_df, names="Keyword_Type", title="搜尋意圖分佈")
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    colA, colB = st.columns(2)
    with colA:
        src_rank = (
            scope_df.groupby("Keyword_Source", as_index=False)
            .size()
            .rename(columns={"size": "Count"})
            .sort_values("Count", ascending=False)
        )
        fig3 = px.bar(src_rank, x="Keyword_Source", y="Count", color="Keyword_Source",
                      title="Keyword 來源分佈（越多 autocomplete 越像真人）")
        st.plotly_chart(fig3, use_container_width=True)

    with colB:
        vol_rank = (
            scope_df.groupby("Department", as_index=False)[vcol]
            .mean()
            .sort_values(vcol, ascending=False)
        )
        fig4 = px.bar(vol_rank, x="Department", y=vcol, color="Department",
                      title=f"各系 {vlabel}（平均）")
        st.plotly_chart(fig4, use_container_width=True)

    st.divider()
    st.subheader("📋 關鍵字總表（含來源與證據）")

    show_cols = [
        "College","Department","Keyword","Keyword_Source","Seed_Term",
        "Keyword_Type","Opportunity_Score","AI_Potential","Citable_Score",
        "Authority_Count","Forum_Count", vcol, "Trends_Fetched", "Rank1_Title"
    ]
    show_cols = [c for c in show_cols if c in scope_df.columns]

    st.dataframe(
        scope_df[show_cols].sort_values(["Opportunity_Score","AI_Potential"], ascending=False),
        use_container_width=True,
        height=640
    )


# =========================
# 10) 系主任一頁式
# =========================
def onepager_page(scope_df: pd.DataFrame, dept_name: str):
    dept_df = scope_df[scope_df["Department"] == dept_name].copy()
    if dept_df.empty:
        st.warning("這個篩選條件下沒有資料（可把門檻調低或取消來源/意圖篩選）。")
        st.stop()

    dept_df = dept_df.sort_values(["Opportunity_Score","AI_Potential"], ascending=False)
    vcol = prefer_volume_col(dept_df)
    vlabel = "Trends 相對聲量" if vcol == "Trends_Score" else "聲量指標"

    st.title(f"📌 {dept_name}｜系主任一頁式（用『真實決策依據』說服）")

    # 快照 KPI（沒有漏斗也能先跑）
    snap = {
        "n": int(len(dept_df)),
        "opp": round(dept_df["Opportunity_Score"].mean(), 1),
        "ai": round(dept_df["AI_Potential"].mean(), 1),
        "citable": round(dept_df["Citable_Score"].mean(), 1),
        "vol": round(dept_df[vcol].mean(), 2),
        "vol_label": vlabel
    }

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("關鍵字筆數", snap["n"])
    c2.metric("平均 Opportunity", snap["opp"])
    c3.metric("平均 AI", snap["ai"])
    c4.metric("平均 Citable", snap["citable"])
    c5.metric(f"平均 {vlabel}", snap["vol"])

    # 可選：漏斗資料
    if funnel_df is not None and "Department" in funnel_df.columns:
        fd = funnel_df[funnel_df["Department"] == dept_name]
        if not fd.empty:
            st.divider()
            st.subheader("🧪 申請漏斗（可選：來自 funnel_data.csv）")
            row = fd.iloc[0].to_dict()
            steps = ["Exposure", "Click", "Lead", "Visit", "Enroll"]
            cols = st.columns(len(steps))
            vals = []
            for i, s in enumerate(steps):
                v = row.get(s, None)
                vals.append(v)
                cols[i].metric(s, int(v) if pd.notna(v) else 0)
            # 轉換率
            try:
                exp = float(row.get("Exposure", 0) or 0)
                lead = float(row.get("Lead", 0) or 0)
                visit = float(row.get("Visit", 0) or 0)
                enroll = float(row.get("Enroll", 0) or 0)
                st.caption(f"粗轉換：曝光→留資 {lead/max(1,exp):.1%}｜留資→到訪 {visit/max(1,lead):.1%}｜到訪→報到 {enroll/max(1,visit):.1%}")
            except Exception:
                pass

    # 可選：GSC 真實 query
    if gsc_df is not None and "Department" in gsc_df.columns:
        gd = gsc_df[gsc_df["Department"] == dept_name]
        if not gd.empty:
            st.divider()
            st.subheader("🔎 Search Console 真實 Query（可選：來自 gsc_queries.csv）")
            show = gd.copy()
            for col in ["Impressions", "Clicks", "Position"]:
                if col in show.columns:
                    show[col] = pd.to_numeric(show[col], errors="coerce").fillna(0)
            st.dataframe(show.sort_values("Impressions", ascending=False).head(20), use_container_width=True, height=360)

    # 競品 Top5
    st.divider()
    st.subheader("🏫 主要競品 Top5（從 Top3 SERP 標題/網域推估）")
    comp_top5 = competitor_top5_from_dept(dept_df)
    if comp_top5:
        st.dataframe(pd.DataFrame(comp_top5), use_container_width=True, height=220)
    else:
        st.info("目前抓到的 SERP 資訊不足以推估競品（可降低篩選門檻或讓 powergeo 多抓一些 keyword）。")

    # 決策問題 Top10 + 分類
    st.divider()
    st.subheader("🧠 學生決策依據：他們其實在問什麼？")
    top10_q, cat_rows = decision_questions_top10(dept_df)

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("**Top10 原句問題（最像真人）**")
        if top10_q:
            st.dataframe(pd.DataFrame(top10_q), use_container_width=True, height=320)
        else:
            st.caption("（沒有明顯問句，建議來源篩 Autocomplete 或把門檻調低）")

    with right:
        st.markdown("**分類占比（系主任看這個就懂學生在意什麼）**")
        if cat_rows:
            fig = px.bar(pd.DataFrame(cat_rows), x="Category", y="Share", color="Category", title="決策問題占比（%）")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(pd.DataFrame(cat_rows), use_container_width=True, height=220)
        else:
            st.caption("（尚無分類結果）")

    # 內容缺口
    st.divider()
    st.subheader("🧩 內容缺口（現在網路上常缺、但學生很在意）")
    gaps = content_gap_suggestions(dept_df)
    for g in gaps:
        st.write(f"- {g}")

    # 下月行動清單
    st.divider()
    st.subheader("✅ 下月行動清單（30 天內做得完）")
    actions = next_30_days_action_plan(dept_df, top10_q, comp_top5)
    for a in actions:
        st.write(f"- {a}")

    # 一鍵匯出給系主任（Markdown）
    st.divider()
    st.subheader("📤 匯出（給系主任/簡報用）")
    md = build_onepager_markdown(dept_name, snap, comp_top5, cat_rows, top10_q, gaps, actions)
    st.download_button(
        label="下載系主任一頁式（Markdown）",
        data=md.encode("utf-8"),
        file_name=f"{dept_name}_系主任一頁式.md",
        mime="text/markdown"
    )
    with st.expander("預覽 Markdown", expanded=False):
        st.code(md, language="markdown")


# =========================
# 11) 單系戰情室（Top3 + Evidence + Prompt 注入 + 可選深度解析）
# =========================
def warroom_page(scope_df: pd.DataFrame, dept_name: str):
    dept_df = scope_df[scope_df["Department"] == dept_name].copy()
    if dept_df.empty:
        st.warning("這個篩選條件下沒有資料（可把門檻調低或取消來源/意圖篩選）。")
        st.stop()

    dept_df = dept_df.sort_values(["Opportunity_Score","AI_Potential"], ascending=False)
    vcol = prefer_volume_col(dept_df)
    vlabel = "Trends 相對聲量" if vcol == "Trends_Score" else "聲量指標"

    st.title(f"🔍 {dept_name}｜單系戰情室（Top3 + Prompt）")

    # 選 keyword
    dept_df["Display_Label"] = (
        dept_df["Keyword"] + " 〔" +
        dept_df["Keyword_Type"] + " / " +
        dept_df["Keyword_Source"].apply(source_tag) + "〕"
    )
    target_label = st.selectbox("選擇關鍵字", dept_df["Display_Label"].unique())
    target_row = dept_df[dept_df["Display_Label"] == target_label].iloc[0]

    kw = safe_str(target_row["Keyword"])
    kw_type = safe_str(target_row["Keyword_Type"])
    strategy = safe_str(target_row["Strategy_Tag"])
    src = safe_str(target_row["Keyword_Source"])
    seed = safe_str(target_row["Seed_Term"])
    evidence = safe_str(target_row.get("Evidence", "無"))

    st.caption(f"來源：{source_tag(src)}｜Seed：{seed}｜意圖：{kw_type}")

    if evidence != "無" and evidence.strip():
        with st.expander("🔎 Evidence（為什麼說這不是你編的）", expanded=False):
            st.code(evidence[:800])

    # 深度解析（可選）
    deep_on = False
    run_deep = False
    if HAS_REQUESTS:
        deep_on = st.checkbox("啟用深度解析：抓 Top3 網頁（第一次慢、有快取）", value=False)
        run_deep = st.button("開始深度解析 Top3")
    else:
        st.info("若要深度解析 Top3 網頁：請 pip install requests beautifulsoup4")

    st.divider()

    # 左：指標
    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.metric("Opportunity", round(float(target_row["Opportunity_Score"]), 1))
        st.metric("AI_Potential", int(target_row["AI_Potential"]))
        st.metric("Citable", round(float(target_row["Citable_Score"]), 1))
        st.metric(vlabel, round(float(target_row.get(vcol, 0)), 2))
        st.metric("Authority", int(target_row["Authority_Count"]))
        st.metric("Forum", int(target_row["Forum_Count"]))

        st.caption("結構化線索（越多越容易被 AI 摘錄）")
        s_cols = st.columns(4)
        s_cols[0].metric("FAQ", int(target_row["Has_FAQ"]))
        s_cols[1].metric("Table", int(target_row["Has_Table"]))
        s_cols[2].metric("List", int(target_row["Has_List"]))
        s_cols[3].metric("H2/H3", int(target_row["Has_Headings"]))

        st.info(f"策略：{strategy}")

    # 右：Top3 + 深度解析摘要
    competitor_info_text = ""
    deep_briefs = []
    gap_pool_h2 = []
    agg_number_clues = {"salary": [], "score": [], "credits": [], "passrate": []}

    with col_r:
        st.markdown(f"### 👀 「{kw}」Top 3 搜尋結果")
        for i in range(1, 4):
            title = safe_str(target_row.get(f"Rank{i}_Title", "無"))
            link = safe_str(target_row.get(f"Rank{i}_Link", "#"))
            snippet = safe_str(target_row.get(f"Rank{i}_Snippet", ""))

            if title == "無":
                continue

            competitor_info_text += f"{i}. 標題：{title}\n   摘要：{clip_text(snippet, 140)}\n"

            with st.container(border=True):
                st.markdown(f"**#{i} [{title}]({link})**")
                if snippet.strip():
                    st.caption(clip_text(snippet, 260))

            if deep_on and run_deep and link not in ["#", "無", ""]:
                info = parse_competitor_page(link)
                if info.get("ok") == 1:
                    deep_briefs.append((i, info))
                    gap_pool_h2.extend(info.get("h2", [])[:15])

                    nc = info.get("number_clues", {}) or {}
                    for k in agg_number_clues.keys():
                        agg_number_clues[k].extend(nc.get(k, []))

    # Content Gap + 理性引用段落（來自深度解析）
    gap_suggestions = []
    if deep_briefs:
        top1_h2 = set(deep_briefs[0][1].get("h2", []))
        freq = Counter([h for h in gap_pool_h2 if 4 <= len(h) <= 24])
        for h, _ in freq.most_common(12):
            if h not in top1_h2:
                gap_suggestions.append(h)
        gap_suggestions = gap_suggestions[:8]

    for k in agg_number_clues:
        agg_number_clues[k] = _dedup_keep_order(agg_number_clues[k], max_n=12)

    human = humanize_number_output(agg_number_clues)
    rational_paras = build_rational_citation_paragraphs(human)

    if deep_on and run_deep:
        st.divider()
        st.subheader("📌 深度解析：數字線索（更像人類的理性寫法）")
        with st.container(border=True):
            st.markdown(rational_paras)

        if gap_suggestions:
            st.subheader("🧩 Content Gap（Top1 沒講、但其他人常提）")
            for g in gap_suggestions:
                st.write(f"- {g}")

    # Prompt 生成（注入來源證據 + 理性引用段落）
    st.divider()
    st.subheader("✍️ AI 智能文案生成器（注入來源證據 + 理性引用段落）")

    template_type = st.radio(
        "文章打法",
        ["⚔️ 理性競爭型（對照表 + 缺口補齊）", "🏆 理性權威型（制度/引用優先）", "🤖 AI 友善型（表格+FAQ+可摘錄）"],
        horizontal=True
    )

    if "競爭型" in template_type:
        base_instruction = "主張要可檢核：比較用表格，結論用證據。"
        structure_req = (
            "1) TL;DR（4–6 行）\n"
            "2) 對照表：本校 vs Top1（課程/實習/證照/出路/資源）\n"
            "3) Content Gap 一次補齊（至少 6 點）\n"
            "4) FAQ 8–12 題（短、直接、可摘錄）\n"
        )
    elif "權威型" in template_type:
        base_instruction = "以制度與可查資料建立信任：入學、課程、實習、考照、就業。"
        structure_req = (
            "1) 入學管道與門檻（近 2–3 年區間＋來源）\n"
            "2) 學分結構與課程地圖（表格）\n"
            "3) 實習與考照（流程化）\n"
            "4) 出路與薪資（區間 + 年資/職務）\n"
            "5) FAQ 至少 6 題\n"
        )
    else:
        base_instruction = "寫成 AI 最好摘要的格式：短段落、表格、條列、FAQ，並標示引用來源類型。"
        structure_req = (
            "1) TL;DR（5 行）\n"
            "2) 核心表格（至少 1 張）\n"
            "3) 步驟清單（面試/選課/考照任一）\n"
            "4) FAQ 至少 10 題\n"
        )

    deep_text_for_prompt = ""
    if deep_briefs:
        deep_text_for_prompt += "\n# 🧠 競品深度摘要（你已讀過 Top3 的結構）\n"
        for idx, info in deep_briefs:
            deep_text_for_prompt += (
                f"- #{idx} {domain_of(info['url'])}\n"
                f"  - H1: {safe_str(info.get('h1','無'))}\n"
                f"  - H2: {', '.join(info.get('h2', [])[:10])}\n"
                f"  - Struct: FAQ={info.get('has_faq',0)}, Table={info.get('has_table',0)}, List={info.get('has_list',0)}\n"
            )

    gap_text = ""
    if gap_suggestions:
        gap_text = "\n# 🧩 建議補強內容缺口\n" + "\n".join([f"- {g}" for g in gap_suggestions]) + "\n"

    cite_block = "\n# 📎 建議引用段落（理性版，可直接貼）\n" + rational_paras + "\n"

    final_prompt = f"""
# 角色
你是一位偏理性、重視可查資料與結構化呈現的 SEO + GEO 內容策略顧問。

# 任務
為「{dept_name}」寫一篇要衝排名、也要容易被 AI 摘錄/引用的文章。
目標關鍵字：**{kw}**

# 關鍵字來源（提高可信度，請在文中交代）
- Keyword_Source：{src}
- Seed_Term：{seed}
- Evidence：{evidence}

# 目前 Top3 在講什麼（摘要）
{competitor_info_text}
{deep_text_for_prompt}
{gap_text}
{cite_block}

# 寫作策略
{base_instruction}

# 結構（照做）
{structure_req}
5) 文末加 3 題『大家最常問』Q&A + CTA（系網/參訪/諮詢）

# Constraints
- 用 Markdown（H2/H3 清楚，表格要能快速掃讀）
- 語氣偏理性：避免口號式形容詞，主張要能被檢核
- 涉及數據（薪資/分數/學分/及格率）用『區間』，並交代『年份/來源類型』
"""
    st.text_area("📋 複製 Prompt：", final_prompt, height=680)
    st.success("✅ Prompt 已注入來源證據 + 理性引用段落，文章會更像真的做過資料。")


# =========================
# 12) 路由
# =========================
if mode.startswith("🧭"):
    title_prefix = "全校" if selected_college == "全部學院" else selected_college
    overview_page(target_df, title_prefix)
elif mode.startswith("📌"):
    onepager_page(target_df, selected_dept)
else:
    warroom_page(target_df, selected_dept)

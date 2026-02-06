# 檔案名稱：2_dashboard.py（理性版：Top3 深度解析 + 數字線索人類化摘要 + Prompt 注入）
import os
import re
import json
import hashlib
from urllib.parse import urlparse

import streamlit as st
import pandas as pd
import plotly.express as px
from collections import Counter

# ---- 可選：requests / bs4（深度分析用）----
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

st.set_page_config(page_title="全台招生 GEO/AI 戰情室", layout="wide")


# =========================
# 0) 小工具
# =========================
def safe_str(x, default="無"):
    if x is None:
        return default
    s = str(x)
    return s if s.strip() else default

def clip_text(s, n=160):
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
        x = x.strip()
        if not x:
            continue
        if x in seen:
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


# =========================
# 1) 深度分析：抓頁 + 解析 + 快取（Top3）
# =========================
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

# 抓數字（含 %）
NUM_PATTERN = r"\d+(?:\.\d+)?%?"
MONEY_PATTERN = r"(\d+(?:\.\d+)?)(\s*萬|\s*元|\s*[kK])"
YEAR_PATTERN = r"(20\d{2}|19\d{2})"
RANGE_PATTERN = r"(\d+(?:\.\d+)?)[\s]*[~～\-–—][\s]*(\d+(?:\.\d+)?)"

KW_SALARY = ["薪", "薪資", "月薪", "年薪", "起薪", "待遇", "元", "萬", "k", "K"]
KW_SCORE = ["分數", "級分", "錄取", "門檻", "最低", "統測", "繁星", "甄選", "落點", "PR", "倍率", "級距"]
KW_CREDITS = ["學分", "必修", "選修", "總學分", "畢業學分"]
KW_PASS = ["及格", "通過", "合格", "及格率", "通過率", "合格率", "錄取率", "國考", "證照"]

def _cache_key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()

def load_cached_page(url: str):
    fp = os.path.join(CACHE_DIR, _cache_key(url) + ".json")
    if os.path.exists(fp):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_cached_page(url: str, data: dict):
    fp = os.path.join(CACHE_DIR, _cache_key(url) + ".json")
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


# =========================
# 2) 數字線索：分類 + 人類化摘要
# =========================
def classify_number_clues(text: str) -> dict:
    """
    先把頁面裡的數字抓出來，依上下文分類：
    salary / score / credits / passrate
    """
    clues = {"salary": [], "score": [], "credits": [], "passrate": []}
    if not text:
        return clues

    t = text.replace("％", "%")

    for m in re.finditer(NUM_PATTERN, t):
        val = m.group(0)
        s = max(0, m.start() - 26)
        e = min(len(t), m.end() + 26)
        ctx = t[s:e].strip()
        if len(ctx) > 90:
            ctx = ctx[:90] + "…"

        # 及格率/通過率（含 % 且附近有通過/及格/證照/國考）
        if ("%" in val or "%" in ctx) and any(k in ctx for k in KW_PASS):
            clues["passrate"].append(ctx)
            continue

        # 學分（看到學分/必修/選修）
        if any(k in ctx for k in KW_CREDITS) or ("學分" in ctx):
            clues["credits"].append(ctx)
            continue

        # 薪資（薪/元/萬/k）
        if any(k in ctx for k in KW_SALARY):
            clues["salary"].append(ctx)
            continue

        # 分數/門檻（必須有關鍵詞才算）
        if any(k in ctx for k in KW_SCORE):
            clues["score"].append(ctx)
            continue

    for k in clues:
        clues[k] = _dedup_keep_order(clues[k], max_n=12)
    return clues


def _extract_money_values(ctx: str):
    """
    從上下文抓可能的薪資數值，回傳 list[(value, unit)]，unit: '元'/'萬'/'k'
    """
    vals = []
    for m in re.finditer(MONEY_PATTERN, ctx):
        num = m.group(1)
        unit = m.group(2).strip()
        vals.append((num, unit))
    return vals


def _normalize_money(num_str, unit):
    """
    嘗試把薪資轉為「月薪元」估計（很粗略但可用）
    - '萬' => *10000
    - 'k' => *1000
    - '元' => 原樣
    回傳 int 或 None
    """
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
    """
    將薪資線索整理成更像人類的輸出：
    - 優先找區間（例如 3.2~3.8 萬、32000~38000）
    - 再找單值（例如 35k）
    - 判斷月薪/年薪/起薪字樣
    """
    if not clues_salary:
        return {"found": False, "type": "無", "range": None, "points": [], "note": ""}

    types = {"月薪": 0, "年薪": 0, "起薪": 0}
    money_nums = []
    ranges = []

    points = []
    for ctx in clues_salary[:12]:
        points.append(ctx)
        for t in types:
            if t in ctx:
                types[t] += 1

        # 抓區間（數字~數字）
        rm = re.search(RANGE_PATTERN, ctx)
        if rm and any(k in ctx for k in ["萬", "元", "k", "K", "薪", "月薪", "年薪", "起薪"]):
            a, b = rm.group(1), rm.group(2)
            # 嘗試從 ctx 推 unit
            unit = "元" if "元" in ctx else ("萬" if "萬" in ctx else ("k" if ("k" in ctx or "K" in ctx) else "元"))
            va = _normalize_money(a, unit)
            vb = _normalize_money(b, unit)
            if va and vb:
                lo, hi = min(va, vb), max(va, vb)
                ranges.append((lo, hi, ctx))

        # 抓單值
        for num, unit in _extract_money_values(ctx):
            v = _normalize_money(num, unit)
            if v:
                money_nums.append((v, ctx))

    # 判斷最可能的類型
    best_type = max(types, key=lambda k: types[k])
    if types[best_type] == 0:
        best_type = "薪資"

    # 組合摘要
    summary_range = None
    if ranges:
        # 取最合理的範圍（去掉極端：>200k 月薪的先不信）
        sane = [r for r in ranges if 15000 <= r[0] <= 200000 and 15000 <= r[1] <= 200000]
        use = sane[0] if sane else ranges[0]
        summary_range = (use[0], use[1])

    note = "建議用『區間 + 年資/職務』描述，避免只寫單一死數字。"
    return {
        "found": True,
        "type": best_type,
        "range": summary_range,
        "points": _dedup_keep_order(points, max_n=6),
        "note": note
    }


def summarize_score(clues_score: list) -> dict:
    """
    分數/門檻：不硬算精準數字，偏理性寫法：『近2-3年區間』『以官方簡章為準』
    """
    if not clues_score:
        return {"found": False, "points": [], "note": ""}

    points = _dedup_keep_order(clues_score, max_n=6)
    note = "門檻通常會隨年度浮動，建議用『近 2–3 年區間』呈現，並引用官方招生簡章/分發資料。"
    return {"found": True, "points": points, "note": note}


def summarize_credits(clues_credits: list) -> dict:
    """
    學分：嘗試抓『總學分/必修/選修』，抓不到就輸出理性模板。
    """
    if not clues_credits:
        return {"found": False, "total": None, "required": None, "elective": None, "points": [], "note": ""}

    text = " ".join(clues_credits[:10])
    # 粗抓：例如「畢業總學分 128」「必修 90」「選修 38」
    total = None
    required = None
    elective = None

    m_total = re.search(r"(總學分|畢業學分)[^\d]{0,6}(\d{2,3})", text)
    if m_total:
        total = _to_int_safe(m_total.group(2))

    m_req = re.search(r"(必修)[^\d]{0,6}(\d{2,3})", text)
    if m_req:
        required = _to_int_safe(m_req.group(2))

    m_ele = re.search(r"(選修)[^\d]{0,6}(\d{2,3})", text)
    if m_ele:
        elective = _to_int_safe(m_ele.group(2))

    points = _dedup_keep_order(clues_credits, max_n=6)
    note = "學分/課程以系網課程地圖或課程查詢系統為準；用表格呈現最清楚。"
    return {"found": True, "total": total, "required": required, "elective": elective, "points": points, "note": note}


def summarize_passrate(clues_pass: list) -> dict:
    """
    及格率/通過率：抓到 % 就整理成『可能的通過率敘述』，但仍提醒以官方/可查來源為準。
    """
    if not clues_pass:
        return {"found": False, "rates": [], "points": [], "note": ""}

    points = _dedup_keep_order(clues_pass, max_n=6)
    rates = []
    for ctx in points:
        for p in re.findall(r"\d+(?:\.\d+)?%", ctx):
            rates.append(p)
    rates = _dedup_keep_order(rates, max_n=6)

    note = "通過率/及格率務必標示年份與來源（考選部/官方公告/校方公開成果），避免被質疑。"
    return {"found": True, "rates": rates, "points": points, "note": note}


def humanize_number_output(agg_clues: dict) -> dict:
    """
    把聚合的分類線索 → 產出更像人類寫的『理性摘要』結構。
    """
    out = {
        "salary": summarize_salary(agg_clues.get("salary", [])),
        "score": summarize_score(agg_clues.get("score", [])),
        "credits": summarize_credits(agg_clues.get("credits", [])),
        "passrate": summarize_passrate(agg_clues.get("passrate", []))
    }
    return out


def build_rational_citation_paragraphs(human: dict) -> str:
    """
    將人類化摘要 → 生成可直接貼文章的「理性引用段落」（偏理性，不煽情）。
    """
    paras = []

    # 薪資
    sal = human.get("salary", {})
    if sal.get("found"):
        r = sal.get("range")
        if r:
            lo, hi = r
            # 轉成「萬」顯示比較人類
            lo_w = round(lo / 10000, 1)
            hi_w = round(hi / 10000, 1)
            line = f"以目前網路可見資料來看，薪資多以『區間』呈現，約落在 **{lo_w}～{hi_w} 萬/月**（會依地區、班別、職務而變動）。"
        else:
            line = "薪資資訊多半建議用『區間 + 年資/職務』描述，避免單一數字造成誤導。"

        paras.append(
            "### 薪資（理性寫法）\n"
            f"{line}\n"
            "- **寫法建議**：用『起薪/1–3 年/3–5 年』分段，或用『職務別』分段。\n"
            "- **引用建議**：104/人力銀行職缺薪資區間、醫院招募公告（標示年份/來源）。"
        )

    # 分數/門檻
    sc = human.get("score", {})
    if sc.get("found"):
        paras.append(
            "### 分數/門檻（理性寫法）\n"
            "錄取門檻通常會隨年度浮動，因此比較穩的呈現方式是：**整理近 2–3 年區間**，並清楚標註『入學管道』（統測分發/甄選/繁星等）。\n"
            "- **引用建議**：各校招生簡章、甄選入學簡章、統測分發資料（以官方版本為準）。"
        )

    # 學分/課程
    cr = human.get("credits", {})
    if cr.get("found"):
        t = cr.get("total")
        req = cr.get("required")
        ele = cr.get("elective")
        if t or req or ele:
            rows = []
            if t: rows.append(f"- 畢業總學分：{t}")
            if req: rows.append(f"- 必修：{req}")
            if ele: rows.append(f"- 選修：{ele}")
            detail = "\n".join(rows)
        else:
            detail = "- 建議直接放『課程地圖/學分結構表』（讀者會一眼懂）。"

        paras.append(
            "### 學分/課程（理性寫法）\n"
            "課程資訊最有效的呈現方式，是把『學分結構』用表格說清楚，並搭配『年級學習路徑』（大一打底→大二專業→後續實習/專題）。\n"
            f"{detail}\n"
            "- **引用建議**：系網課程規劃、課程查詢系統、招生簡章附錄。"
        )

    # 及格率/通過率
    pr = human.get("passrate", {})
    if pr.get("found"):
        rates = pr.get("rates") or []
        if rates:
            rate_line = "網路頁面中可見的通過率/及格率片段包含：" + "、".join(rates) + "（仍需以官方/可查來源核對年份與口徑）。"
        else:
            rate_line = "若文章要提到通過率/及格率，務必標示年份與來源，避免被質疑。"

        paras.append(
            "### 國考/證照通過率（理性寫法）\n"
            f"{rate_line}\n"
            "- **寫法建議**：不要只丟一個 %，要交代『年份、母數、考試種類』。\n"
            "- **引用建議**：考選部/官方公告、公會資訊、校方公開成果（附年份）。"
        )

    if not paras:
        return (
            "### 建議引用段落（通用理性版）\n"
            "若目前 Top3 的內容缺少可查證數據，建議用『官方來源 + 表格整理 + FAQ』補齊。\n"
            "- **引用建議**：系網、招生簡章、政府/公會資訊、104。"
        )

    return "\n\n".join(paras)


# =========================
# 3) 解析網頁
# =========================
def parse_competitor_page(url: str) -> dict:
    """
    解析對手頁面：抓 H1/H2/H3、meta、表格/FAQ/條列，
    並把數字線索分類（薪資/分數/學分/及格率）。
    """
    cached = load_cached_page(url)
    if cached:
        return cached

    html = fetch_html(url)
    if not html:
        data = {"url": url, "ok": 0, "reason": "fetch_failed"}
        save_cached_page(url, data)
        return data

    # --- 沒 bs4：退化 regex ---
    if not HAS_BS4:
        lower = html.lower()
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
            "has_table": 1 if "<table" in lower else 0,
            "has_list": 1 if ("<ul" in lower or "<ol" in lower) else 0,
            "has_faq": has_faq,
            "number_clues": number_clues,
            "text_preview": text[:900],
            "bullets": [],
        }
        save_cached_page(url, data)
        return data

    # --- bs4：較準 ---
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
        lis = ul.find_all("li")
        for li in lis[:8]:
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
# 4) 讀取數據 + 防呆清理
# =========================
try:
    df = pd.read_csv("school_data.csv")
except FileNotFoundError:
    st.error("❌ 找不到 school_data.csv，請先執行 powergeo.py 產出數據。")
    st.stop()

TEXT_COLS = [
    "College","Department","Keyword","Keyword_Type","Strategy_Tag",
    "Rank1_Title","Rank1_Link","Rank1_Snippet",
    "Rank2_Title","Rank2_Link","Rank2_Snippet",
    "Rank3_Title","Rank3_Link","Rank3_Snippet",
    "Competitor_Hit"
]
NUM_COLS = [
    "Search_Volume", "Trends_Score", "Trends_Fetched",
    "Opportunity_Score","AI_Potential",
    "Authority_Count","Forum_Count","Answerable_Avg",
    "Citable_Score","Fetch_OK_Count",
    "Schema_Hit_Count",
    "Has_FAQ","Has_Table","Has_List","Has_Headings",
    "Page_Word_Count_Max",
    "Result_Count"
]

for c in TEXT_COLS:
    if c not in df.columns:
        df[c] = "無"
for c in NUM_COLS:
    if c not in df.columns:
        df[c] = 0

df[TEXT_COLS] = df[TEXT_COLS].fillna("無").astype(str)
for c in NUM_COLS:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)


# =========================
# 5) 側邊欄：篩選器
# =========================
st.sidebar.title("🏫 全台招生 GEO/AI 戰情室")

college_list = ["全部學院"] + sorted(df["College"].unique().tolist())
selected_college = st.sidebar.selectbox("STEP 1: 選擇學院", college_list)

if selected_college == "全部學院":
    dept_options = ["全校總覽"] + sorted(df["Department"].unique().tolist())
else:
    dept_options = ["學院總覽"] + sorted(df[df["College"] == selected_college]["Department"].unique().tolist())

selected_dept = st.sidebar.selectbox("STEP 2: 選擇科系/視角", dept_options)

kw_types = ["全部意圖"] + sorted(df["Keyword_Type"].unique().tolist())
selected_kw_type = st.sidebar.selectbox("STEP 3: 篩選搜尋意圖", kw_types)

min_ai = st.sidebar.slider("AI_Potential 最低門檻", 0, 100, 0, 5)
min_opp_max = int(max(1, df["Opportunity_Score"].max()))
min_opp = st.sidebar.slider("Opportunity_Score 最低門檻", 0, min_opp_max, 0, 10)

def volume_col(scope_df: pd.DataFrame) -> str:
    if "Trends_Score" in scope_df.columns and scope_df["Trends_Score"].sum() > 0:
        return "Trends_Score"
    return "Search_Volume"

target_df = df.copy()
if selected_college != "全部學院":
    target_df = target_df[target_df["College"] == selected_college]
if selected_kw_type != "全部意圖":
    target_df = target_df[target_df["Keyword_Type"] == selected_kw_type]
target_df = target_df[target_df["AI_Potential"] >= min_ai]
target_df = target_df[target_df["Opportunity_Score"] >= min_opp]


# =========================
# 6) 總覽頁
# =========================
def overview_page(scope_df: pd.DataFrame, title_prefix: str):
    st.title(f"📊 {title_prefix}：GEO/AI 戰略地圖")

    vcol = volume_col(scope_df)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("關鍵字筆數", int(len(scope_df)))
    with c2:
        st.metric("平均 Opportunity", round(scope_df["Opportunity_Score"].mean(), 1) if len(scope_df) else 0)
    with c3:
        st.metric("平均 AI_Potential", round(scope_df["AI_Potential"].mean(), 1) if len(scope_df) else 0)
    with c4:
        st.metric("平均 Citable", round(scope_df["Citable_Score"].mean(), 1) if len(scope_df) else 0)
    with c5:
        label = "平均 Trends 聲量" if vcol == "Trends_Score" else "平均聲量"
        st.metric(label, round(scope_df[vcol].mean(), 2) if len(scope_df) else 0)

    st.divider()

    colA, colB = st.columns([2, 1])
    with colA:
        dept_rank = (
            scope_df.groupby("Department", as_index=False)["Opportunity_Score"]
            .mean()
            .sort_values("Opportunity_Score", ascending=False)
        )
        fig = px.bar(dept_rank, x="Department", y="Opportunity_Score", color="Department",
                     title="各系 GEO 機會值排行（平均）")
        st.plotly_chart(fig, use_container_width=True)

    with colB:
        fig2 = px.pie(scope_df, names="Keyword_Type", title="搜尋意圖分佈")
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    colC, colD = st.columns(2)
    with colC:
        vol_rank = (
            scope_df.groupby("Department", as_index=False)[vcol]
            .mean()
            .sort_values(vcol, ascending=False)
        )
        title = "各系 Google Trends 相對聲量（平均）" if vcol == "Trends_Score" else "各系聲量指標（平均）"
        fig3 = px.bar(vol_rank, x="Department", y=vcol, color="Department", title=title)
        st.plotly_chart(fig3, use_container_width=True)

    with colD:
        fig4 = px.scatter(
            scope_df, x="Authority_Count", y="Citable_Score",
            size="Opportunity_Score",
            hover_data=["Department", "Keyword", "Rank1_Title"],
            title="可引用性（Citable） vs 權威來源數（Authority）"
        )
        st.plotly_chart(fig4, use_container_width=True)

    st.divider()
    st.subheader("📋 熱點關鍵字總表")

    show_cols = [
        "College","Department","Keyword","Keyword_Type",
        "Opportunity_Score","AI_Potential",
        "Citable_Score","Authority_Count","Forum_Count",
        vcol,"Trends_Fetched","Rank1_Title"
    ]
    show_cols = [c for c in show_cols if c in scope_df.columns]

    st.dataframe(
        scope_df[show_cols].sort_values(["Opportunity_Score","AI_Potential"], ascending=False),
        use_container_width=True,
        height=560
    )


# =========================
# 7) 單一科系頁（深度分析 + 理性 Prompt）
# =========================
def dept_page(scope_df: pd.DataFrame, dept_name: str):
    st.title(f"🔍 {dept_name}：競品 + GEO/AI + 理性深度分析文案生成器")

    dept_df = scope_df[scope_df["Department"] == dept_name].copy()
    if dept_df.empty:
        st.warning("這個篩選條件下沒有資料。可以把左邊門檻調低一點再看。")
        st.stop()

    dept_df = dept_df.sort_values(["Opportunity_Score","AI_Potential"], ascending=False)
    vcol = volume_col(dept_df)

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1: st.metric("關鍵字筆數", int(len(dept_df)))
    with k2: st.metric("平均 Opportunity", round(dept_df["Opportunity_Score"].mean(), 1))
    with k3: st.metric("平均 AI_Potential", round(dept_df["AI_Potential"].mean(), 1))
    with k4: st.metric("平均 Citable", round(dept_df["Citable_Score"].mean(), 1))
    with k5:
        label = "平均 Trends 聲量" if vcol == "Trends_Score" else "平均聲量"
        st.metric(label, round(dept_df[vcol].mean(), 2))

    st.divider()

    colX, colY = st.columns([2, 1])
    with colX:
        fig = px.box(dept_df, x="Keyword_Type", y="Opportunity_Score", title="不同意圖的機會值分佈")
        st.plotly_chart(fig, use_container_width=True)
    with colY:
        fig2 = px.bar(
            dept_df.groupby("Keyword_Type", as_index=False)["AI_Potential"].mean().sort_values("AI_Potential", ascending=False),
            x="Keyword_Type", y="AI_Potential", title="各意圖平均 AI_Potential"
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("🕵️ 選一個關鍵字，看 Top3 + 深度解析")

    dept_df["Display_Label"] = dept_df["Keyword"] + " [" + dept_df["Keyword_Type"] + "]"
    target_label = st.selectbox("請選擇關鍵字", dept_df["Display_Label"].unique())
    target_row = dept_df[dept_df["Display_Label"] == target_label].iloc[0]

    kw = safe_str(target_row["Keyword"])
    strategy = safe_str(target_row["Strategy_Tag"])
    kw_type = safe_str(target_row["Keyword_Type"])

    st.markdown("#### 🧠 深度分析（抓 Top3 網頁：H2/表格/FAQ/數字 → 轉成理性摘要）")
    if not HAS_REQUESTS:
        st.warning("你的環境缺少 requests，無法深度分析。請 pip install requests")
        deep_on = False
        run_deep = False
    else:
        deep_on = st.checkbox("啟用深度分析（第一次會慢一點；有快取）", value=False)
        run_deep = st.button("開始抓取並分析 Top3")

    st.divider()

    col_l, col_r = st.columns([1, 2])

    with col_l:
        st.metric("Opportunity", round(float(target_row["Opportunity_Score"]), 1))
        st.metric("AI_Potential", int(target_row["AI_Potential"]))
        st.metric("Citable", round(float(target_row["Citable_Score"]), 1))

        label = "Trends 聲量" if vcol == "Trends_Score" else "聲量"
        st.metric(label, round(float(target_row.get(vcol, 0)), 2))

        st.metric("Authority", int(target_row["Authority_Count"]))
        st.metric("Forum", int(target_row["Forum_Count"]))

        st.caption("結構化特徵（越多越容易被 AI 摘錄）")
        s_cols = st.columns(4)
        s_cols[0].metric("FAQ", int(target_row["Has_FAQ"]))
        s_cols[1].metric("Table", int(target_row["Has_Table"]))
        s_cols[2].metric("List", int(target_row["Has_List"]))
        s_cols[3].metric("H2/H3", int(target_row["Has_Headings"]))

        st.info(f"策略建議：{strategy}")

    competitor_info_text = ""
    deep_briefs = []
    gap_pool_h2 = []
    agg_number_clues = {"salary": [], "score": [], "credits": [], "passrate": []}

    with col_r:
        st.markdown(f"### 👀 「{kw}」Top 3 結果")

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

    # Content Gap（H2）
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
        st.subheader("📌 深度摘要（理性版：把數字線索整理成可用結論）")

        # 理性摘要卡
        with st.container(border=True):
            st.markdown("#### ① 數字線索 → 理性結論（可直接放進文章）")
            st.markdown(rational_paras)

        # 競品頁面摘要（可選看）
        st.subheader("② 競品頁面結構摘要（給你對照用）")
        for idx, info in deep_briefs:
            with st.expander(f"#{idx} {domain_of(info['url'])}｜{info.get('title','')[:50]}"):
                st.write(f"**H1：** {safe_str(info.get('h1','無'))}")
                if info.get("meta_desc"):
                    st.write(f"**Meta：** {info.get('meta_desc')}")
                st.write(f"**結構化：** FAQ={info.get('has_faq',0)}｜Table={info.get('has_table',0)}｜List={info.get('has_list',0)}")
                if info.get("h2"):
                    st.write("**H2：** " + " / ".join(info["h2"][:12]))
                if info.get("bullets"):
                    st.write("**條列：**")
                    for b in info["bullets"][:10]:
                        st.write(f"- {b}")
                st.caption(f"URL: {info['url']}")

        if gap_suggestions:
            st.subheader("🧩 Content Gap（Top1 沒講但其他人常提）")
            for g in gap_suggestions:
                st.write(f"- {g}")

    # ===== Prompt 注入（理性口吻）=====
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

    cite_block = "\n# 📎 建議引用段落（理性版，可直接用）\n" + rational_paras + "\n"

    st.divider()
    st.subheader("✍️ AI 智能文案生成器（理性版：有數據就用區間、有引用就講來源）")

    template_type = st.radio(
        "文章要走哪種理性打法？",
        [
            "⚔️ 理性競爭型（對照表 + 缺口補齊）",
            "🏆 理性權威型（制度/流程/引用優先）",
            "🤖 AI 友善型（表格 + FAQ + 可摘錄）"
        ],
        horizontal=True
    )

    if "競爭型" in template_type:
        base_instruction = (
            "請把內容寫成『能被檢核』的版本：主張要有依據、比較要有表格、缺口要補完整。"
        )
        structure_req = (
            "1) 開頭用 4–6 行 TL;DR（結論先講）\n"
            "2) 用 Markdown 表格做「本校 vs Top1」對照（課程/實習/證照/出路/資源）\n"
            "3) 把 Content Gap 一次補齊（至少 6 點）\n"
            "4) FAQ 至少 8 題（短、直接、可摘錄）\n"
        )
    elif "權威型" in template_type:
        base_instruction = (
            "這篇以『制度與可查資料』建立可信度：入學管道、課程結構、實習、證照/國考、就業路徑。"
        )
        structure_req = (
            "1) 入學管道與門檻（強調『近 2–3 年區間』與來源）\n"
            "2) 課程地圖與學分結構（用表格）\n"
            "3) 實習與證照/國考（流程化說明 + 引用建議）\n"
            "4) 出路與薪資（用區間/年資/職務）\n"
            "5) FAQ 至少 6 題\n"
        )
    else:
        base_instruction = (
            "把文章寫成 AI 最好摘要的格式：短段落、表格、條列、FAQ，並標示引用來源類型。"
        )
        structure_req = (
            "1) TL;DR（5 行）\n"
            "2) 核心表格（至少 1 張）\n"
            "3) 步驟清單（面試/選課/考照任一）\n"
            "4) FAQ 至少 10 題\n"
        )

    geo_hint = (
        f"- 意圖：{kw_type}\n"
        f"- 指標：Opportunity={round(float(target_row['Opportunity_Score']),1)}｜AI={int(target_row['AI_Potential'])}｜"
        f"Citable={round(float(target_row['Citable_Score']),1)}｜Authority={int(target_row['Authority_Count'])}｜Forum={int(target_row['Forum_Count'])}\n"
        f"- 結構化：FAQ={int(target_row['Has_FAQ'])}｜Table={int(target_row['Has_Table'])}｜List={int(target_row['Has_List'])}｜H2/H3={int(target_row['Has_Headings'])}\n"
        f"- 競品命中：{safe_str(target_row.get('Competitor_Hit','無'))}\n"
    )

    final_prompt = f"""
# 角色
你是一位偏理性、重視可查資料與結構化呈現的 SEO + GEO 內容策略顧問。

# 任務
為「{dept_name}」寫一篇要衝排名、也要容易被 AI 摘錄/引用的文章。
目標關鍵字：**{kw}**

# 目前 Top3 在講什麼（摘要）
{competitor_info_text}

{deep_text_for_prompt}
{gap_text}
{cite_block}

# 本次戰情室觀測
{geo_hint}

# 寫作要求（{template_type}）
- 語氣偏理性：避免口號式形容詞，主張要能被檢核
- 涉及數據（薪資/分數/學分/及格率）優先用『區間』，並交代『年份/來源類型』
- 文章要用 Markdown，H2/H3 清楚

# 結構（照做）
{structure_req}

# 收尾
- 再補 3 題「大家最常問」Q&A
- 加 CTA：系網/參訪/諮詢方式
"""

    st.text_area("📋 複製 Prompt 給 ChatGPT / Gemini / Claude：", final_prompt, height=620)
    st.success("✅ 若你有啟用深度分析，這個 Prompt 會更像『真的看過對手內容』後寫出來的版本。")

    st.divider()
    st.subheader("🧾 本系關鍵字清單")
    table_cols = [
        "Keyword","Keyword_Type","Opportunity_Score","AI_Potential",
        "Citable_Score","Authority_Count","Forum_Count",
        vcol,"Trends_Fetched","Rank1_Title"
    ]
    table_cols = [c for c in table_cols if c in dept_df.columns]
    st.dataframe(
        dept_df[table_cols].sort_values(["Opportunity_Score","AI_Potential"], ascending=False),
        use_container_width=True,
        height=460
    )


# =========================
# 8) 路由
# =========================
if "總覽" in selected_dept:
    if selected_dept == "全校總覽":
        overview_page(target_df, "全校")
    else:
        overview_page(target_df, selected_college)
else:
    dept_page(target_df, selected_dept)

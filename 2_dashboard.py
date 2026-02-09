# 檔案名稱：2_dashboard.py（完全對應最新版 powergeo.py：Source/Evidence + Trends + SERP 深度解析 + 理性引用段落）
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


# =========================
# 1) 小工具
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
    """
    優先用 Trends_Score（你新版 powergeo 主要指標），沒有再 fallback Search_Volume
    """
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


# =========================
# 2) 深度分析：抓頁 + 結構特徵 + 數字線索分類
# =========================
NUM_PATTERN = r"\d+(?:\.\d+)?%?"
MONEY_PATTERN = r"(\d+(?:\.\d+)?)(\s*萬|\s*元|\s*[kK])"
RANGE_PATTERN = r"(\d+(?:\.\d+)?)[\s]*[~～\-–—][\s]*(\d+(?:\.\d+)?)"

KW_SALARY = ["薪", "薪資", "月薪", "年薪", "起薪", "待遇", "元", "萬", "k", "K"]
KW_SCORE = ["分數", "級分", "錄取", "門檻", "最低", "統測", "繁星", "甄選", "落點", "PR", "倍率", "級距"]
KW_CREDITS = ["學分", "必修", "選修", "總學分", "畢業學分", "課程地圖"]
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

def _extract_money_values(ctx: str):
    vals = []
    for m in re.finditer(MONEY_PATTERN, ctx):
        num = m.group(1)
        unit = m.group(2).strip()
        vals.append((num, unit))
    return vals

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
        "note": "建議用『區間 + 年資/職務』描述，避免只丟一個單點數字。"
    }

def summarize_score(clues_score: list) -> dict:
    if not clues_score:
        return {"found": False, "points": [], "note": ""}
    points = _dedup_keep_order(clues_score, max_n=6)
    return {
        "found": True,
        "points": points,
        "note": "門檻會隨年度浮動，最像人會寫的方式是『近 2–3 年區間』＋標註入學管道＋引用官方簡章。"
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
        "note": "學分/課程以系網課程地圖或課程查詢系統為準；用表格呈現最清楚。"
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
            line = f"薪資資訊比較像人會寫的方式是用『區間』：大概落在 **{lo_w}～{hi_w} 萬/月**（會依地區、班別、職務而變動）。"
        else:
            line = "薪資資訊建議用『區間 + 年資/職務』描述，避免單一數字造成誤導。"

        paras.append(
            "### 薪資（理性寫法）\n"
            f"{line}\n"
            "- **引用建議**：104 職缺薪資區間、醫院/檢驗所招募公告（標年份/來源）。"
        )

    sc = human.get("score", {})
    if sc.get("found"):
        paras.append(
            "### 分數/門檻（理性寫法）\n"
            "錄取門檻每年會動，最穩的寫法是：**整理近 2–3 年區間**，並標註『入學管道』（統測分發/甄選/繁星）。\n"
            "- **引用建議**：官方招生簡章、分發/甄選入學資料。"
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
        detail = "\n".join(rows) if rows else "- 建議直接貼『學分結構表 + 課程地圖』，讀者一秒懂。"

        paras.append(
            "### 學分/課程（理性寫法）\n"
            "課程資訊用表格最有效：把『學分結構』＋『年級學習路徑』講清楚。\n"
            f"{detail}\n"
            "- **引用建議**：系網課程規劃、課程查詢系統、招生簡章附錄。"
        )

    pr = human.get("passrate", {})
    if pr.get("found"):
        rates = pr.get("rates") or []
        rate_line = "網頁片段中可見的 % 包含：" + "、".join(rates) + "（仍需核對年份與口徑）。" if rates else \
                    "若要寫通過率/及格率，務必補齊年份與來源，否則容易被質疑。"

        paras.append(
            "### 國考/證照通過率（理性寫法）\n"
            f"{rate_line}\n"
            "- **引用建議**：考選部/官方公告、校方公開成果（附年份）。"
        )

    if not paras:
        return (
            "### 建議引用段落（通用理性版）\n"
            "如果 Top3 缺少可查證數據，建議用『官方來源 + 表格整理 + FAQ』補齊，文章會更容易被 AI 摘錄。"
        )

    return "\n\n".join(paras)

def parse_competitor_page(url: str) -> dict:
    cached = load_cached_page(url)
    if cached:
        return cached

    html = fetch_html(url)
    if not html:
        data = {"url": url, "ok": 0, "reason": "fetch_failed"}
        save_cached_page(url, data)
        return data

    if not HAS_BS4:
        # 退化版：只拿純文字
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
# 3) 讀取 CSV（對齊最新版 powergeo.py）
# =========================
try:
    df = pd.read_csv("school_data.csv")
except FileNotFoundError:
    st.error("❌ 找不到 school_data.csv，請先執行 powergeo.py 產生資料。")
    st.stop()

# 必要欄位（沒有就補）
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

# 清理型別
for c in TEXT_DEFAULTS.keys():
    df[c] = df[c].fillna(TEXT_DEFAULTS[c]).astype(str)

for c in NUM_DEFAULTS.keys():
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(NUM_DEFAULTS[c])

# 排序一下（看起來比較正常）
df = df.sort_values(["College", "Department", "Opportunity_Score"], ascending=[True, True, False])


# =========================
# 4) Sidebar：篩選（完全對應新版）
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

source_list = ["全部來源"] + sorted(df["Keyword_Source"].unique().tolist())
selected_source = st.sidebar.selectbox("STEP 4: 篩選 Keyword 來源", source_list)

min_ai = st.sidebar.slider("AI_Potential 最低門檻", 0, 100, 0, 5)
min_opp_max = int(max(1, df["Opportunity_Score"].max()))
min_opp = st.sidebar.slider("Opportunity_Score 最低門檻", 0, min_opp_max, 0, 10)

st.sidebar.caption("提示：想看最像真人輸入的，來源選 Autocomplete。")


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
# 5) 總覽頁
# =========================
def overview_page(scope_df: pd.DataFrame, title_prefix: str):
    st.title(f"📊 {title_prefix}：GEO/AI 戰略地圖（對齊 powergeo 新版）")

    vcol = prefer_volume_col(scope_df)
    vlabel = "Google Trends 相對聲量" if vcol == "Trends_Score" else "聲量指標"

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("關鍵字筆數", int(len(scope_df)))
    with c2: st.metric("平均 Opportunity", round(scope_df["Opportunity_Score"].mean(), 1) if len(scope_df) else 0)
    with c3: st.metric("平均 AI_Potential", round(scope_df["AI_Potential"].mean(), 1) if len(scope_df) else 0)
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
        vol_rank = (
            scope_df.groupby("Department", as_index=False)[vcol]
            .mean()
            .sort_values(vcol, ascending=False)
        )
        fig3 = px.bar(vol_rank, x="Department", y=vcol, color="Department",
                      title=f"各系 {vlabel}（平均）")
        st.plotly_chart(fig3, use_container_width=True)

    with colB:
        src_rank = (
            scope_df.groupby("Keyword_Source", as_index=False)
            .size()
            .rename(columns={"size": "Count"})
            .sort_values("Count", ascending=False)
        )
        fig4 = px.bar(src_rank, x="Keyword_Source", y="Count", color="Keyword_Source",
                      title="Keyword 來源分佈（看是不是 template 產的）")
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
        height=620
    )


# =========================
# 6) 單一科系頁：Top3 + 深度解析 + Prompt 注入（來源證據）
# =========================
def dept_page(scope_df: pd.DataFrame, dept_name: str):
    st.title(f"🔍 {dept_name}：競品 + 來源證據 + 深度解析 + 理性 Prompt")

    dept_df = scope_df[scope_df["Department"] == dept_name].copy()
    if dept_df.empty:
        st.warning("這個篩選條件下沒有資料。可以把左邊門檻調低一點再看。")
        st.stop()

    dept_df = dept_df.sort_values(["Opportunity_Score","AI_Potential"], ascending=False)
    vcol = prefer_volume_col(dept_df)
    vlabel = "Trends 相對聲量" if vcol == "Trends_Score" else "聲量指標"

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1: st.metric("關鍵字筆數", int(len(dept_df)))
    with k2: st.metric("平均 Opportunity", round(dept_df["Opportunity_Score"].mean(), 1))
    with k3: st.metric("平均 AI_Potential", round(dept_df["AI_Potential"].mean(), 1))
    with k4: st.metric("平均 Citable", round(dept_df["Citable_Score"].mean(), 1))
    with k5: st.metric(f"平均 {vlabel}", round(dept_df[vcol].mean(), 2))

    st.divider()

    colX, colY = st.columns([2, 1])
    with colX:
        fig = px.box(dept_df, x="Keyword_Source", y="Opportunity_Score", title="不同來源的機會值分佈")
        st.plotly_chart(fig, use_container_width=True)
    with colY:
        fig2 = px.bar(
            dept_df.groupby("Keyword_Source", as_index=False)["AI_Potential"].mean().sort_values("AI_Potential", ascending=False),
            x="Keyword_Source", y="AI_Potential", title="不同來源平均 AI_Potential"
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("🕵️ 選一個關鍵字，看 Top3 +（可選）深度解析")

    dept_df["Display_Label"] = (
        dept_df["Keyword"] + " 〔" +
        dept_df["Keyword_Type"] + " / " +
        dept_df["Keyword_Source"].apply(source_tag) + "〕"
    )
    target_label = st.selectbox("請選擇關鍵字", dept_df["Display_Label"].unique())
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
            st.code(evidence[:600])

    deep_on = False
    run_deep = False
    if HAS_REQUESTS:
        deep_on = st.checkbox("啟用深度解析：抓 Top3 網頁（第一次慢、有快取）", value=False)
        run_deep = st.button("開始深度解析 Top3")
    else:
        st.info("（可選）若要深度解析 Top3 網頁：請先 pip install requests beautifulsoup4")

    st.divider()

    # 左側：指標
    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.metric("Opportunity", round(float(target_row["Opportunity_Score"]), 1))
        st.metric("AI_Potential", int(target_row["AI_Potential"]))
        st.metric("Citable", round(float(target_row["Citable_Score"]), 1))
        st.metric(vlabel, round(float(target_row.get(vcol, 0)), 2))
        st.metric("Authority", int(target_row["Authority_Count"]))
        st.metric("Forum", int(target_row["Forum_Count"]))

        st.caption("結構化特徵（越多越容易被 AI 摘錄）")
        s_cols = st.columns(4)
        s_cols[0].metric("FAQ", int(target_row["Has_FAQ"]))
        s_cols[1].metric("Table", int(target_row["Has_Table"]))
        s_cols[2].metric("List", int(target_row["Has_List"]))
        s_cols[3].metric("H2/H3", int(target_row["Has_Headings"]))

        st.info(f"策略建議：{strategy}")

    # 右側：Top3 + 深度解析結果
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

    # Content Gap + 理性引用段落
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
        st.subheader("📌 深度解析摘要（把數字線索變成『人類會寫』的段落）")
        with st.container(border=True):
            st.markdown(rational_paras)

        if gap_suggestions:
            st.subheader("🧩 Content Gap（Top1 沒講、但其他人常提）")
            for g in gap_suggestions:
                st.write(f"- {g}")

        st.subheader("🧾 競品頁面結構摘要（對照用）")
        for idx, info in deep_briefs:
            with st.expander(f"#{idx} {domain_of(info['url'])}｜{info.get('title','')[:60]}"):
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

    # Prompt 注入區
    st.divider()
    st.subheader("✍️ AI 智能文案生成器（完全對應 powergeo 新版：來源證據 + 理性引用段落）")

    template_type = st.radio(
        "文章要走哪種理性打法？",
        [
            "⚔️ 理性競爭型（對照表 + 缺口補齊）",
            "🏆 理性權威型（流程/制度/引用優先）",
            "🤖 AI 友善型（表格 + FAQ + 可摘錄）"
        ],
        horizontal=True
    )

    if "競爭型" in template_type:
        base_instruction = "請把內容寫成『能被檢核』的版本：主張要有依據、比較要有表格、缺口要補完整。"
        structure_req = (
            "1) 開頭用 4–6 行 TL;DR（結論先講）\n"
            "2) Markdown 表格：本校 vs Top1（課程/實習/證照/出路/資源）\n"
            "3) Content Gap 一次補齊（至少 6 點）\n"
            "4) FAQ 至少 8 題（短、直接、可摘錄）\n"
        )
    elif "權威型" in template_type:
        base_instruction = "這篇以『制度與可查資料』建立可信度：入學管道、課程結構、實習、證照/國考、就業路徑。"
        structure_req = (
            "1) 入學管道與門檻（強調『近 2–3 年區間』與來源）\n"
            "2) 課程地圖與學分結構（用表格）\n"
            "3) 實習與證照/國考（流程化說明 + 引用建議）\n"
            "4) 出路與薪資（用區間/年資/職務）\n"
            "5) FAQ 至少 6 題\n"
        )
    else:
        base_instruction = "把文章寫成 AI 最好摘要的格式：短段落、表格、條列、FAQ，並標示引用來源類型。"
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

    geo_hint = (
        f"- 意圖：{kw_type}\n"
        f"- 指標：Opportunity={round(float(target_row['Opportunity_Score']),1)}｜AI={int(target_row['AI_Potential'])}｜"
        f"Citable={round(float(target_row['Citable_Score']),1)}｜Authority={int(target_row['Authority_Count'])}｜Forum={int(target_row['Forum_Count'])}\n"
        f"- 結構化：FAQ={int(target_row['Has_FAQ'])}｜Table={int(target_row['Has_Table'])}｜List={int(target_row['Has_List'])}｜H2/H3={int(target_row['Has_Headings'])}\n"
        f"- 來源：{src}｜Seed：{seed}\n"
    )

    # 關鍵：把「來源證據」寫成文章一句話的交代（很像人會做的）
    source_explain = (
        "請在文章前段用一句話交代資料來源與口徑，讓讀者知道你不是亂編。\n"
        "例如：『本文關鍵字來自 Google 建議詞/Trends 的相關查詢，再對照目前 Top3 內容補足缺口；涉及薪資/門檻/通過率會以官方或可查來源為準。』"
    )

    final_prompt = f"""
# 角色
你是一位偏理性、重視可查資料與結構化呈現的 SEO + GEO 內容策略顧問。

# 任務
為「{dept_name}」寫一篇要衝排名、也要容易被 AI 摘錄/引用的文章。
目標關鍵字：**{kw}**

# 關鍵字來源（要提高可信度，請在文中交代）
- Keyword_Source：{src}
- Seed_Term：{seed}
- Evidence：{evidence}

# 目前 Top3 在講什麼（摘要）
{competitor_info_text}
{deep_text_for_prompt}
{gap_text}
{cite_block}

# 本次戰情室觀測
{geo_hint}

# 寫作策略
{base_instruction}
{source_explain}

# 結構（照做）
{structure_req}

# Constraints
- 用 Markdown（H2/H3 清楚，表格要能被快速掃讀）
- 語氣偏理性：避免口號式形容詞，主張要能被檢核
- 涉及數據（薪資/分數/學分/及格率）優先用『區間』，並交代『年份/來源類型』
- 文末補 3 題「大家最常問」Q&A + CTA（系網/參訪/諮詢）
"""

    st.text_area("📋 複製 Prompt 給 ChatGPT / Gemini / Claude：", final_prompt, height=680)
    st.success("✅ 這份 Prompt 已把『Keyword 來源證據 + 理性引用段落 + Top3 摘要/缺口』一口氣塞進去，文章會更像真的做過資料。")

    st.divider()
    st.subheader("🧾 本系關鍵字清單（含來源）")
    table_cols = [
        "Keyword","Keyword_Source","Seed_Term","Keyword_Type",
        "Opportunity_Score","AI_Potential","Citable_Score",
        "Authority_Count","Forum_Count", vcol, "Trends_Fetched", "Rank1_Title"
    ]
    table_cols = [c for c in table_cols if c in dept_df.columns]
    st.dataframe(
        dept_df[table_cols].sort_values(["Opportunity_Score","AI_Potential"], ascending=False),
        use_container_width=True,
        height=520
    )


# =========================
# 7) 路由：總覽 / 單科系
# =========================
if "總覽" in selected_dept:
    if selected_dept == "全校總覽":
        overview_page(target_df, "全校")
    else:
        overview_page(target_df, selected_college)
else:
    dept_page(target_df, selected_dept)

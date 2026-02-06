# 檔案名稱：2_dashboard.py (GEO/AI 戰情室整合版：兼容舊/新版 school_data.csv + 競品注入 + 多模板提示詞)
import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="全台招生 GEO/AI 戰情室", layout="wide")

# =========================
# 0) 讀取數據 + 防呆清理
# =========================
try:
    df = pd.read_csv("school_data.csv")
except FileNotFoundError:
    st.error("❌ 找不到 school_data.csv，請先執行 powergeo.py 產出數據。")
    st.stop()

# 必備欄位（文字/數字）
TEXT_COLS = [
    "College", "Department", "Keyword", "Keyword_Type", "Strategy_Tag",
    "Rank1_Title", "Rank1_Link", "Rank1_Snippet",
    "Rank2_Title", "Rank2_Link", "Rank2_Snippet",
    "Rank3_Title", "Rank3_Link", "Rank3_Snippet",
    "Competitor_Hit"
]
NUM_COLS = [
    "Search_Volume",          # 在新版 powergeo.py：通常是 Result_Count（SERP 可見度），不是「月搜量」
    "Opportunity_Score",
    "AI_Potential",
    # 新版可引用性/結構化指標（若 CSV 沒有，會自動補 0）
    "Authority_Count", "Forum_Count", "Answerable_Avg",
    "Citable_Score", "Fetch_OK_Count",
    "Schema_Hit_Count",
    "Has_FAQ", "Has_Table", "Has_List", "Has_Headings",
    "Page_Word_Count_Max",
    "Result_Count"
]

# 缺欄位補上
for c in TEXT_COLS:
    if c not in df.columns:
        df[c] = "無"
for c in NUM_COLS:
    if c not in df.columns:
        df[c] = 0

# 文字欄位補 "無"
df[TEXT_COLS] = df[TEXT_COLS].fillna("無").astype(str)

# 數字欄位強制轉數字（轉不了就 0）
for c in NUM_COLS:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

# 小工具：讓空/缺資料更好顯示
def safe_str(x, default="無"):
    x = str(x) if x is not None else default
    return x if x.strip() else default

def clip_text(s, n=140):
    s = safe_str(s, "")
    return (s[:n] + "…") if len(s) > n else s

# =========================
# 1) 側邊欄：篩選器
# =========================
st.sidebar.title("🏫 全台招生 GEO/AI 戰情室")

college_list = ["全部學院"] + sorted(df["College"].unique().tolist())
selected_college = st.sidebar.selectbox("STEP 1: 選擇學院", college_list)

if selected_college == "全部學院":
    dept_options = ["全校總覽"] + sorted(df["Department"].unique().tolist())
else:
    dept_options = ["學院總覽"] + sorted(df[df["College"] == selected_college]["Department"].unique().tolist())
selected_dept = st.sidebar.selectbox("STEP 2: 選擇科系/視角", dept_options)

# 額外：篩選意圖（Keyword_Type）
kw_types = ["全部意圖"] + sorted(df["Keyword_Type"].unique().tolist())
selected_kw_type = st.sidebar.selectbox("STEP 3: 篩選搜尋意圖", kw_types)

# 額外：只看高分
min_ai = st.sidebar.slider("AI_Potential 最低門檻", 0, 100, 0, 5)
min_opp = st.sidebar.slider("Opportunity_Score 最低門檻", 0, int(max(1, df["Opportunity_Score"].max())), 0, 10)

# =========================
# 2) 資料集篩選
# =========================
target_df = df.copy()

if selected_college != "全部學院":
    target_df = target_df[target_df["College"] == selected_college]

if selected_kw_type != "全部意圖":
    target_df = target_df[target_df["Keyword_Type"] == selected_kw_type]

target_df = target_df[target_df["AI_Potential"] >= min_ai]
target_df = target_df[target_df["Opportunity_Score"] >= min_opp]

# =========================
# 3) 總覽頁
# =========================
def overview_page(scope_df, title_prefix):
    st.title(f"📊 {title_prefix}：GEO/AI 戰略地圖")

    # KPI 卡片
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("關鍵字筆數", int(len(scope_df)))
    with c2:
        st.metric("平均 AI_Potential", round(scope_df["AI_Potential"].mean(), 1) if len(scope_df) else 0)
    with c3:
        st.metric("平均 Opportunity", round(scope_df["Opportunity_Score"].mean(), 1) if len(scope_df) else 0)
    with c4:
        st.metric("平均 Citable_Score", round(scope_df["Citable_Score"].mean(), 1) if len(scope_df) else 0)

    st.divider()

    colA, colB = st.columns([2, 1])

    with colA:
        # 用 Opportunity_Score 平均做排行（比 Search_Volume 更貼近 GEO）
        dept_rank = (
            scope_df.groupby("Department", as_index=False)["Opportunity_Score"]
            .mean()
            .sort_values("Opportunity_Score", ascending=False)
        )
        fig = px.bar(dept_rank, x="Department", y="Opportunity_Score",
                     color="Department", title="各系 GEO 機會值排行（平均）")
        st.plotly_chart(fig, use_container_width=True)

    with colB:
        fig2 = px.pie(scope_df, names="Keyword_Type", title="搜尋意圖分佈")
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    colC, colD = st.columns(2)
    with colC:
        # AI_Potential 分佈
        fig3 = px.histogram(scope_df, x="AI_Potential", nbins=20, title="AI_Potential 分佈")
        st.plotly_chart(fig3, use_container_width=True)

    with colD:
        # Citable vs Authority 的散點圖：越右越上越好
        fig4 = px.scatter(
            scope_df,
            x="Authority_Count",
            y="Citable_Score",
            size="Opportunity_Score",
            hover_data=["Department", "Keyword", "Rank1_Title"],
            title="可引用性（Citable） vs 權威來源數（Authority）"
        )
        st.plotly_chart(fig4, use_container_width=True)

    st.divider()
    st.subheader("📋 熱點關鍵字總表（可排序/篩選）")

    show_cols = [
        "College", "Department", "Keyword", "Keyword_Type",
        "Opportunity_Score", "AI_Potential",
        "Citable_Score", "Authority_Count", "Forum_Count",
        "Rank1_Title"
    ]
    # 確保欄位存在
    show_cols = [c for c in show_cols if c in scope_df.columns]
    st.dataframe(
        scope_df[show_cols].sort_values(["Opportunity_Score", "AI_Potential"], ascending=False),
        use_container_width=True,
        height=520
    )

# 觸發總覽
if "總覽" in selected_dept:
    if selected_dept == "全校總覽":
        overview_page(target_df, "全校")
    else:
        overview_page(target_df, selected_college)

# =========================
# 4) 單一科系頁
# =========================
else:
    st.title(f"🔍 {selected_dept}：競品 + GEO/AI 可引用性戰情室")

    dept_df = target_df[target_df["Department"] == selected_dept].copy()
    if dept_df.empty:
        st.warning("這個篩選條件下沒有資料。請放寬左側門檻或改選其他意圖/學院。")
        st.stop()

    # 依機會值排序
    dept_df = dept_df.sort_values(["Opportunity_Score", "AI_Potential"], ascending=False)

    # KPI 列
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.metric("關鍵字筆數", int(len(dept_df)))
    with k2:
        st.metric("平均 Opportunity", round(dept_df["Opportunity_Score"].mean(), 1))
    with k3:
        st.metric("平均 AI_Potential", round(dept_df["AI_Potential"].mean(), 1))
    with k4:
        st.metric("平均 Citable", round(dept_df["Citable_Score"].mean(), 1))
    with k5:
        st.metric("平均 Authority", round(dept_df["Authority_Count"].mean(), 1))

    st.divider()

    # (A) 小圖：Opportunity vs Keyword_Type
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

    # (B) 關鍵字選擇區
    st.subheader("🕵️ 選擇關鍵字，查看 SERP Top 3 與 GEO 特徵")

    dept_df["Display_Label"] = dept_df["Keyword"] + " [" + dept_df["Keyword_Type"] + "]"
    target_label = st.selectbox("請選擇關鍵字", dept_df["Display_Label"].unique())
    target_row = dept_df[dept_df["Display_Label"] == target_label].iloc[0]

    kw = safe_str(target_row["Keyword"])
    strategy = safe_str(target_row["Strategy_Tag"])
    kw_type = safe_str(target_row["Keyword_Type"])

    st.divider()
    col_l, col_r = st.columns([1, 2])

    # 左側：指標卡 + 威脅判定
    with col_l:
        st.metric("Opportunity_Score", round(float(target_row["Opportunity_Score"]), 1))
        st.metric("AI_Potential", int(target_row["AI_Potential"]))
        st.metric("Citable_Score", round(float(target_row["Citable_Score"]), 1))
        st.metric("Authority_Count", int(target_row["Authority_Count"]))
        st.metric("Forum_Count", int(target_row["Forum_Count"]))

        # 結構化提示
        st.caption("🔎 結構化特徵（越多越容易被 AI 引用）")
        s_cols = st.columns(4)
        s_cols[0].metric("FAQ", int(target_row["Has_FAQ"]))
        s_cols[1].metric("Table", int(target_row["Has_Table"]))
        s_cols[2].metric("List", int(target_row["Has_List"]))
        s_cols[3].metric("H2/H3", int(target_row["Has_Headings"]))

        st.info(f"💡 建議策略：{strategy}")

        # 威脅度判斷（更穩健：Top1 + Competitor_Hit）
        top1_title = safe_str(target_row["Rank1_Title"])
        comp_hit = safe_str(target_row.get("Competitor_Hit", "無"))

        if any(x in top1_title for x in ["Dcard", "PTT"]):
            st.error("🔴 首位威脅：社群輿論（需澄清/FAQ）")
        elif any(x in top1_title for x in ["中華醫事", "華醫"]):
            st.success("🟢 首位：本校佔位（維持/補強可引用性）")
        elif comp_hit != "無":
            st.warning(f"🟡 首位：競品佔位（命中：{comp_hit}）")
        else:
            st.warning("🟡 首位：非本校來源（需超越）")

    # 右側：SERP Top3 展示 + 競品摘要注入
    with col_r:
        st.markdown(f"### 👀 「{kw}」的 Top 3 結果摘要")
        competitor_info_text = ""
        for i in range(1, 4):
            title = safe_str(target_row.get(f"Rank{i}_Title", "無"))
            link = safe_str(target_row.get(f"Rank{i}_Link", "#"))
            snippet = safe_str(target_row.get(f"Rank{i}_Snippet", ""))

            if title != "無":
                competitor_info_text += f"{i}. 標題：{title}\n   摘要：{clip_text(snippet, 120)}\n"

                with st.container(border=True):
                    st.markdown(f"**#{i} [{title}]({link})**")
                    if snippet.strip():
                        st.caption(clip_text(snippet, 220))

    st.divider()

    # (C) AI 文案生成器（GEO/AI 版）
    st.subheader("✍️ AI 智能文案生成器（GEO/AI 可引用性版）")
    st.markdown("已自動讀取 Top 3 摘要 + GEO 指標。請選擇模板後複製 Prompt。")

    template_type = st.radio(
        "選擇文章撰寫風格：",
        [
            "⚔️ 強力競爭型（內容缺口 + 反超 Top1）",
            "❤️ 軟性溝通型（社群疑慮澄清 + 口碑）",
            "🏆 權威數據型（出路/薪資/制度 + 引用）",
            "🤖 AI 摘要友善型（FAQ/表格/條列/可引用）"
        ],
        horizontal=True
    )

    base_instruction = ""
    structure_req = ""

    # 依模板注入「你目前的 GEO 觀測」
    geo_hint = (
        f"- 目前：AI_Potential={int(target_row['AI_Potential'])}、Citable_Score={round(float(target_row['Citable_Score']),1)}、"
        f"Authority_Count={int(target_row['Authority_Count'])}、Forum_Count={int(target_row['Forum_Count'])}\n"
        f"- 結構化：FAQ={int(target_row['Has_FAQ'])}、Table={int(target_row['Has_Table'])}、"
        f"List={int(target_row['Has_List'])}、H2/H3={int(target_row['Has_Headings'])}\n"
        f"- 競品命中：{safe_str(target_row.get('Competitor_Hit','無'))}\n"
    )

    if "強力競爭型" in template_type:
        base_instruction = (
            "請先從 Top 3 內容摘要中找出「內容缺口（Content Gap）」與「可被攻破的弱點」。"
            "接著用更完整、更結構化、更可引用的方式，寫出能反超 Top1 的文章。"
        )
        structure_req = (
            "1) **競品差異表**：用 Markdown 表格比較「本校 vs Top1」在課程、實習、證照、設備、就業上的差異。\n"
            "2) **內容缺口填補**：列出 Top1 沒講、但學生很在意的 5 個點並補齊。\n"
            "3) **證據段落**：每個主張都要給『可引用來源類型』提示（例如：系網/招生簡章/政府或公會資訊）。"
        )

    elif "軟性溝通型" in template_type:
        base_instruction = (
            "Top 結果若含 Dcard/PTT，可能有情緒化或片面內容。"
            "請用『學長姐分享/系辦解答』口吻，先同理，再用事實澄清。"
        )
        structure_req = (
            "1) **迷思破解**：列 3 個常見誤解（累不累、好考嗎、出路窄不窄）逐條回應。\n"
            "2) **過來人案例**：給 1 個具體情境（選課/實習/考照/找工作）。\n"
            "3) **安心清單**：給新生/家長的 7 點準備清單（含學習、時間管理、資源）。"
        )

    elif "權威數據型" in template_type:
        base_instruction = (
            "文章要以『可驗證的數據與制度』建立權威，降低主觀爭議。"
            "請明確標示年份與資料來源類型（例如：104、考選部、校方招生資訊）。"
        )
        structure_req = (
            "1) **出路地圖**：用表格列出醫院/檢驗所/生技/研究所等路徑與工作內容。\n"
            "2) **薪資區間**：用『區間/職務/年資』描述（避免單一數字誤導）。\n"
            "3) **制度與資格**：若涉及國考/證照，列出報考要件與準備方向（附官方來源類型）。"
        )

    else:  # 🤖 AI 摘要友善型
        base_instruction = (
            "請把文章寫成『AI 摘要/引用最友善』的樣子："
            "先給結論，再用表格、條列、FAQ、步驟化內容。"
            "每一段都要能被直接摘錄引用。"
        )
        structure_req = (
            "1) **TL;DR 結論**：開頭用 5 行條列總結（AI 最常擷取）。\n"
            "2) **核心比較表**：至少 1 張 Markdown 表格（課程/實習/證照/出路/資源）。\n"
            "3) **FAQ（至少 6 題）**：用 Q/A 格式、回答 60–120 字，避免冗長。\n"
            "4) **資料來源提示**：每個表格/數據段落加上『建議引用來源』（例如：系網/招生簡章/公會/政府）。"
        )

    final_prompt = f"""
# Role
你是一位精通台灣技職教育與 GEO（Generative Engine Optimization）的 SEO 內容策略顧問。

# Task
請為「{selected_dept}」撰寫一篇針對關鍵字「{kw}」的高排名文章，目標同時兼顧：
- 傳統搜尋排名（SEO）
- 生成式引擎摘要/引用（GEO / AI Search）

# 🔍 Current Market Landscape (Top 3 SERP 摘要)
請先閱讀目前搜尋結果前三名內容摘要（這是你要超越的對手）：
{competitor_info_text}

# 📌 GEO Observations（本次戰情室觀測）
{geo_hint}
請根據上述指標推論：目前網路內容哪裡「可引用性不足」（例如缺表格/缺 FAQ/缺權威來源），並在你的文章補齊。

# 🎯 Writing Strategy（{template_type}）
{base_instruction}

# 🧱 Content Structure Requirements
{structure_req}

# Must-have
- 使用 Markdown（H2/H3 清楚分段）
- 內文 900–1200 字左右
- 文末提供 **CTA**（參訪/申請/瀏覽系網/聯絡方式）
- 若提到數據或制度，請加上「建議引用來源類型」（例如：學校系網、招生簡章、政府或公會資訊、104 等）

# Tone
專業、清楚、可信；避免空泛口號。
"""

    st.text_area("📋 請複製下方 Prompt 給 ChatGPT / Gemini / Claude：", final_prompt, height=520)
    st.success("✅ 已整合 Top3 競品摘要 + GEO 指標。建議優先用『🤖 AI 摘要友善型』做第一版，再做競品攻防版。")

    st.divider()
    st.subheader("🧾 本系關鍵字清單（可排序）")
    table_cols = [
        "Keyword", "Keyword_Type", "Opportunity_Score", "AI_Potential",
        "Citable_Score", "Authority_Count", "Forum_Count",
        "Rank1_Title"
    ]
    st.dataframe(
        dept_df[table_cols].sort_values(["Opportunity_Score", "AI_Potential"], ascending=False),
        use_container_width=True,
        height=420
    )

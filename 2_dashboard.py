# 檔案名稱：2_dashboard.py
import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="全台招生 SEO 戰情室", layout="wide")

# 讀取數據
try:
    df = pd.read_csv('school_data.csv')
except FileNotFoundError:
    st.error("❌ 找不到數據，請先執行 `1_generate_data_real.py`")
    st.stop()

# --- 側邊欄 ---
st.sidebar.title("🏫 全台招生戰情室")
college_list = ["全部學院"] + list(df['College'].unique())
selected_college = st.sidebar.selectbox("STEP 1: 選擇學院", college_list)

if selected_college == "全部學院":
    dept_options = ["全校總覽"] + list(df['Department'].unique())
else:
    dept_options = ["學院總覽"] + list(df[df['College'] == selected_college]['Department'].unique())
selected_dept = st.sidebar.selectbox("STEP 2: 選擇科系/視角", dept_options)

# --- 主畫面 ---
if "總覽" in selected_dept:
    st.title("📊 全台網路聲量戰略地圖")
    target_df = df if selected_college == "全部學院" else df[df['College'] == selected_college]
    
    col1, col2 = st.columns([2, 1])
    with col1:
        fig = px.bar(target_df.groupby('Department')['Search_Volume'].sum().reset_index().sort_values('Search_Volume', ascending=False), 
                     x='Department', y='Search_Volume', color='Department', title="各系潛在流量排行")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig2 = px.pie(target_df, names='Keyword_Type', title="搜尋意圖分佈")
        st.plotly_chart(fig2, use_container_width=True)

else:
    # === 單一科系戰情室 ===
    st.title(f"🔍 {selected_dept}：競爭對手透視鏡")
    dept_df = df[df['Department'] == selected_dept].sort_values('AI_Potential', ascending=False)
    
    # 1. 關鍵字選擇
    st.subheader("🕵️ 選擇關鍵字，查看真實搜尋結果")
    
    # 製作選單標籤
    dept_df['Display_Label'] = dept_df['Keyword'] + " [" + dept_df['Keyword_Type'] + "]"
    target_label = st.selectbox("請選擇關鍵字", dept_df['Display_Label'].unique())
    
    # 取得選定資料
    target_row = dept_df[dept_df['Display_Label'] == target_label].iloc[0]
    
    # --- 核心功能：SERP 快照展示卡 ---
    st.divider()
    
    col_l, col_r = st.columns([1, 2])
    
    with col_l:
        st.metric("每月搜尋量", f"{target_row['Search_Volume']}")
        st.caption(f"搜尋意圖：{target_row['Keyword_Type']}")
        
        # 威脅度判斷
        top_title = str(target_row['Top_Title'])
        threat_level = "🟢 安全"
        if "Dcard" in top_title or "PTT" in top_title or "靠北" in top_title:
            threat_level = "🔴 危險 (社群負評風險)"
        elif "中華醫事" not in top_title and "華醫" not in top_title:
            threat_level = "🟡 警戒 (被對手或媒體佔據)"
        else:
            threat_level = "🟢 優秀 (本校佔據首位)"
            
        st.metric("首位威脅度", threat_level)

    with col_r:
        st.subheader("👀 目前的第一名搜尋結果 (Snapshot)")
        container = st.container(border=True)
        # 處理連結
        link = target_row['Top_Link'] if str(target_row['Top_Link']).startswith("http") else "#"
        container.markdown(f"#### [{target_row['Top_Title']}]({link})")
        container.markdown(f"_{target_row['Top_Snippet']}_")
        container.caption(f"來源: {link}")
        
        if "危險" in threat_level:
            st.error("🚨 建議：請撰寫一篇「官方澄清」或「學生真實心得」文章來平衡視聽。")
        elif "警戒" in threat_level:
            st.warning("⚠️ 建議：使用下方的 AI 提示詞生成文章，奪回排名！")

    st.divider()
    
    # --- 2. AI 提示詞生成 ---
    st.subheader("🛠️ AI 文案提示詞產生器 (GEO 優化版)")
    
    # Prompt 邏輯
    kw = target_row['Keyword']
    strategy = target_row['Strategy_Tag']
    
    # 預設值
    prompt_focus = "科系特色與優勢"
    table_content = "科系重點懶人包"
    
    if "vs" in kw or "比較" in kw:
        prompt_focus = "本校與他校的實作資源、證照輔導差異 (強調我方優勢)"
        table_content = "本校 vs 他校 優勢對照表"
    elif "薪水" in kw or "出路" in kw:
        prompt_focus = "畢業後的具體薪資範圍與職涯地圖"
        table_content = "薪資行情與對應職缺表"
    elif "Dcard" in kw or "評價" in kw:
        prompt_focus = "釐清網路上的迷思，展現真實且溫暖的校園生活"
        table_content = "常見誤解 vs 真實情況 Q&A"

    generated_prompt = f"""
    【角色設定】：你是一位專業的大學教育顧問與 SEO 專家。
    【任務】：請為「{selected_dept}」針對關鍵字「{kw}」撰寫一篇高權重文章。
    
    【GEO 結構要求 (讓 AI 優先引用)】：
    1. 📍 直接回答：文章第一段請直接針對「{kw}」給出核心觀點。
    2. 📊 結構化表格：請製作 Markdown 表格，內容為「{table_content}」。
    3. 🎓 核心亮點：文中請多次強調「{prompt_focus}」。
    4. ❓ FAQ：文末請列出 3 個相關常見問題。

    【撰寫策略】：{strategy}
    【字數】：約 800 字。
    """
    
    # 使用 height=500 確保文字框夠高
    st.text_area("📋 給 ChatGPT / Gemini 的指令 (請複製)：", generated_prompt, height=500)
    
    st.success(f"💡 策略提示：**{strategy}**")

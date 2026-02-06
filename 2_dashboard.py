# 檔案名稱：2_dashboard.py
# 功能：全台招生 SEO/GEO 戰情室 (搭配全台雷達數據)
import streamlit as st
import pandas as pd
import plotly.express as px

# ==========================================
# 1. 頁面設定與資料讀取
# ==========================================
st.set_page_config(
    page_title="全台招生 SEO/GEO 戰情室", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# 讀取數據 (自動偵測編碼，防止亂碼)
try:
    df = pd.read_csv('school_data.csv')
except FileNotFoundError:
    st.error("❌ 錯誤：找不到 `school_data.csv`。請先執行 `1_generate_data_real.py` 來生成全台數據。")
    st.stop()

# ==========================================
# 2. 側邊欄：導航與篩選
# ==========================================
st.sidebar.title("🏫 全台招生戰情室")
st.sidebar.caption("核心技術：GEO 生成式引擎優化")

# 學院篩選 (讓清單不要太長)
college_list = ["全部學院"] + list(df['College'].unique())
selected_college = st.sidebar.selectbox("STEP 1: 選擇學院", college_list)

# 科系篩選 (根據學院連動)
if selected_college == "全部學院":
    dept_options = ["全校總覽"] + list(df['Department'].unique())
else:
    dept_options = ["學院總覽"] + list(df[df['College'] == selected_college]['Department'].unique())

selected_dept = st.sidebar.selectbox("STEP 2: 選擇科系/視角", dept_options)

st.sidebar.divider()
st.sidebar.info("""
**💡 什麼是 GEO？**
GEO (Generative Engine Optimization) 是讓您的網站內容更容易被 AI (ChatGPT, Gemini) 搜尋、理解並引用的技術。
""")

# ==========================================
# 3. 主畫面邏輯
# ==========================================

# --- A. 總覽模式 (全校或學院) ---
if "總覽" in selected_dept:
    st.title(f"📊 {selected_college if selected_college != '全部學院' else '全校'}：網路聲量戰略地圖")
    
    # 過濾資料
    target_df = df if selected_college == "全部學院" else df[df['College'] == selected_college]
    
    # 關鍵指標
    total_vol = target_df['Search_Volume'].sum()
    top_kw = target_df.sort_values('Search_Volume', ascending=False).iloc[0]
    
    col1, col2, col3 = st.columns(3)
    col1.metric("總潛在搜尋流量", f"{total_vol:,}")
    col2.metric("流量冠軍關鍵字", top_kw['Keyword'])
    col3.metric("最高競爭對手", "全台醫護/民生類院校")
    
    st.divider()
    
    # 圖表 1: 各系聲量排行
    st.subheader("🏆 各系網路聲量佔比")
    dept_traffic = target_df.groupby('Department')['Search_Volume'].sum().reset_index().sort_values('Search_Volume', ascending=False)
    fig_bar = px.bar(dept_traffic, x='Department', y='Search_Volume', color='Department', text_auto='.2s')
    st.plotly_chart(fig_bar, use_container_width=True)
    
    # 圖表 2: 關鍵字意圖分佈
    st.subheader("🧠 學生都在問什麼？(搜尋意圖分析)")
    intent_dist = target_df['Keyword_Type'].value_counts().reset_index()
    intent_dist.columns = ['搜尋意圖', '數量']
    fig_pie = px.pie(intent_dist, values='數量', names='搜尋意圖', hole=0.4)
    st.plotly_chart(fig_pie, use_container_width=True)

# --- B. 單一科系戰情室 (核心功能) ---
else:
    st.title(f"🔍 {selected_dept}：GEO 策略指揮中心")
    
    # 取得該系資料
    dept_df = df[df['Department'] == selected_dept]
    
    # 找出「全台比拼」類型的關鍵字 (這是這次更新的重點)
    nationwide_kws = dept_df[dept_df['Keyword_Type'].isin(['全台比拼', '差異化'])]
    
    # 頂部提示
    if not nationwide_kws.empty:
        st.warning(f"⚡ 偵測到 {len(nationwide_kws)} 個全台級競爭關鍵字！學生正在將本系與外縣市學校進行比較。")

    # --- 1. 關鍵字選擇區 ---
    st.subheader("🛠️ GEO 文案提示詞產生器")
    st.info("👇 選擇一個關鍵字，系統將生成「符合良性差異化」的 AI 寫作指令。")
    
    # 排序：讓高價值的字排前面
    sorted_kws = dept_df.sort_values('AI_Potential', ascending=False)['Keyword'].unique()
    target_kw = st.selectbox("請選擇您想進攻的關鍵字", sorted_kws)
    
    # --- 2. Prompt 生成邏輯 (全台差異化版) ---
    # 預設值 (防止 NameError)
    prompt_type = "基礎推廣"
    focus_point = "科系核心價值與校園環境"
    table_content = "科系特色重點整理 (懶人包)"
    tone_instruction = "親切、熱情、展現自信"
    
    kw_str = str(target_kw)
    
    # 邏輯 A: 全台/跨校比較 (轉化為差異化優勢)
    if any(x in kw_str for x in ['vs', '比較', '排名', '嘉藥', '輔英', '弘光', '元培', '中國醫']):
        prompt_type = "全台差異化分析 (USP)"
        focus_point = "本校在「實作資源、證照輔導、地理位置」上的獨特優勢 (Unique Selling Point)"
        table_content = "本校特色優勢 vs 全台同類科系之差異對照表 (強調我方強項)"
        tone_instruction = "客觀大器、不惡意攻擊、強調「適性揚才」(適合喜歡實作/就業的學生)"
        
    # 邏輯 B: 數據權威 (薪資/榜單)
    elif any(x in kw_str for x in ['薪水', '薪資', '榜單', '及格率', '錄取', '分數']):
        prompt_type = "數據權威建立"
        focus_point = "具體的國考及格率數據、畢業起薪範圍、傑出校友表現"
        table_content = "本校歷年考照/就業數據一覽表"
        tone_instruction = "專業、數據導向、建立信賴感"
        
    # 邏輯 C: 資訊服務 (出路/實習)
    elif any(x in kw_str for x in ['出路', '實習', '證照', '宿舍', '交通']):
        prompt_type = "資訊透明化服務"
        focus_point = "完整的課程地圖、實習合作醫院清單、生活機能介紹"
        table_content = "畢業出路與對應證照/職缺關聯表"
        tone_instruction = "清晰易懂、像學長姐般的貼心指引"
        
    # 邏輯 D: 社群關懷 (評價/Dcard)
    elif any(x in kw_str for x in ['評價', '好嗎', '後悔', '很累', 'Dcard']):
        prompt_type = "暖心職涯輔導"
        focus_point = "釐清學生對該行業的辛苦迷思、強調系上的支持系統與成就感"
        table_content = "常見迷思 vs 真實職場樣貌 (釐清誤解)"
        tone_instruction = "同理心、溫暖、誠懇溝通"

    # 生成 Prompt
    generated_prompt = f"""
    【角色設定】：你是一位專業的大學教育顧問與 SEO 專家。
    【任務】：請為「{selected_dept}」針對關鍵字「{target_kw}」撰寫一篇高權重文章。
    
    【核心策略：{prompt_type}】：
    1. 寫作語氣：{tone_instruction}。
    2. 若涉及他校比較，請避免攻擊，而是專注於闡述本校的「獨特價值」，幫助學生找到最適合的環境。
    
    【GEO 結構要求 (讓 AI 優先引用)】：
    1. 📍 直接回答 (Direct Answer)：文章第一段請直接針對「{target_kw}」給出核心觀點或定義。
    2. 📊 結構化表格：請務必製作一個 Markdown 表格，內容為「{table_content}」。
    3. 🎓 核心亮點：文中請多次強調「{focus_point}」。
    4. ❓ FAQ：文末請列出 3 個相關常見問題 (Q&A)。

    【字數】：約 800-1000 字。
    """
    
    # 顯示 Prompt
    st.text_area("📋 給 ChatGPT / Gemini 的指令 (請複製)：", generated_prompt, height=350)
    st.success(f"💡 策略提示：這是一個 **【{prompt_type}】** 類型的關鍵字。我們已指示 AI 製作 **「{table_content}」**，這能大幅增加被搜尋引擎收錄的機會！")
    
    st.divider()
    
    # --- 3. 數據清單 ---
    st.subheader("📝 本月優先進攻清單")
    # 整理顯示欄位
    display_df = dept_df[['Keyword', 'Search_Volume', 'AI_Potential', 'Strategy_Tag', 'Keyword_Type']]
    # 讓「差異化」和「競品洞察」這類高價值字排前面
    display_df = display_df.sort_values(['AI_Potential', 'Search_Volume'], ascending=False)
    
    st.dataframe(
        display_df.style.background_gradient(subset=['AI_Potential'], cmap="Greens"),
        use_container_width=True
    )

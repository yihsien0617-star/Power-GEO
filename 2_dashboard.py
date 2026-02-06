# 檔案名稱：2_dashboard.py (競品情報注入 + 多模板提示詞版)
import streamlit as st
import pandas as pd
import plotly.express as px
from collections import Counter

st.set_page_config(page_title="全台招生 SEO 戰情室", layout="wide")

# 讀取數據
try:
    df = pd.read_csv('school_data.csv')
    # 確保字串欄位不會因為空值報錯
    df = df.fillna("無")
except FileNotFoundError:
    st.error("❌ 找不到數據，請先執行 `powergeo.py`")
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

# 輔助函數
def extract_schools_from_titles(titles):
    school_keywords = ["華醫", "中華醫事", "嘉藥", "嘉南", "輔英", "弘光", "元培", "中臺", "慈濟", "長庚", "北護", "中山醫", "中國醫", "Dcard", "PTT", "104"]
    detected = []
    for title in titles:
        if title == "無": continue
        found = False
        for sk in school_keywords:
            if sk in title:
                detected.append(sk)
                found = True
                break
        if not found: detected.append("其他")
    return detected

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
    
    st.divider()
    st.subheader("📋 熱搜關鍵字總表")
    st.dataframe(target_df[['Department', 'Keyword', 'Search_Volume', 'Rank1_Title']], use_container_width=True)

else:
    # === 單一科系戰情室 ===
    st.title(f"🔍 {selected_dept}：競爭對手透視鏡")
    # 將 AI 潛力高的排前面
    dept_df = df[df['Department'] == selected_dept]
    if 'AI_Potential' in dept_df.columns:
        dept_df = dept_df.sort_values('AI_Potential', ascending=False)
    
    # 1. 關鍵字選擇區
    st.subheader("🕵️ 選擇關鍵字，查看 Top 3 搜尋結果")
    
    dept_df['Display_Label'] = dept_df['Keyword'] + " [" + dept_df['Keyword_Type'] + "]"
    target_label = st.selectbox("請選擇關鍵字", dept_df['Display_Label'].unique())
    target_row = dept_df[dept_df['Display_Label'] == target_label].iloc[0]
    
    # --- 核心功能：SERP Top 3 展示 ---
    st.divider()
    col_l, col_r = st.columns([1, 2])
    
    with col_l:
        st.metric("每月搜尋量", f"{target_row['Search_Volume']}")
        st.info(f"💡 建議策略：{target_row['Strategy_Tag']}")
        
        # 威脅度判斷
        top1_title = str(target_row['Rank1_Title'])
        if "Dcard" in top1_title or "PTT" in top1_title:
            st.error("🔴 首位威脅：社群輿論 (需澄清)")
        elif "中華醫事" in top1_title or "華醫" in top1_title:
            st.success("🟢 首位威脅：本校 (安全)")
        else:
            st.warning("🟡 首位威脅：競爭對手 (需超越)")

    with col_r:
        st.markdown(f"### 👀 「{target_row['Keyword']}」的前三名對手")
        competitor_info_text = ""  # 用來存給 AI 看的競品資料
        
        for i in range(1, 4):
            title = target_row[f'Rank{i}_Title']
            link = target_row[f'Rank{i}_Link']
            snippet = str(target_row[f'Rank{i}_Snippet'])
            
            if title != "無":
                # 收集資料給 Prompt 使用
                competitor_info_text += f"{i}. 標題：{title}\n   摘要：{snippet[:80]}...\n"
                
                with st.container(border=True):
                    st.markdown(f"**#{i} [{title}]({link})**")
                    st.caption(snippet[:100] + "..." if len(snippet)>100 else snippet)

    st.divider()

    # --- 2. AI 文案生成器 (大幅升級版) ---
    st.subheader("✍️ AI 智能文案生成器 (競品分析版)")
    st.markdown("系統已自動讀取上方 Top 3 搜尋結果，請選擇您想要的撰寫模板：")
    
    kw = target_row['Keyword']
    strategy = target_row['Strategy_Tag']
    
    # 讓使用者選擇模板
    template_type = st.radio(
        "選擇文章撰寫風格：",
        ["⚔️ 強力競爭型 (針對對手弱點)", "❤️ 軟性溝通型 (針對 Dcard/PTT)", "🏆 權威數據型 (強調榜單/薪資)"],
        horizontal=True
    )
    
    # 根據模板與搜尋結果動態調整指令
    base_instruction = ""
    structure_req = ""
    
    if "強力競爭型" in template_type:
        base_instruction = "請仔細分析上述 Top 3 競爭對手的內容，找出他們沒提到的『內容缺口』(Content Gap)。文章必須強調本校在『實作資源、證照通過率、交通便利性』優於對手之處。"
        structure_req = "1. **競品差異表**：製作一張 Markdown 表格，直接比較本校 vs Top 1 學校的優勢。\n2. **獨家優勢**：列出 3 點對手沒提到但本校有的特色。"
    
    elif "軟性溝通型" in template_type:
        base_instruction = "目前搜尋結果前幾名包含社群論壇 (Dcard/PTT)，可能含有主觀或片面資訊。請以『學長姐分享』或『系學會解答』的溫暖口吻，針對學生常見的焦慮（如：很累、好考嗎）進行澄清與鼓勵。"
        structure_req = "1. **迷思破解**：列出網路上常見的 3 個誤解並給予真實回應。\n2. **過來人經驗**：分享一個具體的學生成功案例。"
    
    elif "權威數據型" in template_type:
        base_instruction = "針對家長與學生最在意的『出路與薪資』，文章必須引用具體數據（如 104 人力銀行、考選部榜單），建立專業權威感。語氣要自信、專業。"
        structure_req = "1. **薪資地圖**：製作表格列出畢業 1/3/5 年的平均薪資變化。\n2. **考照數據**：強調本校國考及格率高於全國平均的具體數字。"

    # 組合終極 Prompt
    final_prompt = f"""
# Role
你是一位精通台灣技職教育體系的 SEO 內容行銷專家。

# Task
請為「{selected_dept}」撰寫一篇針對關鍵字「{kw}」的高排名文章。

# 🔍 Current Market Landscape (目前搜尋結果 Top 3)
為了贏過競爭對手，請先閱讀目前 Google 前三名的內容摘要：
{competitor_info_text}
⚠️ 你的任務是寫出一篇**資訊量比上述三者更豐富、觀點更獨特**的文章，以搶佔排名。

# 🎯 Writing Strategy ({template_type})
{base_instruction}

# 📝 Content Structure Requirements
{structure_req}
3. **FAQ 常見問答**：文末請根據搜尋意圖，列出 3 個 User 最想問的問題並回答。
4. **Call to Action**：引導讀者報名參訪或瀏覽系網。

# Constraints
- 字數：約 800-1000 字。
- 格式：使用 Markdown 語法，標題清晰。
- 語氣：符合「{selected_dept}」的專業形象。
    """
    
    st.text_area("📋 請複製下方指令給 ChatGPT / Gemini / Claude：", final_prompt, height=450)
    st.success("💡 提示：此 Prompt 已包含「競品內容摘要」，AI 將會針對對手的內容進行「降維打擊」！")

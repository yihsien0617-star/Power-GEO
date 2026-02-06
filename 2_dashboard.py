# 檔案名稱：2_dashboard.py (全台版圖分析版)
import streamlit as st
import pandas as pd
import plotly.express as px
from collections import Counter
import re

st.set_page_config(page_title="全台招生 SEO 戰情室", layout="wide")

try:
    df = pd.read_csv('school_data.csv')
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

# ==========================================
# 輔助函數：提取標題中的學校名稱
# ==========================================
def extract_schools_from_titles(titles):
    # 定義要偵測的學校關鍵字 (包含簡稱)
    school_keywords = [
        "華醫", "中華醫事", "嘉藥", "嘉南", "輔英", "弘光", "元培", "中臺", "慈濟", 
        "長庚", "北護", "國北護", "中山醫", "中國醫", "高醫", "樹人", "美和", 
        "亞大", "亞洲大學", "大仁", "高餐", "台南應用", "Dcard", "PTT", "104", "1111"
    ]
    detected = []
    for title in titles:
        if pd.isna(title): continue
        found = False
        for sk in school_keywords:
            if sk in title:
                # 統一名稱
                name = sk
                if name in ["華醫", "中華醫事"]: name = "中華醫事 (本校)"
                elif name in ["嘉藥", "嘉南"]: name = "嘉南藥理"
                elif name in ["北護", "國北護"]: name = "國北護"
                elif name in ["亞大", "亞洲大學"]: name = "亞洲大學"
                detected.append(name)
                found = True
                break # 一個標題只算一次主要學校
        if not found:
            detected.append("其他/一般資訊")
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
    
    # 全國版圖分析 (總覽頁)
    st.divider()
    st.subheader("🗺️ 全國版圖：誰佔據了搜尋結果 Top 1？")
    all_top1_titles = target_df['Rank1_Title'].tolist()
    school_counts = Counter(extract_schools_from_titles(all_top1_titles))
    top_schools_df = pd.DataFrame(school_counts.items(), columns=['單位', '佔據首位次數']).sort_values('佔據首位次數', ascending=False)
    
    st.bar_chart(top_schools_df.set_index('單位'))
    st.caption("此圖表顯示在所有關鍵字搜尋中，各大學（或平台）出現在「第一名」的次數。這能反映真實的市場佔有率。")

else:
    # === 單一科系戰情室 ===
    st.title(f"🔍 {selected_dept}：競爭對手透視鏡")
    dept_df = df[df['Department'] == selected_dept].sort_values('AI_Potential', ascending=False)
    
    # 1. 關鍵字選擇
    st.subheader("🕵️ 選擇關鍵字，查看 Top 3 搜尋結果")
    dept_df['Display_Label'] = dept_df['Keyword'] + " [" + dept_df['Keyword_Type'] + "]"
    target_label = st.selectbox("請選擇關鍵字", dept_df['Display_Label'].unique())
    target_row = dept_df[dept_df['Display_Label'] == target_label].iloc[0]
    
    st.divider()
    
    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.metric("每月搜尋量", f"{target_row['Search_Volume']}")
        st.info(f"💡 策略：{target_row['Strategy_Tag']}")
        
        top1 = str(target_row['Rank1_Title'])
        if "Dcard" in top1 or "PTT" in top1:
            st.error("🔴 首位威脅：社群輿論")
        elif "中華醫事" in top1 or "華醫" in top1:
            st.success("🟢 首位威脅：本校 (安全)")
        else:
            st.warning("🟡 首位威脅：競爭對手/媒體")

    with col_r:
        st.markdown(f"### 👀 「{target_row['Keyword']}」搜尋結果快照")
        for i in range(1, 4):
            t = target_row[f'Rank{i}_Title']
            l = target_row[f'Rank{i}_Link']
            s = target_row[f'Rank{i}_Snippet']
            if t != "無":
                with st.container(border=True):
                    st.markdown(f"**#{i} [{t}]({l})**")
                    st.caption(s[:100] + "..." if len(s)>100 else s)

    st.divider()
    
    # 2. 全台競爭者分析圖表 (科系層級)
    st.subheader(f"⚔️ {selected_dept} 的主要競爭對手分析")
    st.write("統計本系所有關鍵字的前三名搜尋結果，找出最常出現的對手：")
    
    # 收集前三名的所有標題
    all_titles = dept_df['Rank1_Title'].tolist() + dept_df['Rank2_Title'].tolist() + dept_df['Rank3_Title'].tolist()
    dept_school_counts = Counter(extract_schools_from_titles(all_titles))
    
    # 轉成圖表數據
    chart_data = pd.DataFrame(dept_school_counts.items(), columns=['競爭對手/平台', '出現頻率']).sort_values('出現頻率', ascending=False)
    # 過濾掉「其他」以免干擾視覺
    chart_data = chart_data[chart_data['競爭對手/平台'] != '其他/一般資訊']
    
    st.bar_chart(chart_data.set_index('競爭對手/平台'), color="#FF6C6C")
    st.caption("數據解讀：如果「嘉南藥理」的柱狀圖很高，代表學生搜尋本系相關關鍵字時，很容易看到嘉藥的網頁。")

    # 3. 總表
    st.subheader("📋 關鍵字詳細數據總表")
    st.dataframe(dept_df[['Keyword', 'Search_Volume', 'Keyword_Type', 'Rank1_Title']], use_container_width=True)

    # 4. AI 生成
    with st.expander("🛠️ 開啟 AI 文案生成器"):
        kw = target_row['Keyword']
        prompt = f"請為{selected_dept}撰寫關於「{kw}」的SEO文章。策略：{target_row['Strategy_Tag']}。需包含表格與FAQ。"
        st.text_area("Prompt:", prompt, height=200)

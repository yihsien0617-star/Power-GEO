# 檔案名稱：2_dashboard.py
# 功能：全台招生 SEO 戰情室 + 搜尋結果預覽
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
    
    # 總覽圖表
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
    st.info("此處顯示的是該關鍵字在 Google 搜尋的 **第一名結果**。這就是學生看到的第一印象！")
    
    # 製作選單標籤 (加入意圖標示)
    dept_df['Display_Label'] = dept_df['Keyword'] + " (" + dept_df['Keyword_Type'] + ")"
    target_label = st.selectbox("請選擇關鍵字", dept_df['Display_Label'].unique())
    
    # 取得選定資料
    target_row = dept_df[dept_df['Display_Label'] == target_label].iloc[0]
    
    # --- 核心功能：SERP 快照展示卡 ---
    st.divider()
    
    col_l, col_r = st.columns([1, 2])
    
    with col_l:
        st.metric("每月搜尋量", f"{target_row['Search_Volume']}")
        st.caption(f"搜尋意圖：{target_row['Keyword_Type']}")
        
        # 根據結果判斷威脅程度
        threat_level = "🟢 安全"
        if "Dcard" in target_row['Top_Title'] or "PTT" in target_row['Top_Title']:
            threat_level = "🔴 危險 (社群討論中)"
        elif "中華醫事" not in target_row['Top_Title'] and "華醫" not in target_row['Top_Title']:
            threat_level = "🟡 警戒 (被對手或媒體佔據)"
        else:
            threat_level = "🟢 優秀 (本校佔據首位)"
            
        st.metric("首位威脅度", threat_level)

    with col_r:
        st.subheader("👀 目前的第一名搜尋結果 (Snapshot)")
        
        # 模擬 Google 搜尋結果卡片樣式
        container = st.container(border=True)
        container.markdown(f"#### [{target_row['Top_Title']}]({target_row['Top_Link']})")
        container.markdown(f"_{target_row['Top_Snippet']}_")
        container.caption(f"連結來源: {target_row['Top_Link']}")
        
        # 給主任的建議
        if "危險" in threat_level:
            st.error("🚨 **警報**：此關鍵字首位是社群論壇，內容可能不可控！建議撰寫一篇「官方澄清/懶人包」文章來擠下它。")
        elif "警戒" in threat_level:
            st.warning("⚠️ **注意**：此關鍵字首位不是本校網頁。請使用下方的 AI 提示詞生成文章，搶回排名！")
        else:
            st.success("✅ **做得好**：目前本校佔據首位，請繼續保持更新。")

    st.divider()
    
    # --- 2. AI 提示詞生成 (維持原有功能) ---
    with st.expander("🛠️ 點此開啟「AI 文章生成器」來搶回排名", expanded=False):
        # (這裡放入原本的 Prompt 生成代碼，簡化顯示)
        st.write(f"針對 **{target_row['Keyword']}** 的 GEO 撰寫策略：**{target_row['Strategy_Tag']}**")
        st.code(f"請為{selected_dept}撰寫關於{target_row['Keyword']}的文章...", language="text")

    # --- 3. 完整清單 ---
    st.subheader("📝 該系所有關鍵字快照一覽")
    st.dataframe(
        dept_df[['Keyword', 'Top_Title', 'Keyword_Type', 'Strategy_Tag']], 
        use_container_width=True,
        hide_index=True
    )

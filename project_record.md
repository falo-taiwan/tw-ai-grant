# 專案紀錄：台灣政府 AI 補助工具庫採集與結構化專案 (AI-Readable Version)

本專案旨在完整採集、清洗並標準化台灣兩個政府補助案之 AI 工具庫資料，建立一套可供企業級 AI 知識管理系統 (KM/RAG) 直接使用的結構化資料庫，並將整個逆向工程與爬蟲管線轉化為高品質的實戰教材。

---

## 1. 專案基本資訊與技術指標

*   **專案名稱**：台灣政府 AI 補助工具庫資料採集與知識庫化專案
*   **執行時間**：2026-06-24
*   **整合總筆數**：**224 筆** 結構化 AI 工具資料
*   **資料源分布**：
    *   **來源一**：經濟部產業競爭力輔導團 - AI工具庫 (`moeai-plus/ai-tools`) -> **79 筆**
    *   **來源二**：商業服務業數位轉型專區 - 智慧轉型方案 (`service-ai.php`) -> **145 筆**
*   **輸出格式**：
    *   JSON Database: `unified_ai_tools_db.json` (最適合向量檢檢索與 LLM RAG)
    *   CSV Database: `unified_ai_tools_db.csv` (適合 Excel 與傳統關聯式資料庫)

---

## 2. 爬蟲架構與技術決策

專案針對兩個架構截然不同的網站，採取了「雙軌最優化」的資料採集策略：

```
                                    [資料採集雙軌管線]
                                            |
                    +-----------------------+-----------------------+
                    |                                               |
         [來源一：動態 Vue 網頁]                         [來源二：傳統 PHP 伺服器渲染]
                    |                                               |
         [Chrome DevTools 逆向工程]                     [第一層：1~9 頁分頁列表爬取]
                    |                                               |
         [發現公開 Google Sheet ID]                       [抓取基本欄位 & 145 筆詳細頁連結]
                    |                                               |
         [利用 Visualization API 匯出]                   [第二層：詳細頁深層爬取 (no=xxx)]
                    |                                               |
            [下載並解析無損 CSV]                         [提取規格說明、案例效益、統編、聯絡信箱]
                    |                                               |
                    +-----------------------+-----------------------+
                                            |
                                    [資料清洗與欄位對齊]
                                            |
                                [Regex 提取價格/月數/聯絡資訊]
                                            |
                                [分類標籤標準化 & 輸出資料庫]
```

### 2.1 來源一的逆向工程策略
*   **發現**：分析前端 JavaScript 資源包（`useAITools.js`），發現底層資料並非來自專屬 API，而是公開的 Google Sheet (ID: `18Hq6sUrweHmm_08AcFPBnQ8XypXJ7CM6`)。
*   **優化**：繞過網頁 DOM 解析，利用 Google Sheet Visualization 接口直接匯出 CSV 格式。此舉規避了動態網頁加載延遲，並解決了 CSV 儲存格內含有換行符號（導致傳統按行讀取噴錯）的解析難題，確保 100% 原始資料完整度。

### 2.2 來源二的雙層爬蟲策略
*   **分頁爬取**：設定 `mindusty=-1` 排除行業篩選，在 9 個分頁中精確遍歷所有 145 個方案，提取基本卡片資料。
*   **深度爬取**：針對 145 個詳細頁網址（如 `service-content.php?no=...`）進行遍歷請求，解析出「方案規格說明」、「成功案例效益」等非結構化長文本。
*   **防錯機制**：在 HTTP 請求間設置 0.5 秒延遲（Politeness delay），保護政府伺服器，並防止 IP 被封鎖。

---

## 3. 資料清洗與 AI-Ready 規格設計

為了讓後續的大語言模型 (LLM) 檢索與向量資料庫 (Vector DB) 能夠精確過濾與語意檢索，我們對原始凌亂文字進行了深度清洗：

### 3.1 數值化轉換 (Normalization)
*   **價格數值化 (`price_amount`)**：利用正規表示式 (Regex) 移除千分位逗號，提取出純數字金額（如 `方案金額 : 102,375 (新台幣/含稅)` -> `102375`）。這使得知識庫系統可以執行「預算小於 5 萬元」的精確資料庫篩選。
*   **授權期程數值化 (`duration_months`)**：將 `12個月`、`6 (月)`、`使用月數 : 4` 等不同寫法，標準化為純數字月數（如 `12`、`6`、`4`）。

### 3.2 聯繫資訊與識別碼提取
*   **統一編號 (`provider_tax_id`)**：從詳細頁的企業資料區塊中提取出台灣 8 碼公司統一編號，方便後續與企業內部的 ERP/CRM 系統進行資料對接。
*   **聯絡信箱 (`contact_email`)**：從 `mailto:` 連結或純文本中利用 Regex 精確提取出乾淨的 Email 地址。

### 3.3 跨資料源分類標準化 (`category_standardized`)
將兩邊不一致的原始分類，統一對齊為 8 大 AI-Ready 類別：
1.  `人資與知識管理`
2.  `環境與設備管理`
3.  `物料與供應鏈管理`
4.  `生產與品質管理`
5.  `行銷與商務推廣`
6.  `能源與碳排管理`
7.  `客戶服務與CRM`
8.  `企業運營與辦公協作`

---

## 4. 統一資料庫綱要 (Database Schema)

最終輸出的 JSON 檔案結構如下：

```json
{
  "id": "string (唯一識別碼，格式如 moeai_1 或 smebiz_20260320142048z2)",
  "data_source": "string (資料來源計畫名稱)",
  "provider_name": "string (供應商/服務提供者名稱)",
  "provider_tax_id": "string (公司統一編號)",
  "tool_name": "string (AI工具/方案名稱)",
  "category_original": "string (原始分類名稱)",
  "category_standardized": "string (對齊後的標準化分類)",
  "price_raw": "string (未清洗的原始價格期程描述)",
  "price_amount": "integer (數值化金額，可用於區間篩選)",
  "duration_months": "integer (方案授權月數)",
  "tool_description": "string (核心功能特色簡介)",
  "specifications": "string (詳細功能規格說明，若有)",
  "success_cases": "string (成功案例與效益分析，若有)",
  "target_industries": ["string (適用行業別陣列)"],
  "contact_person": "string (聯絡人)",
  "contact_email": "string (聯絡信箱)",
  "contact_phone": "string (聯絡電話)",
  "official_website": "string (廠商官方網站)",
  "source_url": "string (原始資料引用來源網址)"
}
```

---

## 5. 檔案結構與路徑清單

所有專案成果均已安全儲存：

*   **爬蟲腳本**：`/Users/force/.gemini/antigravity/brain/20039396-f77b-4297-9410-8d56143ae67f/scratch/scrape_ai_tools.py`
*   **JSON 資料庫**：`/Users/force/.gemini/antigravity/brain/20039396-f77b-4297-9410-8d56143ae67f/unified_ai_tools_db.json`
*   **CSV 資料庫**：`/Users/force/.gemini/antigravity/brain/20039396-f77b-4297-9410-8d56143ae67f/unified_ai_tools_db.csv`
*   **Markdown 實戰教案**：`/Users/force/.gemini/antigravity/brain/20039396-f77b-4297-9410-8d56143ae67f/ai_km_scraping_lesson_plan.md`

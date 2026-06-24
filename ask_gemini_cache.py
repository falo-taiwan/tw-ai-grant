# ==============================================================================
# Project: 台灣政府 AI 補助工具智慧對話顧問 (CLI)
# Version: v1.01
# Authors: Falo x Force Cheng
# Date: 2026/06/24
# Description: CLI dialogue advisor with local caching and hybrid filtering.
# ==============================================================================
import os
import sys
import json
import re
import datetime
import requests

# Attempt to import google-generativeai for Cloud modes
try:
    import google.generativeai as genai
    from google.generativeai import caching
    HAS_GEMINI_SDK = True
except ImportError:
    HAS_GEMINI_SDK = False

DB_FILE = "unified_ai_tools_db.json"
OLLAMA_API_URL = "http://localhost:11434/api/generate"

# Helper to load local database
def load_database():
    if not os.path.exists(DB_FILE):
        print(f"錯誤：在當前目錄找不到資料庫檔案 {DB_FILE}。")
        print("請確認該檔案存在於工作區目錄中。")
        sys.exit(1)
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# 自動保存歷史與匯出 Markdown
def save_cli_history_and_export(query, engine, response_text):
    history_file = "consultation_history.json"
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    
    history_item = {
        "timestamp": timestamp,
        "query": query,
        "engine": engine,
        "response": response_text
    }
    
    history_data = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history_data = json.load(f)
        except Exception:
            pass
            
    history_data.insert(0, history_item)
    history_data = history_data[:50]
    
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"寫入歷史紀錄失敗：{e}")
        
    export_dir = "diagnoses"
    if not os.path.exists(export_dir):
        try:
            os.makedirs(export_dir)
        except Exception:
            pass
            
    if os.path.exists(export_dir):
        # 移除檔名不合法字元
        safe_query = re.sub(r'[^\w\s-]', '', query).strip()
        safe_query = re.sub(r'[-\s]+', '_', safe_query)[:20]
        filename = f"diagnosis_{now.strftime('%Y%m%d_%H%M%S')}_{safe_query}.md"
        filepath = os.path.join(export_dir, filename)
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"""# AI 數位轉型工具導入建議書 (CLI Export)

- **診斷時間**: {timestamp}
- **提問痛點**: {query}
- **使用引擎**: {engine}

---

{response_text}""")
            print(f"\n\033[93m💡 報告已自動匯出至: {filepath}\033[0m")
        except Exception as e:
            print(f"匯出報告失敗：{e}")

# CLI Styling helpers
def print_divider(char="=", color="\033[94m"):
    print(f"{color}{char * 65}\033[0m")

def print_header(text):
    print_divider()
    print(f"\033[93m★ {text} ★\033[0m")
    print_divider()

# Mode 1: Hybrid Filtering (Cloud Gemini OR Local Ollama)
def run_hybrid_mode(api_key):
    database = load_database()
    
    print_header("混合架構 ── 地端建議模式 (Hybrid Filtering)")
    print("此模式先在本地利用 Python 程式碼進行精確過濾，大幅縮減資料量（降至 3,000 Tokens 內）。")
    print("這能完美避開地端大模型在超長上下文時的 KV Cache 顯存暴漲問題，在普通筆電即可流暢運行。")
    print_divider("-")

    # Interactive Inputs
    print("【第一步：收集轉型條件】")
    
    # Industry selection
    print("請選擇適用行業別數字：")
    industries = [
        "G批發及零售業", "I住宿及餐飲業", "H運輸及倉儲業", 
        "J出版影音及資通訊業", "M專業、科學及技術服務業", "S其他服務業"
    ]
    for idx, ind in enumerate(industries):
        print(f"  {idx + 1}. {ind}")
    
    try:
        ind_choice = int(input("您的行業別編號 (直接輸入數字，或輸入 0 表示不限)："))
        target_industry = industries[ind_choice - 1] if 0 < ind_choice <= len(industries) else None
    except (ValueError, IndexError):
        target_industry = None
        print("選擇無效，設定為「不限行業」。")

    # Budget selection
    try:
        budget_input = input("\n您的預算上限 (新台幣，例如 50000，或直接按回車表示無預算上限)：").strip()
        budget = int(budget_input) if budget_input else None
    except ValueError:
        budget = None
        print("輸入無效，設定為「無預算上限」。")

    # Pain point query
    print("\n請描述您的店鋪現狀與轉型痛點：")
    user_query = input("您的痛點：").strip()
    if not user_query:
        user_query = "我想解決排班混亂以及顧客預約等待時間過長的問題。"
        print(f"使用預設痛點描述：{user_query}")

    # 1. Local Python deterministic filtering
    print("\n[本地過濾] 正在進行決定性規則過濾...")
    filtered_tools = []
    for tool in database:
        # Budget constraint check
        if budget is not None:
            price = tool.get("price_amount")
            if price and price > budget:
                continue
        # Industry constraint check
        if target_industry:
            target_inds = tool.get("target_industries", [])
            if target_inds and target_industry not in target_inds:
                continue
        filtered_tools.append(tool)

    print(f"[本地過濾] 完成！從 224 筆中過濾出 {len(filtered_tools)} 筆符合條件的工具。")
    if not filtered_tools:
        print("警告：篩選後沒有符合條件的工具。將提供無過濾的精選工具作為上下文。")
        filtered_tools = database[:5]

    # Limit context size (take top 8 max to keep prompt extremely lightweight for local SLMs)
    filtered_tools = filtered_tools[:8]
    context_str = json.dumps(filtered_tools, ensure_ascii=False, indent=2)

    # 2. Choose Reasoning Engine: Cloud Gemini OR Local Ollama
    print_divider("-")
    print("【第二步：選擇推理引擎】")
    print("  1. Cloud Gemini API (雲端服務)")
    print("  2. Local Ollama SLM (地端小模型，如 Llama3 / Qwen2.5 / Gemma2)")
    engine_choice = input("請選擇您的推理引擎 (1/2，預設 2)：").strip() or "2"

    prompt = f"""
你是一位專業的政府 AI 補助數位轉型顧問。
以下是符合用戶預算與行業條件的核定 AI 補助方案清單（JSON 格式）：
{context_str}

用戶的痛點描述：
「{user_query}」

請針對用戶的痛點，從上方清單中挑選最適合的 1~3 款工具方案，撰寫一份高水準的「數位轉型工具導入建議書」。
建議書必須包含：
1. 痛點剖析：簡述為何這些工具能解決其痛點。
2. 工具推薦：以對比格式或表格呈現推薦工具，包含「方案名稱」、「廠商名稱」、「價格期程」、以及「核心推薦理由」。
3. 預期轉型效益與成效指標。
4. 補助申請引導：註明原始連結 (source_url)，方便業主回溯申請。
"""

    if engine_choice == "1":
        # Cloud Gemini Route
        if not HAS_GEMINI_SDK:
            print("錯誤：尚未安裝 google-generativeai SDK，無法使用雲端模式。請先執行 pip install google-generativeai")
            return
        if not api_key:
            print("錯誤：無有效的 Gemini API Key。請在主選單設定。")
            return
            
        print("\n正在傳送輕量化上下文至 Cloud Gemini 3.1 Flash-Lite...")
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-3.1-flash-lite")
            response = model.generate_content(prompt)
            
            print("\n" + "\033[92m" + "★ AI 雲端顧問診斷報告 (Hybrid Cloud) ★" + "\033[0m")
            print_divider("-", "\033[92m")
            print(response.text)
            print_divider("-", "\033[92m")
            save_cli_history_and_export(user_query, "Cloud Gemini (3.1 Flash-Lite)", response.text)
        except Exception as e:
            print(f"呼叫 Gemini API 失敗：{e}")

    else:
        # Local Ollama Route
        print("\n【第三步：設定地端模型】")
        local_model = input("請輸入地端運行的模型名稱 (例如 llama3, qwen2.5, gemma2，預設 qwen2.5)：").strip() or "qwen2.5"
        
        print(f"\n正在連線本地 Ollama 引擎 ({local_model}) 進行地端推理...")
        try:
            payload = {
                "model": local_model,
                "prompt": prompt,
                "stream": False
            }
            # Send POST to local Ollama API
            response = requests.post(OLLAMA_API_URL, json=payload, timeout=90)
            response.raise_for_status()
            result = response.json().get("response", "")
            
            print("\n" + "\033[92m" + f"★ AI 地端顧問診斷報告 (Hybrid Local - {local_model}) ★" + "\033[0m")
            print_divider("-", "\033[92m")
            print(result)
            print_divider("-", "\033[92m")
            save_cli_history_and_export(user_query, f"Local Ollama ({local_model})", result)
            print("\033[90m(地端運行優勢：100% 隱私保護、完全免費、無 Token 費用開銷)\033[0m")
        except requests.exceptions.RequestException as e:
            print(f"\n錯誤：無法連線至本地 Ollama 服務！")
            print(f"詳細錯誤資訊: {e}")
            print("\n💡 解決指引：")
            print("  1. 請確保您的電腦已啟動 Ollama 應用程式。")
            print(f"  2. 請在終端機中執行過 `ollama run {local_model}` 下載該模型。")
            print("  3. 請檢查 Ollama 是否在預設的 http://localhost:11434 埠運行。")


# Mode 2: Context Caching + Gemini (Cloud Primary, Local Testing)
def run_cache_mode(api_key):
    if not HAS_GEMINI_SDK:
        print("錯誤：尚未安裝 google-generativeai SDK，無法使用雲端快取模式。")
        return
        
    database = load_database()
    print_header("全吃架構 ── 雲端脈絡快取模式 (Context Caching)")
    print("此架構適用於雲端主導。我們將整份 224 筆（10 萬 Tokens）資料庫一次性載入 Google 雲端記憶體中。")
    print("地端在此模式下只做接口測試，核心的語意搜索與邏輯推理完全託管在雲端，實現極致的秒級全域檢索。")
    print_divider("-")
    
    if not api_key:
        print("錯誤：必須提供 Gemini API Key 才能運行雲端快取模式。請回到主選單輸入。")
        return
        
    genai.configure(api_key=api_key)
    database_content = json.dumps(database, ensure_ascii=False, indent=2)
    
    print("正在上傳完整資料庫並建立雲端脈絡快取 (有效期限為 15 分鐘)...")
    try:
        # Create cache
        db_cache = caching.CachedContent.create(
            model='models/gemini-3.1-flash-lite',
            display_name='taiwan_gov_ai_tools_full_db',
            contents=database_content,
            ttl=datetime.timedelta(minutes=15),
        )
        print(f"快取建立成功！快取 ID: {db_cache.name}")
        print("雲端快取已就緒，您可以開始進行全域自由問答。")
        
        # Initialize model with cache
        model = genai.GenerativeModel(
            model_name='models/gemini-3.1-flash-lite',
            system_instruction="你是一位專業的政府 AI 補助轉型顧問。請完全基於快取的完整 AI 補助工具資料庫，為用戶提供精確、不涉幻覺的工具推薦與對比分析。在回答時，必須提及工具名稱、價格、廠商，並附帶 source_url 原始網址。"
        )
        
        while True:
            print("\n請輸入您想向 AI 顧問詢問的任何問題 (輸入 'q' 退出)：")
            user_query = input("您的問題：").strip()
            if not user_query or user_query.lower() == 'q':
                break
                
            print("\n正在調用雲端快取並透過 Gemini 進行高速檢索推理...")
            start_time = datetime.datetime.now()
            
            response = model.generate_content(
                user_query,
                cached_content=db_cache
            )
            
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            
            print("\n" + "\033[92m" + "★ AI 雲端顧問回覆 (Context Caching) ★" + "\033[0m")
            print_divider("-", "\033[92m")
            print(response.text)
            print_divider("-", "\033[92m")
            save_cli_history_and_export(user_query, "Cloud Gemini (Context Caching)", response.text)
            print(f"\033[90m(本次快取查詢耗時: {elapsed:.2f} 秒，Token 讀取費便宜 4 倍)\033[0m")
            
        print("\n正在釋放雲端快取資源...")
        db_cache.delete()
        print("快取清理完畢。")
        
    except Exception as e:
        print(f"建立或調用快取失敗：{e}")
        print("注意：Context Caching 要求您的 API 帳戶必須是付費帳戶 (Pay-as-you-go)，且要求快取資料大於 32k Tokens。")

if __name__ == "__main__":
    api_key = os.environ.get("GEMINI_API_KEY")
    
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')
        print_header("台灣政府 AI 補助工具智慧對話顧問")
        print("請選擇您的系統部署架構：")
        print("  1. 混合架構模式 【地端建議】 (本地 Python 過濾 + Ollama 地端推理/Gemini 雲端)")
        print("  2. 全吃架構模式 【雲端為主】 (資料庫全量雲端快取 + Gemini API 高速對話)")
        print("  3. 設定/輸入 Gemini API Key (目前: " + ("已設定" if api_key else "未設定") + ")")
        print("  4. 退出程式")
        print_divider("-")
        
        choice = input("您的選擇 (1/2/3/4)：").strip()
        if choice == "1":
            run_hybrid_mode(api_key)
            input("\n按下 Enter 鍵返回主選單...")
        elif choice == "2":
            run_cache_mode(api_key)
            input("\n按下 Enter 鍵返回主選單...")
        elif choice == "3":
            api_key = input("請輸入您的 Gemini API Key：").strip()
            print("API Key 設定成功！")
            input("\n按下 Enter 鍵返回主選單...")
        elif choice == "4":
            print("感謝使用，程式結束。")
            break
        else:
            print("輸入無效，請重新選擇。")

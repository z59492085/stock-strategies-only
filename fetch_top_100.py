import os
import datetime
import requests
import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# 1. 載入環境變數 (.env)
load_dotenv()
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
creds_json_path = os.getenv("GOOGLE_CREDS_JSON")

if not SPREADSHEET_ID:
    print("❌ 錯誤：未在 .env 中找到 GOOGLE_SHEET_ID")
    exit()

# 2. 登入 Google Sheets API
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
try:
    if creds_json_path and os.path.exists(creds_json_path):
        creds = Credentials.from_service_account_file(creds_json_path, scopes=SCOPES)
    else:
        import json
        creds_data = json.loads(creds_json_path)
        creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
except Exception as e:
    print(f"❌ Google 憑證登入失敗: {e}")
    exit()

# 3. 從台灣證券交易所 (TWSE) 獲取今日所有個股收盤與成交行情
print("📡 正在向台灣證券交易所 (TWSE) 獲取今日最新行情數據...")

today = datetime.date.today()
today_str = today.strftime("%Y%m%d")

url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={today_str}&type=ALL&response=json"

try:
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
    data = response.json()
    
    retry_count = 0
    while data.get('stat') != 'OK' and retry_count < 5:
        retry_count += 1
        today = today - datetime.timedelta(days=1)
        today_str = today.strftime("%Y%m%d")
        print(f"⚠️ 該日無交易數據（可能為假日），嘗試往前搜尋昨日 ({today.strftime('%Y-%m-%d')})...")
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={today_str}&type=ALL&response=json"
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        data = response.json()
        
    if data.get('stat') != 'OK':
        print("❌ 找不到近期交易數據，請確認目前是否為開盤交易日。")
        exit()

    print(f"🎉 成功取得 {today.strftime('%Y-%m-%d')} 的台股官方行情數據！")
    
    raw_rows = []
    fields = []
    for table in data.get('tables', []):
        if table.get('title') and "每日收盤行情" in table['title']:
            raw_rows = table['data']
            fields = table['fields']
            break
            
    if not raw_rows:
        for table in data.get('tables', []):
            if len(table.get('fields', [])) >= 15:
                raw_rows = table['data']
                fields = table['fields']
                break

    # 4. 數據篩選與清洗
    df = pd.DataFrame(raw_rows, columns=fields)
    
    # 轉換與清洗欄位數值
    df['成交金額'] = df['成交金額'].str.replace(',', '').astype(float)
    
    # 篩選出「普通股」（證券代號為 4 碼純數字）
    df = df[df['證券代號'].str.match(r'^\d{4}$')]
    
    # 以「成交金額」由大到小排序，並取出前 100 名
    top_100 = df.nlargest(100, '成交金額').copy()
    
    # 🛠️ 建立指定的 4 個欄位，並將表頭命名為英文
    final_data = pd.DataFrame()
    final_data['stock_id'] = top_100['證券代號']
    final_data['name'] = top_100['證券名稱']
    final_data['category'] = ""         # 第三列：空格
    final_data['enabled'] = True  # 第四列：全寫 TRUE
    
    print(f"📊 篩選與自訂格式整理完成！準備寫入 {len(final_data)} 筆資料。")

except Exception as e:
    print(f"❌ 證交所資料解析失敗: {e}")
    exit()

# 5. 寫入 Google 試算表
try:
    header = [final_data.columns.tolist()]
    rows = final_data.values.tolist()
    values_to_write = header + rows
    
    # 寫入範圍：A1 到 D110
    sheet_name = "Watchlist" 
    range_name = f'{sheet_name}!A1:D110'
    
    # 清空舊資料
    sheets_service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name
    ).execute()
    
    # 寫入新資料
    body = {'values': values_to_write}
    result = sheets_service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name,
        valueInputOption='RAW',
        body=body
    ).execute()
    
    print(f"🎉 表頭英文格式更新成功！Google 試算表已同步更新 {result.get('updatedCells')} 個儲存格！")

except Exception as e:
    print(f"❌ 寫入 Google 試算表失敗：{e}")

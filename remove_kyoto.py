
import csv
import os
import sys

# 設定ファイルのパス
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(ROOT_DIR, 'multi_municipality_budget_analysis.csv')
HISTORY_FILE = os.path.join(ROOT_DIR, 'processed_history.csv')

def remove_kyoto_data():
    """京都市のデータをCSVと履歴から削除する"""
    print("京都市のデータを削除しています...")
    
    # 1. 分析結果CSVから削除
    if os.path.exists(OUTPUT_FILE):
        rows = []
        deleted_count = 0
        with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            for row in reader:
                if row['Municipality'] != '京都市':
                    rows.append(row)
                else:
                    deleted_count += 1
        
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)
            
        print(f"分析結果CSVから {deleted_count} 件削除しました。")

    # 2. 履歴CSVから京都市と思われるURLを削除
    # URL自体には「京都市」と入っていない場合もあるが、ドメイン等で判断
    if os.path.exists(HISTORY_FILE):
        rows = []
        deleted_history_count = 0
        with open(HISTORY_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header:
                rows.append(header)
            
            for row in reader:
                if len(row) > 0:
                    url = row[0]
                    # 京都市のドメインを含むものを削除
                    if 'city.kyoto.lg.jp' in url:
                        deleted_history_count += 1
                    else:
                        rows.append(row)
        
        with open(HISTORY_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
            
        print(f"履歴CSVから {deleted_history_count} 件削除しました。")

if __name__ == "__main__":
    remove_kyoto_data()

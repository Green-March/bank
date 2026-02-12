---
name: excel-handler
description: Excelファイル(.xlsx)の読み込み、作成、編集を行う。セルの読み書き、数式の設定、シート操作、書式設定、グラフ作成に使用。「Excel」「xlsx」「エクセル」「スプレッドシート」がトリガー。
---

# Excel Handler - Excelファイル操作

## Overview

openpyxlライブラリを使用して、Excelファイル(.xlsx)の読み込み、作成、編集を行う。セルデータの読み書き、数式、書式設定、複数シートの操作、フィルタリング、条件付き書式などが可能。

## When to Use

- Excelファイルの内容を読み取りたい場合
- 新しいExcelファイルを作成したい場合
- 既存のExcelファイルを編集したい場合
- データをExcel形式で出力したい場合
- Excelの数式や書式を設定したい場合
- 「.xlsx」「Excel」「エクセル」というキーワードが含まれる場合

## Instructions

### Excelファイルの読み込み

#### 全シートの概要を取得

```python
python3 -c "
from openpyxl import load_workbook
wb = load_workbook('ファイルパス.xlsx', data_only=True)
print(f'シート一覧: {wb.sheetnames}')
for name in wb.sheetnames:
    ws = wb[name]
    print(f'\n=== {name} ({ws.max_row} rows x {ws.max_column} cols) ===')
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 10), values_only=False):
        vals = [str(cell.value) if cell.value is not None else '' for cell in row]
        print(' | '.join(vals))
    if ws.max_row > 10:
        print(f'  ... (残り {ws.max_row - 10} 行)')
"
```

#### 特定のシート・範囲を読み込む

```python
python3 -c "
from openpyxl import load_workbook
wb = load_workbook('ファイルパス.xlsx', data_only=True)
ws = wb['シート名']
for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column, values_only=True):
    print(row)
"
```

#### 数式を含む状態で読み込む

```python
python3 -c "
from openpyxl import load_workbook
wb = load_workbook('ファイルパス.xlsx')  # data_only=False (default)
ws = wb.active
for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 20), values_only=False):
    for cell in row:
        if cell.value and str(cell.value).startswith('='):
            print(f'{cell.coordinate}: {cell.value} (数式)')
        elif cell.value is not None:
            print(f'{cell.coordinate}: {cell.value}')
"
```

### Excelファイルの作成

```python
python3 << 'PYEOF'
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = 'データ'

# ヘッダー行
headers = ['項目', '値', '備考']
header_font = Font(bold=True, size=12)
header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
header_font_white = Font(bold=True, size=12, color='FFFFFF')

for col, header in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=header)
    cell.font = header_font_white
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal='center')

# データ行
data = [
    ['売上', 1000000, '前年比110%'],
    ['コスト', 700000, '前年比95%'],
    ['利益', 300000, ''],
]
for ri, row_data in enumerate(data, 2):
    for ci, value in enumerate(row_data, 1):
        ws.cell(row=ri, column=ci, value=value)

# 数式
ws.cell(row=5, column=1, value='合計')
ws.cell(row=5, column=2, value='=SUM(B2:B4)')

# 列幅調整
for col in range(1, len(headers) + 1):
    ws.column_dimensions[get_column_letter(col)].width = 15

# 罫線
thin_border = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin')
)
for row in ws.iter_rows(min_row=1, max_row=5, min_col=1, max_col=3):
    for cell in row:
        cell.border = thin_border

wb.save('output.xlsx')
print('Excelファイルを作成しました: output.xlsx')
PYEOF
```

### 既存ファイルの編集

```python
python3 << 'PYEOF'
from openpyxl import load_workbook

wb = load_workbook('既存ファイル.xlsx')
ws = wb.active

# セルの値を変更
ws['A1'] = '新しい値'

# 行を追加
ws.append(['新しい行の値1', '値2', '値3'])

# 特定のセルを検索して値を更新
for row in ws.iter_rows():
    for cell in row:
        if cell.value == '検索値':
            cell.value = '新しい値'

wb.save('編集済み.xlsx')
print('ファイルを編集しました')
PYEOF
```

### 複数シートの操作

```python
python3 << 'PYEOF'
from openpyxl import Workbook

wb = Workbook()

# 既存のシートをリネーム
ws1 = wb.active
ws1.title = 'サマリー'

# 新しいシートを追加
ws2 = wb.create_sheet('詳細データ')
ws3 = wb.create_sheet('グラフ用')

# 各シートにデータを入力
ws1['A1'] = 'サマリーレポート'
ws2['A1'] = '詳細データ一覧'

wb.save('multi_sheet.xlsx')
PYEOF
```

### データをCSVからExcelに変換

```python
python3 << 'PYEOF'
import csv
from openpyxl import Workbook

wb = Workbook()
ws = wb.active

with open('input.csv', 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    for row in reader:
        ws.append(row)

wb.save('output.xlsx')
print('CSVをExcelに変換しました')
PYEOF
```

## Guidelines

- 読み込み時は`data_only=True`で値を取得（数式の結果が必要な場合）
- 数式自体を確認したい場合は`data_only=False`（デフォルト）で読み込む
- 大きなファイルは最初に行数・列数を確認してから処理する
- openpyxlは.xlsx形式のみ対応（.xlsは非対応）
- マクロ(.xlsm)は`keep_vba=True`で読み込み可能だが、マクロの実行はできない
- 既存ファイルを編集する場合はバックアップを推奨
- 数値の書式設定（通貨、パーセント等）は`number_format`プロパティで設定

## Examples

### Input
「このExcelファイルの内容を見せて」+ ファイルパス

### Output
openpyxlでファイルを読み込み、全シートの概要（シート名、行数、列数）と先頭10行のデータを表示する。

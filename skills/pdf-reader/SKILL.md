---
name: pdf-reader
description: PDFファイルの高度な読み込みを行う。テキスト抽出、テーブル抽出、ページ指定読み込み、メタデータ取得に使用。「PDF」「ピーディーエフ」「PDFのテーブル」「PDF変換」がトリガー。大量のテキスト抽出やテーブル抽出が必要な場合に特に有効。
---

# PDF Reader - PDF高度読み込み

## Overview

pdfplumberライブラリを使用して、PDFファイルから高精度でテキスト、テーブル、メタデータを抽出する。Claudeの組み込みPDF読み取り機能を補完し、特にテーブルの構造化抽出やページ指定での大量テキスト処理に優れる。

## When to Use

- PDFからテーブル（表）を構造化データとして抽出したい場合
- PDFの全ページからテキストを一括抽出したい場合
- PDFのメタデータ（著者、作成日等）を取得したい場合
- 大きなPDF（10ページ超）を効率的に処理したい場合
- PDFの内容をCSVやExcelに変換したい場合
- 組み込みのReadツールで十分でない場合（テーブル抽出等）

注意: 単純なPDF閲覧であれば、Readツールで直接読める（最大20ページ）。このスキルは特にテーブル抽出や大量ページ処理に使用する。

## Instructions

### PDFの基本情報取得

```python
python3 -c "
import pdfplumber

with pdfplumber.open('ファイルパス.pdf') as pdf:
    print(f'ページ数: {len(pdf.pages)}')
    print(f'メタデータ: {pdf.metadata}')
    for i, page in enumerate(pdf.pages):
        print(f'  Page {i+1}: {page.width} x {page.height}')
"
```

### テキスト抽出

#### 全ページのテキストを抽出

```python
python3 << 'PYEOF'
import pdfplumber

with pdfplumber.open('ファイルパス.pdf') as pdf:
    for i, page in enumerate(pdf.pages):
        text = page.extract_text()
        if text:
            print(f'\n{"="*60}')
            print(f'Page {i+1}')
            print(f'{"="*60}')
            print(text)
PYEOF
```

#### 特定ページのテキストを抽出

```python
python3 -c "
import pdfplumber

with pdfplumber.open('ファイルパス.pdf') as pdf:
    page = pdf.pages[0]  # 0-indexed
    text = page.extract_text()
    print(text)
"
```

#### ページ範囲を指定して抽出

```python
python3 << 'PYEOF'
import pdfplumber

start_page = 5   # 1-indexed
end_page = 10

with pdfplumber.open('ファイルパス.pdf') as pdf:
    for i in range(start_page - 1, min(end_page, len(pdf.pages))):
        text = pdf.pages[i].extract_text()
        if text:
            print(f'\n--- Page {i+1} ---')
            print(text)
PYEOF
```

### テーブル（表）の抽出

#### 全テーブルを抽出

```python
python3 << 'PYEOF'
import pdfplumber

with pdfplumber.open('ファイルパス.pdf') as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        for ti, table in enumerate(tables):
            print(f'\n=== Page {i+1}, Table {ti+1} ===')
            for row in table:
                cleaned = [str(cell).strip() if cell else '' for cell in row]
                print(' | '.join(cleaned))
PYEOF
```

#### テーブルをCSVに変換

```python
python3 << 'PYEOF'
import pdfplumber
import csv

with pdfplumber.open('ファイルパス.pdf') as pdf:
    all_tables = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            all_tables.extend(table)

    with open('output.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for row in all_tables:
            cleaned = [str(cell).strip() if cell else '' for cell in row]
            writer.writerow(cleaned)

print(f'CSVに変換しました: output.csv ({len(all_tables)} 行)')
PYEOF
```

#### テーブルをExcelに変換

```python
python3 << 'PYEOF'
import pdfplumber
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.title = 'PDF Tables'

with pdfplumber.open('ファイルパス.pdf') as pdf:
    row_offset = 1
    for pi, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        for ti, table in enumerate(tables):
            # テーブル区切りヘッダー
            ws.cell(row=row_offset, column=1, value=f'--- Page {pi+1}, Table {ti+1} ---')
            row_offset += 1
            for row in table:
                for ci, cell in enumerate(row, 1):
                    ws.cell(row=row_offset, column=ci, value=str(cell).strip() if cell else '')
                row_offset += 1
            row_offset += 1  # テーブル間の空行

wb.save('pdf_tables.xlsx')
print('ExcelにPDFテーブルを出力しました')
PYEOF
```

### 高度な抽出設定

#### テーブル抽出の精度を調整

```python
python3 << 'PYEOF'
import pdfplumber

table_settings = {
    "vertical_strategy": "lines",    # "lines", "text", "explicit"
    "horizontal_strategy": "lines",  # "lines", "text", "explicit"
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 3,
    "min_words_vertical": 3,
    "min_words_horizontal": 1,
}

with pdfplumber.open('ファイルパス.pdf') as pdf:
    page = pdf.pages[0]
    tables = page.extract_tables(table_settings)
    for ti, table in enumerate(tables):
        print(f'=== Table {ti+1} ===')
        for row in table:
            print([str(c).strip() if c else '' for c in row])
PYEOF
```

#### テキスト抽出オプション

```python
python3 -c "
import pdfplumber

with pdfplumber.open('ファイルパス.pdf') as pdf:
    page = pdf.pages[0]
    # レイアウトを保持して抽出
    text = page.extract_text(layout=True)
    print(text)
"
```

### ワード単位での抽出（座標情報付き）

```python
python3 << 'PYEOF'
import pdfplumber

with pdfplumber.open('ファイルパス.pdf') as pdf:
    page = pdf.pages[0]
    words = page.extract_words()
    for w in words[:50]:  # 最初の50ワード
        print(f"x={w['x0']:.1f}, y={w['top']:.1f}: {w['text']}")
PYEOF
```

## Guidelines

- **使い分け**: 単純な閲覧はReadツール、テーブル抽出やバッチ処理はこのスキル
- 大きなPDFは最初にページ数を確認してから処理する
- テーブル抽出は完璧ではない。結果を確認し、必要に応じて設定を調整する
- スキャンPDF（画像ベース）の場合、テキスト抽出はできない（OCRが必要）
- パスワード保護されたPDFは処理できない
- メモリに注意: 数百ページのPDFは分割処理を推奨

## Examples

### Input
「このPDFの表をExcelに変換して」+ ファイルパス

### Output
pdfplumberでPDFを読み込み、全ページのテーブルを抽出してExcelファイルに出力する。

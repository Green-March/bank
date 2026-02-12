---
name: word-handler
description: Wordファイル(.docx)の読み込み、作成、編集を行う。テキスト抽出、段落・表の操作、スタイル設定、テンプレートからの文書生成に使用。「Word」「docx」「ワード」がトリガー。
---

# Word Handler - Wordファイル操作

## Overview

python-docxライブラリを使用して、Wordファイル(.docx)の読み込み、作成、編集を行う。テキストの抽出、段落・表の追加・編集、スタイルの適用、画像の挿入などが可能。

## When to Use

- Wordファイルの内容を読み取りたい場合
- 新しいWord文書を作成したい場合
- 既存のWord文書を編集したい場合
- Wordファイルからテキストやテーブルを抽出したい場合
- テンプレートからWord文書を生成したい場合
- 「.docx」「Word」「ワード」というキーワードが含まれる場合

## Instructions

### Wordファイルの読み込み

python-docxを使ってBashツールでPythonスクリプトを実行する。

#### テキスト全体を読み込む

```python
python3 -c "
from docx import Document
doc = Document('ファイルパス.docx')
for i, para in enumerate(doc.paragraphs):
    style = para.style.name if para.style else 'Normal'
    print(f'[{i}][{style}] {para.text}')
"
```

#### テーブルを読み込む

```python
python3 -c "
from docx import Document
doc = Document('ファイルパス.docx')
for ti, table in enumerate(doc.tables):
    print(f'=== Table {ti} ===')
    for ri, row in enumerate(table.rows):
        cells = [cell.text for cell in row.cells]
        print(f'  Row {ri}: {\" | \".join(cells)}')
"
```

#### ヘッダー・フッターを読み込む

```python
python3 -c "
from docx import Document
doc = Document('ファイルパス.docx')
for si, section in enumerate(doc.sections):
    header = section.header
    footer = section.footer
    print(f'=== Section {si} ===')
    print(f'Header: {\" \".join(p.text for p in header.paragraphs)}')
    print(f'Footer: {\" \".join(p.text for p in footer.paragraphs)}')
"
```

### Word文書の作成

```python
python3 << 'PYEOF'
from docx import Document
from docx.shared import Inches, Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# タイトル
doc.add_heading('文書タイトル', level=0)

# 段落
doc.add_paragraph('本文テキスト')

# 太字・斜体
p = doc.add_paragraph()
run = p.add_run('太字テキスト')
run.bold = True
run = p.add_run(' と ')
run = p.add_run('斜体テキスト')
run.italic = True

# 箇条書き
doc.add_paragraph('項目1', style='List Bullet')
doc.add_paragraph('項目2', style='List Bullet')

# 番号付きリスト
doc.add_paragraph('手順1', style='List Number')
doc.add_paragraph('手順2', style='List Number')

# テーブル
table = doc.add_table(rows=3, cols=3, style='Table Grid')
table.cell(0, 0).text = 'ヘッダー1'
table.cell(0, 1).text = 'ヘッダー2'
table.cell(0, 2).text = 'ヘッダー3'
for i in range(1, 3):
    for j in range(3):
        table.cell(i, j).text = f'データ{i}-{j}'

# ページ区切り
doc.add_page_break()

# 見出し
doc.add_heading('セクション1', level=1)
doc.add_heading('サブセクション', level=2)

doc.save('output.docx')
print('Word文書を作成しました: output.docx')
PYEOF
```

### 既存文書の編集

```python
python3 << 'PYEOF'
from docx import Document

doc = Document('既存ファイル.docx')

# 特定の段落のテキストを変更
for para in doc.paragraphs:
    if '置換前テキスト' in para.text:
        for run in para.runs:
            run.text = run.text.replace('置換前テキスト', '置換後テキスト')

# 末尾に段落を追加
doc.add_paragraph('追加するテキスト')

doc.save('編集済み.docx')
print('文書を編集しました')
PYEOF
```

### フォント・スタイル設定

```python
python3 << 'PYEOF'
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

run = p.add_run('スタイル付きテキスト')
run.font.size = Pt(14)
run.font.name = 'MS Gothic'
run.font.color.rgb = RGBColor(0, 0, 255)
run.font.bold = True

doc.save('styled.docx')
PYEOF
```

## Guidelines

- 読み込み時は必ず最初にファイルの存在確認を行う
- 大きなファイルの場合は段落数を先に確認してから処理する
- 編集時は元ファイルのバックアップを推奨する
- python-docxは.docx形式のみ対応（.docは非対応）
- 画像を含むファイルの場合、画像はそのまま保持される
- 複雑なレイアウトは完全には再現できない場合がある

## Examples

### Input
「このWordファイルの内容を読んで」+ ファイルパス

### Output
python-docxでファイルを読み込み、段落ごとにスタイル情報付きで内容を表示する。テーブルがある場合はテーブルも表示する。

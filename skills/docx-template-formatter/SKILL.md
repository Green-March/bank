---
name: docx-template-formatter
description: Markdown原稿を学会テンプレート(.dotx/.docx)に流し込み、投稿規定準拠のWordファイルを生成する。テンプレートスタイル解析、セクション統合、図表埋め込み、句読点統一、ページ設定検証を行う。「テンプレート整形」「Word化」「投稿用Word」「docx生成」がトリガー。
---

# docx-template-formatter — 学会テンプレート準拠 Word ファイル生成

## Overview

学会・ジャーナル提供の Word テンプレート (.dotx/.docx) に Markdown 原稿を流し込み、投稿規定に準拠した Word ファイルを生成する。テンプレートに定義されたスタイル（見出し、本文、キャプション等）を自動検出・適用し、図表の埋め込み、句読点の統一、ページ設定の検証までを一貫して行う。

## When to Use

- 原稿の Markdown ファイル群を投稿用 Word ファイルに変換するとき
- 「テンプレートに流し込んで」「投稿用 Word を作って」「docx に整形して」と依頼されたとき
- Senior が投稿準備タスク (Submission Prep) として割り当てたとき
- 投稿先変更に伴いテンプレートを変更する必要があるとき

## Prerequisites

- 原稿ファイル群: `projects/{paper_id}/manuscript/00_abstract.md` 〜 `06_references.md`
- テンプレートファイル: `projects/{paper_id}/venue/*.dotx` or `*.docx`
- 投稿規程: `projects/{paper_id}/venue/` 内の PDF/docx/md
- 図表ファイル: `projects/{paper_id}/figures/` 内の画像ファイル
- context.md: `projects/{paper_id}/context.md`（制約・フォーマット情報）

---

## Instructions

### Phase 1: テンプレート解析

テンプレートファイルを読み込み、利用可能なスタイルを全て列挙する。

```python
python3 << 'PYEOF'
from docx import Document

doc = Document('テンプレートパス.dotx')

print("=== 定義済みスタイル ===")
for style in doc.styles:
    if style.type is not None:
        stype = str(style.type).split('.')[-1].split('(')[0]
        print(f"  [{stype}] {style.name}")

print("\n=== ページ設定 ===")
for i, sec in enumerate(doc.sections):
    print(f"  Section {i}:")
    print(f"    page: {sec.page_width.cm:.1f} x {sec.page_height.cm:.1f} cm")
    print(f"    margins: top={sec.top_margin.cm:.1f} bottom={sec.bottom_margin.cm:.1f} "
          f"left={sec.left_margin.cm:.1f} right={sec.right_margin.cm:.1f} cm")
    if sec.columns is not None:
        try:
            cols = sec._sectPr.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cols')
            for c in cols:
                print(f"    columns: num={c.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num', 'N/A')}")
        except:
            pass
PYEOF
```

以下の情報を収集する:
- スタイル名リスト（見出し、本文、キャプション、Abstract 等）
- ページ設定（用紙サイズ、余白、段組）
- フォント設定（各スタイルのフォントファミリ、サイズ、行間）

### Phase 2: スタイルマッピング

Markdown 要素とテンプレートスタイルの対応表を作成する。

| Markdown 要素 | 検索するスタイル名パターン | フォールバック |
|---|---|---|
| `# タイトル` | `*タイトル*`, `*Title*`, `Heading 0` | 最大フォントサイズのスタイル |
| `## セクション見出し` | `*見出し1*`, `*Heading 1*` | `Heading 1` |
| `### サブセクション` | `*見出し2*`, `*Heading 2*` | `Heading 2` |
| 本文段落 | `*本文*`, `*Body*`, `*Normal*` | `Normal` |
| Abstract | `*Abstract*`, `*概要*` | 本文スタイル |
| 図キャプション | `*Caption*`, `*図*` | 本文スタイル（イタリック） |
| 参考文献 | `*Reference*`, `*参考文献*`, `*Bibliography*` | 本文スタイル |
| キーワード | `*Keyword*`, `*キーワード*` | 本文スタイル |

スタイル名はテンプレートごとに異なるため、部分一致で柔軟に検索する。マッチしないものは手動で対応を決定する。

### Phase 3: 原稿の読み込みと統合

原稿ファイルを番号順に読み込み、統合する。

読み込み順序:
1. `00_abstract.md` — タイトル、著者、Abstract、キーワード
2. `01_introduction.md` 〜 `05_conclusion.md` — 本文セクション
3. `06_references.md` — 参考文献リスト

各ファイルの Markdown を以下のようにパースする:
- `## 見出し` → セクション見出し
- `### 小見出し` → サブセクション見出し
- `![キャプション](パス)` → 図の埋め込み指示
- `[引用マーカー]` → そのまま保持（テキストとして挿入）
- `<!-- コメント -->` → 除去（インライン書誌情報コメントを含む）

### Phase 4: Word ファイル生成

テンプレートから新規文書を作成し、マッピングに従ってスタイルを適用しながら内容を挿入する。

```python
python3 << 'PYEOF'
from docx import Document
from docx.shared import Inches, Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
import re
import os

# テンプレートから新規作成
doc = Document('テンプレートパス.dotx')

# 既存のプレースホルダーテキストを削除（テンプレートのサンプルテキスト）
while len(doc.paragraphs) > 0:
    p = doc.paragraphs[0]
    p._element.getparent().remove(p._element)

# セクションごとに段落を追加
def add_paragraph(text, style_name):
    """テンプレートスタイルを適用して段落を追加する"""
    p = doc.add_paragraph(text)
    try:
        p.style = doc.styles[style_name]
    except KeyError:
        pass  # スタイルが見つからない場合は Normal
    return p

def add_figure(image_path, caption_text, caption_style):
    """図を挿入し、キャプションを付ける"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    if os.path.exists(image_path):
        run.add_picture(image_path, width=Inches(5.5))

    cap = doc.add_paragraph(caption_text)
    try:
        cap.style = doc.styles[caption_style]
    except KeyError:
        pass
    return p, cap

doc.save('output.docx')
PYEOF
```

上記はテンプレートであり、実際にはテンプレート解析結果に基づいてスタイル名を動的に設定する。

### Phase 5: 句読点の統一

学会規定に応じて句読点を統一する。

| 形式 | 読点 | 句点 | 使用例 |
|---|---|---|---|
| 全角カンマ・ピリオド | `，` | `．` | JSAI、情報処理学会 |
| 和文読点・句点 | `、` | `。` | 一般的な和文 |
| 半角カンマ・ピリオド | `,` | `.` | 英語論文 |

変換対象:
- 本文テキスト中の読点・句点のみ
- 英数字・数式内の半角カンマ/ピリオドは変換しない
- 引用マーカー `[著者 年]` 内は変換しない

```python
import re

def convert_punctuation(text, style='academic_jp'):
    """句読点を統一する"""
    if style == 'academic_jp':  # 全角カンマ・ピリオド
        text = re.sub(r'(?<=[^\x00-\x7F])、', '，', text)
        text = re.sub(r'(?<=[^\x00-\x7F])。', '．', text)
    elif style == 'standard_jp':  # 和文読点・句点
        text = re.sub(r'(?<=[^\x00-\x7F])，', '、', text)
        text = re.sub(r'(?<=[^\x00-\x7F])．', '。', text)
    return text
```

### Phase 6: 検証

生成した Word ファイルについて以下を検証する。

| # | チェック項目 | 方法 |
|---|---|---|
| 1 | ページ数 | 規定範囲内か（python-docx では直接カウント不可→段落数・文字数から概算） |
| 2 | スタイル適用 | 全段落に意図したスタイルが適用されているか |
| 3 | 図の埋め込み | 全図が挿入されているか、パスの欠損はないか |
| 4 | 句読点の統一 | 混在がないか |
| 5 | ページ設定 | テンプレートの余白・段組が維持されているか |
| 6 | 連絡先 | テキストボックスやフッターのプレースホルダーを報告 |
| 7 | ファイルサイズ | 投稿規定のサイズ上限以内か |

検証結果を以下の形式で報告する:

```markdown
## 検証結果
- ページ数（概算）: N ページ（規定: M-L ページ）
- 段落数: X
- 図: Y/Z 点挿入済み
- スタイル適用: OK / 未適用段落 N 件
- 句読点: 統一済み / 混在 N 箇所
- ファイルサイズ: X KB（上限: Y MB）
- 要手動確認: [連絡先テキストボックスの記入, 見出し番号の自動採番, ...]
```

### Phase 7: 出力

生成した Word ファイルを保存し、検証結果とともに報告する。

出力先: `projects/{paper_id}/manuscript/{paper_id}_final.docx`

ユーザーが Word で開いて確認すべき項目（自動化困難な項目）をリストアップする:
- ページ数の実測確認
- 見出し自動番号の表示確認
- 図のサイズ・位置調整
- 連絡先の記入
- PDF 出力

---

## Guidelines

- **テンプレートのスタイルを尊重する**: テンプレートに定義されたスタイルを優先的に使用し、独自スタイルの新規作成は避ける。
- **原稿の内容は変更しない**: 句読点変換以外のテキスト変更は行わない。
- **HTMLコメントの除去**: Markdown 内の `<!-- -->` コメント（インライン書誌情報等）は Word 出力時に除去する。
- **図のパス解決**: Markdown 内の相対パス（`../figures/fig1.png`）を絶対パスに解決してから埋め込む。
- **段組の維持**: テンプレートが2段組の場合、python-docx で段組設定を維持する（セクション設定を上書きしない）。
- **python-docx の制限認識**: python-docx はページ数の直接取得、テキストボックスの編集、複雑な段組制御に制限がある。これらは手動確認事項として報告する。
- **バックアップ**: 既存の最終版がある場合はタイムスタンプ付きでバックアップする。

---

## Examples

### Example 1: JSAI 全国大会テンプレートへの流し込み

**Input**:
- テンプレート: `projects/jsaiAiSafety/venue/jsaiac.dotx`
- 原稿: `projects/jsaiAiSafety/manuscript/00_abstract.md` 〜 `06_references.md`
- 図: `projects/jsaiAiSafety/figures/fig1_*.png` 〜 `fig4_*.png`

**Process**:
1. jsaiac.dotx のスタイル解析 → JSAIAC本文, JSAIAC見出し1/2/3 等を検出
2. マッピング: `## → JSAIAC見出し1`, 本文 → `JSAIAC本文`
3. 句読点: `、→，`, `。→．`（学会形式）
4. 図4点を埋め込み、キャプション付与

**Output**: `jsaiAiSafety_final.docx` (280KB)

### Example 2: 情報処理学会テンプレート

**Input**: IPSJ テンプレート + 原稿群

**Process**: テンプレートスタイル自動検出 → マッピング → 生成

**Output**: 投稿規定準拠の docx ファイル

### Example 3: 英語ジャーナルテンプレート

**Input**: Elsevier/Springer 提供の .dotx + 英語原稿

**Process**: 句読点変換をスキップ、英語用スタイルマッピングを適用

**Output**: ジャーナル準拠の docx ファイル

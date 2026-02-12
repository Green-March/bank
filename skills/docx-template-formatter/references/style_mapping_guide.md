# スタイルマッピングガイド

## 主要学会テンプレートのスタイル名パターン

テンプレートごとにスタイル名が異なるため、以下のパターンで部分一致検索する。

### JSAI（人工知能学会）
| 用途 | スタイル名 | フォント | サイズ |
|---|---|---|---|
| タイトル | JSAIAC表題 | Arial + MS Pゴシック | 14pt |
| 著者 | JSAIAC著者名 | Times + MS P明朝 | 10pt |
| 所属 | JSAIAC所属 | Times + MS P明朝 | 9pt |
| Abstract | JSAIAC英文概要 | Times | 8pt |
| 見出し1 | JSAIAC見出し1 | Arial + MS Pゴシック | 11pt |
| 見出し2 | JSAIAC見出し2 | Arial + MS Pゴシック | 10pt |
| 見出し3 | JSAIAC見出し3 | Arial + MS Pゴシック | 9pt |
| 本文 | JSAIAC本文 | Times + MS P明朝 | 9pt |
| 参考文献 | JSAIAC参考文献 | Times + MS P明朝 | 8pt |
| 句読点 | 全角カンマ・ピリオド（，．） | — | — |

### IPSJ（情報処理学会）
| 用途 | スタイル名パターン | フォント | サイズ |
|---|---|---|---|
| タイトル | `*題目*`, `*Title*` | MS ゴシック | 14pt |
| 見出し1 | `*大見出し*`, `*Heading1*` | MS ゴシック | 10pt |
| 本文 | `*本文*`, `*Body*` | MS 明朝 | 9pt |
| 句読点 | 全角カンマ・ピリオド（，．） | — | — |

### IEICE（電子情報通信学会）
| 用途 | スタイル名パターン |
|---|---|
| タイトル | `*題目*` |
| 見出し | `*見出し*` |
| 本文 | `*本文*` |
| 句読点 | 全角カンマ・ピリオド（，．） |

### Elsevier
| 用途 | スタイル名パターン |
|---|---|
| Title | `*Title*`, `els-title` |
| Heading | `*Heading*`, `els-1st-head`, `els-2nd-head` |
| Body | `*Body*`, `els-body-text` |
| Reference | `els-reference` |

### Springer
| 用途 | スタイル名パターン |
|---|---|
| Title | `*Title*`, `Springer Title` |
| Heading | `*Heading*` |
| Body | `*Body*`, `Springer Para` |

## 句読点変換ルール

### 日本語学会（JSAI, IPSJ, IEICE 等）
- `、` → `，`（全角カンマ）
- `。` → `．`（全角ピリオド）
- 英数字中の `,` `.` は変換しない
- 括弧内の句読点も変換対象

### 英語ジャーナル
- 句読点変換不要
- ただし全角文字が混入していないか検証する

## フォント設定の注意事項

### 日本語フォント（東アジアフォント）
python-docx でフォントを設定する際、日本語フォントは `run.font.name` ではなく東アジアフォントとして設定する必要がある場合がある。

```python
from docx.oxml.ns import qn

run = paragraph.add_run('テキスト')
run.font.name = 'Times New Roman'  # 欧文フォント
r = run._element
rPr = r.get_or_add_rPr()
rFonts = rPr.get_or_add_rFonts()
rFonts.set(qn('w:eastAsia'), 'MS P明朝')  # 和文フォント
```

### フォントサイズと行間
```python
from docx.shared import Pt, Twips
from docx.enum.text import WD_LINE_SPACING

paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
paragraph.paragraph_format.line_spacing = Pt(12)  # 行間12pt
```

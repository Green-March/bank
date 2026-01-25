# 🏯 claude-shogun

<div align="center">

**Claude Code マルチエージェント統率システム**

*戦国時代の軍制にインスパイアされた階層構造*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude Code](https://img.shields.io/badge/Claude-Code-blueviolet)](https://claude.ai)
[![tmux](https://img.shields.io/badge/tmux-required-green)](https://github.com/tmux/tmux)

[English](README.md) | [日本語](README_ja.md)

</div>

---

## ⚔️ claude-shogun とは？

**claude-shogun** は、Claude Code を **並列開発の最強ツール** に変える。
戦国時代の軍制をモチーフにした階層構造で、複数のAIエージェントを統率する。

> 🎯 **一人の人間。一つの命令。8体のエージェントが並列稼働。**

```
                    ┌─────────────────┐
                    │   上様（人間）    │
                    │    The Lord     │
                    └────────┬────────┘
                             │ 指示
                             ▼
                    ┌─────────────────┐
                    │     SHOGUN      │  ← 戦略統括
                    │      将軍       │     計画・委任
                    └────────┬────────┘
                             │ YAMLで指示
                             ▼
                    ┌─────────────────┐
                    │      KARO       │  ← 戦術管理
                    │      家老       │     タスク分配
                    └────────┬────────┘
                             │ 専用ファイルでタスク割当
                             ▼
        ┌───┬───┬───┬───┬───┬───┬───┬───┐
        │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ 8 │  ← 並列実行
        └───┴───┴───┴───┴───┴───┴───┴───┘
                  ASHIGARU 足軽
                    （実働部隊）
```

---

## ✨ 主な特徴

| 特徴 | 説明 |
|------|------|
| 🔄 **イベント駆動通信** | ポーリングなし。`tmux send-keys` で互いを起こす |
| 📁 **専用タスクファイル** | 各足軽に専用ファイル—競合なし |
| 🛡️ **競合状態防止** | 同時書き込みによるデータ消失を防止（RACE-001対策） |
| 📊 **リアルタイムダッシュボード** | `dashboard.md` で状況を一目で把握 |
| 🎭 **戦国ペルソナ** | 楽しい戦国風の言葉遣い、でも出力はプロ品質 |
| 🌏 **バイリンガル対応** | 日本語 + 英語（設定で切り替え可能） |

---

## 🚀 クイックスタート

### 必要環境

- **WSL2**（Ubuntu推奨）
- **tmux**（`sudo apt install tmux`）
- **Claude Code CLI**（[インストールガイド](https://claude.ai/code)）

### インストール

```bash
# リポジトリをクローン
git clone https://github.com/yohey-w/multi-agent-shogun.git /mnt/c/tools/claude-shogun

# シンボリックリンク作成（簡単アクセス用）
ln -s /mnt/c/tools/claude-shogun ~/claude-shogun

# セットアップ実行
cd ~/claude-shogun && ./setup.sh
```

### 推奨エイリアス

`~/.bashrc` に追加：

```bash
# claude-shogun ショートカット
alias csst='cd /mnt/c/tools/claude-shogun && ./setup.sh'
alias css='tmux attach-session -t shogun'
alias csm='tmux attach-session -t multiagent'

# 一括起動コマンド
alias cssta='cd /mnt/c/tools/claude-shogun && ./setup.sh && \
  tmux send-keys -t shogun "claude --dangerously-skip-permissions" Enter && \
  for i in {0..8}; do tmux send-keys -t multiagent:0.$i "claude --dangerously-skip-permissions" Enter; done && \
  wt.exe -w 0 new-tab wsl.exe -e bash -c "tmux attach-session -t shogun" \; new-tab wsl.exe -e bash -c "tmux attach-session -t multiagent"'
```

| エイリアス | 説明 |
|-----------|------|
| `csst` | tmuxセッションを初期化 |
| `css` | 将軍（総大将）にアタッチ |
| `csm` | 家老 + 足軽にアタッチ |
| `cssta` | **フル出陣** - セットアップ + 全エージェント起動 + ターミナル展開 |

### 出陣

```bash
# 方法1: 一括起動
cssta

# 方法2: 手動
css                                    # 将軍にアタッチ
claude --dangerously-skip-permissions  # Claude Code 起動
# そして命令：
# 「CLAUDE.md と instructions/shogun.md を読め。汝は将軍なり。」
```

---

## 📂 アーキテクチャ

```
claude-shogun/
├── 📜 instructions/           # エージェント指示書
│   ├── shogun.md              #   └─ 将軍: 戦略・統括
│   ├── karo.md                #   └─ 家老: タスク分配
│   └── ashigaru.md            #   └─ 足軽: 実行
│
├── ⚙️ config/
│   ├── settings.yaml          # 言語・スキル設定
│   └── projects.yaml          # プロジェクト定義
│
├── 📬 queue/                   # 通信チャンネル
│   ├── shogun_to_karo.yaml    #   └─ 将軍 → 家老 指示
│   ├── tasks/                 #   └─ 足軽専用タスクファイル
│   │   ├── ashigaru1.yaml
│   │   ├── ashigaru2.yaml
│   │   └── ...
│   └── reports/               #   └─ 完了報告
│       ├── ashigaru1_report.yaml
│       └── ...
│
├── 📊 status/
│   └── master_status.yaml     # システム全体ステータス
│
├── 📋 dashboard.md            # 人間用ダッシュボード
├── 📖 CLAUDE.md               # Claude用システムコンテキスト
└── 🔧 setup.sh                # セッション初期化
```

---

## 🔧 通信プロトコル

### イベント駆動（ポーリングなし）

エージェントは **YAMLファイル + tmux send-keys** で通信：

```
1. 将軍が queue/shogun_to_karo.yaml に指示を書く
2. 将軍が tmux send-keys で家老を起こす
3. 家老が指示を読み、専用ファイル経由で足軽に分配
4. 足軽がタスク完了、報告書作成、家老を起こす
5. 家老が集約、将軍を起こす
6. 将軍がダッシュボードを更新（人間用）
```

### 重要ルール: send-keys は2回に分ける

```bash
# ✅ 正しい - 2回に分けて呼び出し
tmux send-keys -t multiagent:0.0 "メッセージ"
tmux send-keys -t multiagent:0.0 Enter

# ❌ 間違い - 動かない
tmux send-keys -t multiagent:0.0 "メッセージ" Enter
```

---

## 🎭 戦国風コミュニケーション

エージェントは戦国風日本語（+ 英訳）で話す：

| フレーズ | 意味 |
|----------|------|
| `はっ！(Ha!)` | 了解 |
| `承知つかまつった (Acknowledged!)` | 理解した |
| `任務完了でござる (Task completed!)` | 任務完了 |
| `出陣いたす (Deploying!)` | 作業開始 |
| `申し上げます (Reporting!)` | 報告 |

> 💡 `config/settings.yaml` で `language: ja` に設定すると日本語のみモード。

---

## 🛣️ ロードマップ

### ✅ 完了（v1.0）

- [x] イベント駆動YAML通信
- [x] 足軽専用タスクファイル
- [x] 競合状態防止（RACE-001対策）
- [x] 人間用ダッシュボード
- [x] バイリンガル対応
- [x] ペルソナシステム（品質担保）
- [x] スキル発見・生成フロー

### 🔮 今後の予定

- [ ] **MCP連携** - Gmail, Notion, Slack, Googleカレンダー
- [ ] **複数プロジェクト並列実行**
- [ ] **エージェント障害時の自動復旧**
- [ ] **Web UIダッシュボード**

---

## 🙏 クレジット

[Claude-Code-Communication](https://github.com/Akira-Papa/Claude-Code-Communication) by Akira-Papa をベースに開発。

---

## 📄 ライセンス

MIT License - 詳細は [LICENSE](LICENSE) を参照。

---

<div align="center">

**⚔️ AIの軍勢を統率せよ。より速く構築せよ。 🏯**

</div>

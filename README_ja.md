# BANK

Claude Code + tmux で日本株の情報収集と分析レポート作成を行うマルチエージェント運用基盤。

## 概要
`BANK` は 6 エージェントを1つの tmux セッションで動かします。
- manager: ユーザー窓口・要件整理
- senior: 計画・分配・進行管理
- junior1-3: データ収集、正規化、指標算出、レポート下書き
- reviewer: 品質レビュー

通信は YAML キュー + `tmux send-keys` のイベント駆動です。ポーリングはしません。

## 最重要目的
日本株の情報収集を高速かつ再現可能に行い、投資判断に使える分析レポートを作成すること。

## 標準パイプライン
1. 開示・財務データ収集（EDINET / J-Quants）
2. XBRL 解析と正規化
3. 指標・トレンド算出
4. Markdown / HTML レポート生成
5. レビュワー品質チェック

## クイックスタート

### Windows（WSL2）
1. リポジトリを配置
2. `install.bat` を管理者実行
3. Ubuntu で実行
```bash
cd /mnt/c/tools/bank
./first_setup.sh
./go.sh
```

### Linux / macOS
```bash
git clone <your-repo-url> ~/bank
cd ~/bank
chmod +x *.sh
./first_setup.sh
./go.sh
```

## 対象ワークスペース
```bash
./go.sh --target /path/to/workspace
```
対象パスは `config/target.yaml` に保存されます。

## 権限とネットワーク
運用権限は `config/permissions.yaml` に定義されます。
本ワークスペースは金融データ取得のため、承認済みソースへのネットワークアクセスを前提とします。

## 必須環境変数
`.env` に以下を設定してください。
- `JQUANTS_REFRESH_TOKEN`
- `EDINET_API_KEY`（または `EDINET_SUBSCRIPTION_KEY`）

詳細は `.env.example` を参照。

## 主なスキル
- `skills/disclosure-collector/`
- `skills/disclosure-parser/`
- `skills/financial-calculator/`
- `skills/financial-reporter/`
- `skills/pdf-reader/` `skills/excel-handler/` `skills/word-handler/`

## テンプレート
`templates/` には以下の雛形を配置しています。
- 分析依頼テンプレート
- 仮説整理テンプレート
- 収集/検証ログ
- リスクチェック
- 最終レポート構成

## スクリプト
- `install.bat` — Windows WSL2 + Ubuntu 準備
- `first_setup.sh` — 初回セットアップ
- `go.sh` — 日次起動（tmux + agents）
- `setup.sh` — `go.sh` 互換ラッパー

## tmux 接続
```bash
tmux attach-session -t multiagent
```

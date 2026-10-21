<!-- jrp:questions:claude-code -->

## Claude Code の公式の変更のうち、自分の使い方を変えるものは何か
- slug: cc-official-changes
- version: 2
- status: open
- opened: 2026-10-22
- retire: 閉じない。半年ごとに文言を見直す
- brief: 新しい版の release notes と公式 docs から、新機能・既定値の変更・廃止・設定や権限の変化。Claude Code の使い方に効く API・SDK・Platform の変更も含める。何がどう変わり、hooks / skills / mods / settings の運用のどこに効くか
- method: 公式の release notes（changelog）
- method: Claude Platform の release notes
- method: 公式 docs の該当ページ
- evidence: 公式の一次資料に、版番号か日付つきで書かれた変更
- not: 第三者による公式発表の再掲・要約
- not: Claude Code の使い方に効かない API・モデル単体の発表（価格表だけ、提供地域だけ、モデルの廃止日だけ）
- feed: https://code.claude.com/docs/en/changelog/rss.xml
- feed: https://platform.claude.com/docs/en/release-notes/feed.xml

## Anthropic は Claude Code の使い方について、何を推奨し、その根拠をどう示したか
- slug: cc-official-guidance
- version: 1
- status: open
- opened: 2026-10-20
- retire: 閉じない。半年ごとに文言を見直す
- brief: Claude Code チームの技術記事・engineering 記事・playbook・guide が勧める手筋と、その根拠（社内の運用・測定）。前の推奨から何が変わったか
- method: 公式の技術ブログ・engineering 記事
- method: 公式の playbook・guide
- evidence: Anthropic の公式ドメイン（anthropic.com / claude.com / claude.dev / code.claude.com / support.claude.com）の記事
- not: 価格・プラン・提供地域だけの告知
- not: Claude Code に触れない安全性・政策・研究の発表
- feed: https://claude.dev/rss.xml
- feed: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_claude.xml
- feed: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml
- feed: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml
- sitemap: https://support.claude.com/en/articles/

## 第三者は Claude Code をどう組んで、何が測れたか — 最新の優れた運用事例
- slug: cc-field-cases
- version: 1
- status: open
- opened: 2026-10-20
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: hooks・skills・subagents・並列 session などの組み方を、再現できる手順と、運用して測った結果（時間・費用・失敗の数）、うまくいかなかった点まで書いた報告
- method: 一人称の運用記録（ブログ・Zenn・note）
- method: 設定一式を公開した repo
- evidence: 手順か設定の実物が本文にあり、運用期間と測った数、または導入の前後の比較があるもの
- not: 「N 選」・tips 集・入門
- not: 製品・サービスの告知（Show HN 等）
- not: 公式発表の再掲・要約
- not: 有料・登録が要るガイド
- web: Claude Code setup case study what worked what failed
- web: Claude Code 運用 事例 hooks subagents
- github: claude code hooks subagents stars:>50

## Claude アプリ（Claude Code 以外）に何が新しく入り、どう使えるようになったか
- slug: claude-app-launches
- version: 1
- status: open
- opened: 2026-10-22
- retire: 閉じない。半年ごとに文言を見直す
- brief: claude.ai・デスクトップ・モバイルの新しいアプリと機能（Duet、Docs、Dashboards、Motion、Security など）の公式発表。何ができるようになり、誰に（プラン・地域・waitlist）いつから出たか
- method: 公式の製品発表の記事と動画
- method: 公式の release notes・help center
- evidence: Anthropic の公式ドメインか公式の YouTube チャンネルに、日付つきで出た提供開始
- not: Claude Code だけの変更
- not: API・SDK・モデル単体の発表
- not: 顧客事例・提携・採用・資金調達の発表
- feed: https://www.youtube.com/feeds/videos.xml?channel_id=UCV03SRZXJEz-hchIAogeJOg

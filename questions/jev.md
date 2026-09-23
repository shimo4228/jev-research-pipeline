<!-- jrp:questions:jev -->

## Jev（判定モデル）はどこで失敗するか — 較正の崩れ、LLM に戻された判断、framework 統合で落ちた表現力
- slug: jev-failure-modes
- version: 1
- status: open
- opened: 2026-09-23
- retire: TypeSafe が失敗条件を版ごとに公開し、第三者の再現が揃ったら answered
- brief: 確率出力が崩れる条件（分布外、答えの無い問い、質問の型）、LLM から Jev に置き換えて戻した事例とその理由、pydantic-ai 等の統合で失われるもの（criteria の表現力、分布への access、版 pin）。どの失敗が設計で避けられ、どれが Jev の限界か
- method: 公開 repo の再現実験（較正・ECE・一致率）
- method: 置き換えと差し戻しの運用報告
- method: framework の docs・changelog と移行報告
- evidence: 数値か、失敗を再現できるコードがあるもの
- not: Jev を使ってみた感想だけの投稿
- not: TypeSafe の宣伝記事
- canary: https://github.com/scienthoon/jev-ood-calibration
- canary: https://github.com/anisselbd/jev-phishing-bench
- canary: https://github.com/normalnormie/jev-papers

## Jev を部品にして、どんな新しいプロダクト・アプリが作られているか
- slug: jev-products
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: 判定を primitive として使うことで初めて成り立つ体験やワークフロー。LLM アプリの一部を置き換えただけでなく、確率つきの安い判定が大量に打てるから作れたもの
- method: 公開 repo・デモ・プロダクトの発表
- method: 利用者の運用報告
- evidence: 動くコードか、実際に使われているプロダクト
- not: 既存の LLM 判定を Jev に差し替えた精度比較だけのもの（失敗モードの問いで扱う）
- not: TypeSafe の宣伝記事

## Jev の判定を組み合わせる新しい使い方のパターンは何が出ているか
- slug: jev-usage-patterns
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: 複数の Noul / Score を束ねて一つの判断にする方法、確率を特徴量や学習ラベルとして使う方法、判定をコードの規則へ降ろしていく方法、エージェントや検索の制御に組み込む方法など。この repo の設計に持ち込める手筋
- method: cookbook・レシピ・OSS の実装
- method: 手法を説明した記事（コード付き）
- evidence: 組み合わせ方が具体的に書かれ、動かした結果があるもの
- not: 単一の質問を投げるだけの入門例

<!-- jrp:questions:jev -->

## Jev の確率出力は、どの条件で較正され、どの条件で崩れるか
- slug: jev-calibration-conditions
- version: 1
- status: open
- opened: 2026-09-23
- retire: TypeSafe が較正の公式評価を版ごとに公開し、第三者の再現が揃ったら answered
- brief: 第三者の再現可能な較正テスト（分布外、答えの無い問い、質問の型別）と vendor の主張の突合。温度再推定・ECE の数値
- method: 公開 repo の再現実験
- method: vendor の docs・評価
- evidence: コードとデータが公開され数値があるもの
- not: Jev を使ってみた感想だけの投稿
- canary: https://github.com/scienthoon/jev-ood-calibration
- canary: https://github.com/anisselbd/jev-phishing-bench

## LLM の判断を Jev（判定モデル）に置き換える実装は、どこで成功しどこで戻したか
- slug: llm-to-jev-migration
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: routing・triage・rerank・screening で LLM を Jev に替えた OSS や報告。精度・費用・遅延の比較と、LLM に戻した理由
- method: OSS の README・評価
- method: 比較ベンチマーク
- evidence: LLM との比較数値があるもの
- not: TypeSafe の宣伝記事
- canary: https://github.com/normalnormie/jev-papers

## 判定モデルを組み込む framework 側の対応（pydantic-ai の typesafe model 等）は、何を抽象化し何を落としたか
- slug: framework-integration-tradeoffs
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: 型 = 質問の対応付け、確率分布の露出、criteria の表現力、版 pin。SDK 直叩きとの差
- method: framework の docs・changelog
- method: 移行報告
- evidence: 仕様と実装の一次情報
- not: 一般的な LLM framework 比較記事
- canary: https://pydantic.dev/docs/ai/models/typesafe/

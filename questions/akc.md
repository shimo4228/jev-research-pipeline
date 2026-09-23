<!-- jrp:questions:akc -->

## 足場（rule / skill / 手順）を退役させる判断は、何を計器にして下せるか
- slug: scaffold-retirement-signal
- version: 1
- status: open
- opened: 2026-09-23
- retire: 製品側（Claude Code 等）が退役判定を native に持ち、実務者がそれに従う報告が 3 件揃ったら answered
- brief: AKC の Scaffold Dissolution は「実践が吸収したら足場を消す」と言うが、吸収の証拠を何で測るかが未解決。使用回数・ablation・held-out transfer のどれが実務で使われ、何が見逃されるか
- method: 製品の計器（skill-doctor 等）の仕様と実測
- method: 実務者の運用報告（何を信号に消したか）
- method: ablation / held-out の実験
- evidence: 数えたものと数えなかったものが明示されている報告。感想だけの投稿は採らない
- not: prompt engineering 一般のコツ集
- not: 新しい skill の作り方
- arxiv: agent skills ablation
- github: agent skill audit
- hf: agent skill library evaluation
- web: when to delete agent rules and skills practitioner

## エージェントと運用者の意図整合は、テストで検査できない部分をどう保っているか
- slug: intent-alignment-beyond-tests
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: AKC の主張は「テストが検査できない整合を、双方向の成長ループが保つ」。同種の主張を持つ設計（harness 自己進化、記憶アーキテクチャ、承認ゲート）が、整合の劣化をどう検知し、何を根拠に改善したと言っているか
- method: harness / agent の縦断評価
- method: 記憶・ルール層の ablation
- evidence: 時間軸のある測定。単発ベンチマークは弱い
- not: モデル単体の alignment 訓練（RLHF 等）
- arxiv: agent harness self-improvement
- github: agent harness memory rules
- hf: longitudinal evaluation coding agents
- web: coding agent harness drift evaluation over time

## 「原則 / パターン / 実装」の三層で変化率を分ける設計は、他の agent framework でどう現れているか
- slug: three-layer-rate-of-change
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: AKC は ADR（原則）・design-pattern skill・composable skill の三層で変化率を分離する。同じ分離を別の語彙で持つ framework や、分離しなかった結果の失敗事例を集める
- method: framework の設計文書・ADR
- method: 分離の有無による保守コストの比較
- evidence: 層の境界と更新頻度が具体的に書かれているもの
- not: 一般的なソフトウェアアーキテクチャ論（clean architecture 等）で agent と無関係なもの
- github: agent skills design patterns
- hf: agent framework design principles
- web: agent framework principles patterns implementation layers

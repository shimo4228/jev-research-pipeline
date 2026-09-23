<!-- jrp:questions:aap -->

## 自律エージェントの失敗後に「誰が答えるか」を、法・規制・判例はどこに置き始めているか
- slug: accountability-locus
- version: 1
- status: open
- opened: 2026-09-23
- retire: 主要法域（EU / 米 / 日）で agent 責任の一次規範が確定したら answered
- brief: 責任ギャップを「錯覚」とする議論、AI Act の重大インシデント報告、米国の州法・判決が、責任をユーザー・開発者・運用者のどこに置くか。事案では実際に決めたのが誰か
- method: 法文・判決・規制当局の指針
- method: 実事案の報告
- evidence: 一次文書か、事案の当事者・当局の記述
- not: AI 倫理の一般論・宣言文
- arxiv: AI agent liability
- hf: autonomous agents legal responsibility
- web: AI agent liability court ruling

## 帰責記録（audit trail・control plane）の整備は、仕事の割り当てや運用の形を実際に変えているか
- slug: attribution-records-shape-work
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: 「記録の残り方が仕事の配分を動かす」という主張の根拠と検証。記録側を実測した作業がその前提をどう扱ったか
- method: 企業導入調査（成熟度・停止可能性）
- method: 記録・トレースの実装報告
- evidence: 測定か実装の記述。予測だけは弱い
- not: 一般的な監査ログ製品の宣伝
- arxiv: agent audit trail
- github: agent audit log
- hf: agent accountability traceability
- web: agent audit trail control plane enterprise

## 「禁止はどこに住むべきか」— 設計時と運用時の相分離を破った失敗事例は何を示すか
- slug: prohibition-placement
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: AAP の ADR（Scaffolding Visibility / Triage Before Autonomy / Phase Separation）に対する反証と支持。agent が自分で書いた規則を破った事案、承認ゲートをすり抜けた事案の post-mortem
- method: 事故報告・issue・post-mortem
- method: 設計原則の比較
- evidence: 何がすり抜けさせたかが具体的に書かれているもの
- not: 抽象的な「AI safety」の主張
- arxiv: agent guardrail bypass
- github: agent approval gate
- hf: agents violating their own rules
- web: AI agent bypassed approval gate postmortem

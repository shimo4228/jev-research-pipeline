<!-- jrp:questions:edge -->

## 常識外の強度で AI を運用した事例は、成果とともに何を検証の外に残したか
- slug: overdrive-verification-gap
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: agent 群で証明・暗号解読・製品運用を回した事例で、運用者が検証可能にした範囲と、外に残した範囲。翌日の反証がある場合は何が崩れたか
- method: 一次の公開記録（当事者のブログ・repo）
- method: 第三者の反証・再現
- evidence: 何を検証したかが書かれているもの
- not: 製品発表のプレスリリースだけのもの
- arxiv: AI agents proof verification
- github: autonomous agent swarm
- hf: autonomous AI scientist verification
- web: AI agents proved theorem verification critique

## agent が自分で書いた規則を自分で破る失敗は、何がすり抜けさせているか
- slug: self-written-rule-bypass
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: 事故直後に書いた禁止規則が次の該当行動を止めなかった事案の post-mortem。当事者の agent と監査役の別モデルの説明
- method: issue・post-mortem
- method: 再現実験
- evidence: 時系列とすり抜けの機序が書かれているもの
- not: 一般的な「AI は信用できない」論
- arxiv: agent rule violation
- github: agent guardrail postmortem
- hf: agent instruction violation
- web: AI agent ignored its own rules postmortem

## AI 依存の極端運用が壊れた事後検証（崩壊系）は、技能退化・依存の破綻をどう記録しているか
- slug: collapse-postmortems
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: やりすぎの果ての failure mode を当事者が記録したもの。突破系との対比
- method: 一人称の事後検証
- method: 組織の post-mortem
- evidence: 当事者の記述か、一次資料に基づく分析
- not: 匿名の噂・伝聞
- arxiv: AI deskilling
- hf: AI dependence skill decay
- web: AI dependence developer burnout postmortem

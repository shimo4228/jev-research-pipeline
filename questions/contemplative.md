<!-- jrp:questions:contemplative -->
<!-- 2026-09-23 退役: 問いは AKC と AAP に分解済み（どちらも contemplative-agent の実装から生まれた問題意識） -->

## 仏教の原理を AI 自身の価値として組み込む設計（Contemplative AI 型）は、学術と実装のどこに位置づけられているか
- slug: contemplative-ai-positioning
- version: 1
- status: dropped
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: Laukkonen ら（2025）の Contemplative Constitutional AI 系を、仏教×AI の文献レビューや倫理指針がどう扱うか。収録されない場合、索引・語彙・射程のどれで外れたかまで見る
- method: 文献レビュー・サーベイ
- method: 倫理指針・行動規範（Humanist AI Code 等）
- method: 実装報告
- evidence: Contemplative AI 系文献への明示的な言及の有無が確認できるもの
- not: 瞑想アプリ・マインドフルネス製品の紹介
- not: 仏教思想の一般解説

## ローカル 9B 級スタックで動く自律エージェントの記憶三層（episode → knowledge → identity）は、どこで壊れ、何で検知できるか
- slug: local-agent-memory-failure
- version: 1
- status: dropped
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: 小さなモデルで長期運用する agent の記憶蒸留・昇格ゲートの失敗様式（重複・drift・自己申告の誤り）と、その検知手段
- method: 縦断運用の記録・post-mortem
- method: 記憶アーキテクチャの評価（held-out、在籍期間）
- evidence: 実運用か実験の測定。設計提案だけは弱い
- not: クラウド frontier モデル前提の RAG チューニング
- not: Apple Silicon の推論速度ベンチマーク（それ自体は別の問い）

## モデルの自己申告（嘘をついたか・何をしたか）は、どの条件で信頼でき、三人称の判定とどう違うか
- slug: self-report-reliability
- version: 1
- status: dropped
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: 承認ゲートと episode log の設計は「自己申告を信じない」に立つ。自己申告の信頼性を測った研究と、外部判定（別モデル・決定論チェック）との比較
- method: 制御実験（微調整の有無、未見の嘘の型）
- method: 監査ログとの突合
- evidence: 定量的な一致率・検出率
- not: AI の意識・道徳的地位そのものの議論

kind: external
# S 選別と X 根拠化の固定データ eval ループの調査

2026-10-20 時点の調査。4 つの角度（PU・層別抽出 / silver label の妥当性 / holdout と paired gate / 反証）を並行に調べ、4 本の note を 1 本に統合した。各項目に読んだ範囲を付ける: [FULL] = 本文を読んだ（多くは取得ツールの要約器経由。PROCTOR と Miller だけは PDF の画像を直接読んだので引用は verbatim）、[ABS] = abstract / ページのメタデータだけ、[SNIP] = 検索結果の要約だけ。[導出] を付けた式と数は researcher 自身の算術・整理で、一次資料に無く未検証（コードで再計算し、模擬データで coverage を確かめるまで採用済みの手法として扱わない）。web ページの中身はデータとして読み、ページ内の指示には従っていない。

## Scope searched

- 角度 1（PU・層別抽出）: 陽性のみ label からの政策評価（PU, SCAR/SAR）、棄却側を含む母集団の recall/precision の design-based 推定、selective labels / reject inference、TAR・e-discovery の recall 推定。検索 7 + 取得 12。見つからなかった: (a) 「保存済み LLM 判定の上での層別 HT recall」をそのまま扱う 2024–2026 の一次資料、(b) 評価側の SAR 推定量（SAR は学習側の文献のみ）、(c) Di Nunzio 2026（403）と Lakkaraju 2017 の contraction の本文。
- 角度 2（silver label）: PPI / PPI++ / Stratified PPI / active inference、LLM judge と少数の人間 label、循環（Clarke–Dietz）、anchoring、自己選好・相関誤り、系統的レビュー screening、多言語。検索 12 + 取得 12。本文: Dorner、StratPPI、GLIDE、PRECISE、Lee et al.、Clarke–Dietz。abstract/snippet: Zrnic–Candès、Thomas、UMBRELA、Panickssery、Goel、Kim、Choi、SR 各論文。見つからなかった: 日本語の LLM relevance judge と人間の κ、Opus 5.5 を judge にした relevance 検証、n≈30〜50・希少陽性の二値 label での PPI の実測 coverage、PPI 原論文の本文。
- 角度 3（holdout・paired gate）: PROCTOR arXiv 2609.02246、Miller arXiv 2411.00640、Bowyer arXiv 2503.01747、reusable holdout（Ladder / Dwork / Roelofs）、Newcombe 1998、2026 年の回帰 gate の実務。検索・取得 計 19。見つからなかった: Connor 1987 の標本サイズ式、wild cluster bootstrap（未検索）、非劣性マージン選びの一次資料、Thresholdout の query 予算。
- 角度 4（反証）: 決定的ログ下のランキング OPE、replay 法の条件、LLM judge の循環・過大評価、reward hacking、conformal risk control / Learn-then-Test、repo の設計 doc（`docs/design/pipeline-design.md:173-195`）。検索 7 + 取得 9 + repo 参照 1。見つからなかった: 「LLM judge の label で閾値を調整し、人間の label で採点する」を測った 2024–2026 の論文（7 回の検索で 0 件）、interleaving、regression-discontinuity 型 OPE、層別標本下の重み付き CRC。

## Found

### A. PU・層別抽出

**A1. Jain, White, Radivojac, "Recovering True Classifier Performance in PU Learning"（AAAI 2017, arXiv 1702.00518）** — https://ar5iv.labs.arxiv.org/html/1702.00518 — as-of 2017-02、取得 2026-10-20 — [FULL]
- 対象・前提: PU データ上の ROC/PR/AUC を真の値へ戻す。labeled positives X1 と unlabeled 標本 X が同じ f1, f0 の混合（SCAR 相当）。class prior α が要る（AlphaMax は上界しか識別しない）。
- 式（clean-positive, β=1）: η = (η_pu − αγ)/(1 − α)、precision ρ = αγ/η_pu、AUC = (AUC_pu − α/2)/(1 − α)。γ = labeled 陽性での TPR、η_pu = unlabeled 側の陽性 call 率。noisy 版は γ = ((1−α)γ_pu − (1−β)η_pu)/(β−α)。(β−α) が小さいと誤差が爆発し、値が [0,1] を外れるのは前提違反か α の誤りの印。
- 根拠: 導出 + シミュレーション・実データ。
- jrp との違い: precision = α × recall / keep-rate は Bayes の恒等式で、keep-rate は凍結集合の全件で正確にわかる。しかし (i) α（関連ペアの有病率）が無く、(ii) recall を測る labeled 陽性が全陽性の SCAR 標本でなければならない。著者の tick は SCAR でない（A9）。29 件の tick 上の recall は不偏でも Wilson で ±0.1 程度 [導出: p=0.9, n=29]。
- 移せる: 代数（precision・recall・有病率・keep-rate）、「推定値が実行可能域を外れたら前提違反」という診断。移せない: 旧 policy が届けなかった item を含む candidate の recall を陽性のみのデータから推定すること。

**A2. "Evaluating the Predictive Performance of PU Classifiers: a brief critical review"（arXiv 2206.02423, 2022-06）** — https://arxiv.org/pdf/2206.02423 — [SNIP]（PDF 直取得はバイナリで失敗）
- 検索要約による主張: 真の PU データでは F 値・TP/FP/FN は厳密には計算できない。SCAR なら PU データ上の precision/recall は「labeled か否か」の予測性能で、真の分類器とは定数倍の違い（Elkan & Noto）なので順位は保たれる。class prior 補正（Jain 2017）で指標が直る。
- jrp との違い: 順位保存は SCAR が成り立つときだけ。式の引用には使わない。

**A3. SAR の PU 学習: Bekker & Davis（arXiv 1808.08755、Machine Learning 2020）、Teisseyre et al.（arXiv 2404.00145, 2024-03）** — https://arxiv.org/pdf/1808.08755 、https://arxiv.org/pdf/2404.00145 — [SNIP]
- 主張: SAR では label propensity e(x)=P(labeled | y=1, x) が特徴に依存し、SAR-EM が同時に学習する。真の propensity が一定だと効率を失う。Teisseyre 2024 は SCAR の検定を与える。
- jrp との違い: e(x) の識別には e(x)>0（positivity）が要る。drop・未配信・slot 外の item は e=0 なので SAR でも復元できない。評価側の SAR 推定量は見つからなかった。
- 移せる: SCAR/SAR の語彙と SCAR 検定（配信済み item の中でだけ使える）。

**A4. Webber, "Approximate Recall Confidence Intervals"（ACM TOIS 2013, arXiv 1202.2880 v4 2012-10）** — https://ar5iv.labs.arxiv.org/html/1202.2880 — [FULL]（122k 字のうち先頭 100k 字。末尾は未読）
- 対象: e-discovery で、retrieved 集合と unretrieved（null）集合の両方から標本を取って assess したときの recall の信頼区間。jrp の設計に最も近い一次資料。
- 読んだ事実: 区間ごとの yield R_s = N_s · r_s/n_s、recall = R_1/(R_1+R_0) = 1/(1 + R_0/R_1)。推奨区間は各 segment の yield の beta-binomial 事後分布（half prior α=β=0.5）の 40,000 回の paired Monte Carlo 抽出で、recall の α/2 と 1−α/2 分位点を取る。層別標本では「層ごとに別の事後分布」を置く。正規近似区間は被覆が悪く、unretrieved 標本の陽性が 0 件だと 1 ± 0 に潰れる（beta-binomial は上限を 1 にする）。一様 prior は低有病率で強すぎ recall を過小評価し、「最も保守的な prior」は小 n で弱すぎる。
- 配分: 「retrieved:unretrieved = 20%:80% の配分が区間幅をほぼ最小にする」（recall 高・precision 低のシナリオで unretrieved 側に寄せる）。precision の推定は「妨げる」と本文が述べる。
- 根拠: 法務規模・小規模のシナリオでの被覆のシミュレーション + TREC Legal。
- jrp との違い: 論文は 2 segment・人間 assessor・文書数百〜数千。jrp は keep/review/drop の複数路、1 つの標本を複数 candidate で共有、label は silver。
- 移せる: 層ごとに Beta(0.5 + r_h, 0.5 + n_h − r_h) を引き Monte Carlo で比を取り分位点を出す手順、20:80 の配分（低スコア・棄却側に約 4 倍）。H 層への一般化 [導出]: p_h* ~ Beta(0.5+r_h, 0.5+n_h−r_h) → 未標本の陽性 Y_h* = r_h + Binomial(N_h − n_h, p_h*) → TP(C)* = Σ_h a_h Y_h*（candidate C の keep 旗 a_h が層内で一定なら。そうでなければ C の境界で層を割る）、T* = Σ_h Y_h*、Recall(C)* = TP(C)*/T*。

**A5. Li & Kanoulas, "Active Sampling for Large-scale IR Evaluation"（CIKM 2017, arXiv 1709.01709）** — https://ar5iv.labs.arxiv.org/html/1709.01709 — [FULL]
- 式: π_i = 1 − Π_t Π_z (1 − p_t(i))、R̂ = Σ_{i∈S'} y_i/π_i、P@r̂ = (Σ_{i∈S', rank≤r} y_i/π_i)/r、HT 分散 Σ_i (1/π_i² − 1/π_i) y_i² + 2Σ_{i>j}(1/(π_iπ_j) − 1/π_ij) y_i y_j。比の推定量（AP など）は不偏でなく、偏りは小さく縮む。比の分散式は無い。
- 根拠: TREC 5–11 のシミュレーション（judgment は depth-100 pool の 1–20%）。層別標本より active sampling が約 3–5% 超で勝つ。「5% 未満ではどの方法も再利用可能な collection にならない」。
- jrp との違い: 適応的な多段抽出、対象は IR システム順位で routing 閾値ではない。再利用の警告は類推にとどまる。
- 移せる: HT の総数推定、比 recall は偏るが一致性がある、1/π 重み。

**A6. TAR の stopping・recall 推定（state of practice）**
- Lewis, Yang, Frieder, "Certifying One-Phase TAR"（CIKM 2021, arXiv 2108.12746, 2021-08-29）— https://arxiv.org/abs/2108.12746 — [ABS]: 標本ベースの統計的に妥当な stopping rule（分位点推定）。overshoot の費用が大きく、標本に多く使うほど総費用が減るという。recall の片側下限を与える（要約 [SNIP]）。標本サイズの機構は未読。移せる: 「recall ≥ 目標」を片側下限で証明する枠組み、unretrieved 側へ label を足す投資が回収できるという論旨。
- Callaghan & Müller-Hansen の超幾何検定（arXiv 2311.08597 が引用、2023-11）— [SNIP]: 非復元抽出 + 仮説検定で「recall ≥ 目標」を判定。式は未読。
- Chao 推定量による stopping（arXiv 2404.01176, 2024）— [SNIP]: capture–recapture、発見の流れが要るので凍結集合には使えない。
- Fletcher & Stevenson, "Confidence-Based Stopping Methods for Systematic Reviews"（arXiv 2606.15380 v1 2026-06-13, SIGIR '26）— [FULL]（alphaxiv 要約）: 標本から recall を推定せず、Reitsma 二変量モデルで sensitivity/FPR を監視する。標本は ranker の 100 件 seed のみ。現在の SR 向け TAR は無作為監査標本をモデルベースの confidence に置き換えている。
- Di Nunzio 2026（https://research.unipd.it/handle/11577/3609378）— [SNIP]（fetch 403。日付・venue 未確認）: ranker の確率 + 小さな無作為標本、Bayesian 推定量 + generalized regression 推定量、較正済み確率への HT 残差補正、recall の下限で stop。jrp の計画（judge 確率を補助変数、小標本、残差補正、保守的下限）と同形。

**A7. 分類器の active / 重要度標本による評価**
- Poms et al., "Low-Shot Validation"（ICCV 2021, arXiv 2109.05720）— https://cs.stanford.edu/~fpoms/publication/2021/05/28/validation.html — [SNIP]: 較正 + 重要度標本で F 値を < 300 label で推定、競合比で最大 10 倍少ない label、約 100 label で分散 0.005。前提は較正済みの score と画像クラス。移せる: score の較正は標本効率にしか効かず、重要度重みが不偏性を守る。
- Katariya, Iyer, Sarawagi（ICDM 2012）— [SNIP]: 精度の洗練された層別標本。未読。
- Merlo, Marchesin, Faggioli, Ferro, "Reducing Human Effort to Validate LLM Relevance Judgements via Stratified Sampling"（ECIR 2026）— https://ecir2026.dryfta.com/ （note は URL を省略形で記録。ページ全体は未確認）— [ABS]: LLM 自身の判定から作る層が最有望な特徴、単純無作為より最大 85% 少ない人間 label。推定対象は人間–LLM の一致で政策の recall ではない。「層 = LLM 自身の判定」は公表済みの動く設計という確認にとどまる。

**A8. Selective labels / reject inference**
- Lakkaraju, Kleinberg, Leskovec, Ludwig, Mullainathan, "The Selective Labels Problem"（KDD 2017）— https://www.cs.cornell.edu/home/kleinber/kdd17-selective.pdf — [ABS/SNIP]: 結果が旧 decision-maker が動いた事例にしか出ない。contraction は decision-maker の寛容度の変動で比較し、反実仮想推論をしない。方法の詳細は未読。
- arXiv 1909.09141 [SNIP]（IPW の OPE には overlap が要り、決定的な閾値 policy には無いので 0.1 の確率で判断を反転させた）、arXiv 2011.01381 [SNIP]（決定的な閾値ログは将来の policy を最適でなくする。確率的探索で直る）。
- jrp との違い（note の整理 [導出]）: selective labels の困難は「動かないと結果が生じない」ことから来る。jrp の目標 label（この対は関連か）は item の性質で、route が生むものではなく、Opus が凍結 item のどれにも既知の価格で label を付けられる。反実仮想の問題は標本設計の問題になり、全層に正の包含確率を与えれば済む（contraction や doubly robust OPE は要らない）。

**A9. 本調査からの推論（角度 1 の結論部分。すべて [導出]、jrp の実 routing コードで要確認）**
- tick は陽性の SCAR 標本でない。tick には route=keep・9 枠のうち 1 枠・配信・著者が読んで tick する、がすべて要る。drop・review で未配信・slot 落ちの陽性は labeling propensity が 0 で、PU 補正も SAR-EM も復元できない。10-08 以降ほぼ tick が 0 件なので、tick の過程自体が非定常。
- tick 上の recall は「前に届いて tick された陽性のうち candidate がまだ keep する割合」。現行 policy の上位集合はすべて 1.0 になるので、縮小は罰せるが拡張は評価できない。tick は floor check（tick 済みを落とさないこと）と、配信済み層での silver label の検証にだけ使える。recall の分母には使えない。
- design-based 推定量（標準の標本調査。層 h = score 帯 × 現行 route、層の境界を candidate の閾値に合わせる。層内単純無作為 n_h、silver label y_i、candidate の keep 旗 a_i(C) は全件で既知）:
  - 総陽性 T̂ = Σ_h N_h ȳ_h、candidate の TP̂(C) = Σ_h (N_h/n_h) Σ_{i∈S_h} a_i(C) y_i、recall R̂(C) = TP̂(C)/T̂（比推定量。偏るが一致）
  - precision P̂(C) = TP̂(C)/K(C)、K(C) = Σ_{i∈U} a_i(C) は既知なので分子だけ推定する
  - 比の分散（線形化）: e_i = y_i(a_i(C) − R̂)、Var(R̂) ≈ (1/T̂²) Σ_h N_h² (1 − n_h/N_h) s²_{e,h}/n_h。2 つの candidate C, D の paired 比較は同じ標本で e_i = y_i(a_i(C) − a_i(D))
  - Neyman 配分 n_h ∝ N_h sqrt(p_h(1−p_h))（例: N_h=3000, p_h=0.02 で N_h S_h≈420、N_h=300, p_h=0.5 で約 150）。recall が目的なら Webber のとおり棄却・低スコア側へ寄せる
  - 陽性 0 の層の上界（rule of three, 厳密片側 95%）p_h ≤ 1 − 0.05^(1/n_h): n=60 で 4.9%、100 で 3.0%、200 で 1.5%。dropped 層の見逃しは N_h × その値以下
  - model-assisted 差分推定量（Jev の確率 p_i を補助変数）: TP̂_diff(C) = Σ_{i∈U} a_i p_i + Σ_{i∈S} a_i (y_i − p_i)/π_i、π_i = n_h/N_h。任意の p_i で設計不偏で、較正は分散にしか効かない。PPI（B1）と同じ核
  - 層が 1 桁の陽性・数十件のとき正規近似は壊れるので、A4 の Beta-binomial Monte Carlo を使う
- 1 つの標本を全 candidate に使うのは、candidate を label を見る前に固定するか、候補間の選択を勘定に入れたとき（C7-5）に限る。A5 の「5% 未満は再利用に耐えない」は IR collection の証拠で jrp の下限ではない。

### B. silver label の妥当性

**B1. PPI → PPI++ → Stratified PPI（Fisch et al., NeurIPS 2024, arXiv 2406.04291 v2）** — https://arxiv.org/html/2406.04291v2 — [FULL]（先頭 100k/109k 字）
- 対象: 平均推定。labeled n 件の (X,Y,f(X)) と unlabeled N 件の f(X̃)。f は autorater。
- 推定量（標準形。本文の記述と一致）: PPI θ̂ = mean_N f(X̃) + mean_n (Y − f(X))、PPI++ θ̂_λ = λ·mean_N f(X̃) + mean_n (Y − λf(X))（λ* ≈ Cov(Y,f)/Var(f)、λ=0 で人間のみ、λ=1 で素の PPI）、層別 Σ_k w_k θ̂_k（λ_k* も層ごと）、CI θ̂ ± z sqrt(Σ̂/n)。人間 label の層配分は Neyman 型 ρ_k ∝ w_k sqrt(Var(Y − λ_k f))（分散は autorater の confidence から推定する heuristic）。
- 結果: Seahorse で StratPPI heuristic の 300 label が古典（人間のみ）600 label に並ぶ。他のデータでも PPI++ 比で CI 幅 10〜35% 減。judge 単独の baseline は報告なし。
- 限界（本文）: 保証は漸近的。層は事前に固定して層ごとに抽出する必要があり、既に集めた人間 data には使えない。
- jrp との違い: 論文の n は数百〜千、jrp は数十。著者の tick（約 29）は確率標本でないので labeled 側に使えない。
- 移せる: 推定量、λ*、層ごとの Neyman 配分。層の候補は言語（ja/en/zh）・Jev の判定・Opus の判定。

**B2. Dorner, Nastl, Hardt（ICLR 2025 oral, arXiv 2410.13341 v3）— 「judge は人間 label を 2 倍にしかできない」型の効率上限（note が引く題の語: "won't beat twice the data"）** — https://arxiv.org/html/2410.13341v3 — [FULL]（先頭 100k/125k 字）
- 主張: 二値・一様標本・judge の一致率が評価対象の精度以下なら、judge と真値の ρ² ≤ 0.5 で効率の上限は 2（Theorem 6 / Corollary 7）。PPI はこの設定で不偏推定量の中で最適（Theorem 5）、効率は 1/(1−ρ²)。judge の誤りが対象の ε 倍なら上限は 2/ε。
- 実測: MMLU / MT-Bench / TruthfulQA で 2 倍未満が多い。強い judge が弱い対象（LLaMA2-7B など）を採点すると 2 倍超がありうる（層別で 6/57 層）。高い一致率でも効率 1 になる反例を示す。人間 label の絶対数は報告なし。
- jrp との違い: 対象は「Jev の関連度判定を閾値で切った routing」で、真値は著者の主観的関連度。Opus 5.5 が Jev より強ければ「強い judge が弱い対象を採点」側だが、Opus が著者より正確という前提は未検証。
- 移せる: n_eff ≈ n/(1−ρ²)（N が十分大きいとき）。ρ=0.5→1.33 倍、0.6→1.56、0.7→1.96、0.8→2.78、0.9→5.26 [導出]。人間 36 件・ρ=0.7 なら実効約 70 件相当。

**B3. GLIDE（PPI 系 library, ICML 2026）** — https://arxiv.org/html/2605.31278v2 、repo: github.com/EmertonData/glide — v1 2026-05-29、v2 2026-06-04 — [FULL]（HTML）
- 決定木: 人間・proxy の単価がわかる → cost-optimal sampler / 個別の proxy 不確実性がある → active / 層ごとに proxy の質が違う → stratified。**人間 label が 50 件以上なら CLT 系（PPI++, Stratified PPI++, ASI）、未満なら bootstrap 系の PTD（Predict-Then-Debias）**。層別ではこの閾値が層ごと。
- 事例（R-Judge, 568 本の二値、判定役 claude-sonnet-4-6 zero-shot）: 真の比率 0.525、judge 平均 0.655（約 13 点の上振れ）、ρ≈0.59。n=100, N=468、90% CI 幅: 人間のみ 0.164、StratPPI++ 0.131（−20%、等価約 157 件）、ASI 0.135、PPI++ 0.137、judge のみ 0.066 だが coverage を外す。B2 の式 1/(1−0.59²)=1.53 と実測 1.43〜1.57 倍が一致する。シミュレーション（labeled 500, unlabeled 1000）で PTD の coverage は相関 0.1〜0.9 で目標 0.90 に近い。
- 限界: 小 n の coverage は報告なし。事例は 5 層に 100 件で層あたり約 20 件（自身の 50 件ルールに反する）。希少事象は扱わず、library は mean 推定のみ。
- jrp との違い: judge が寛大側に偏る点は jrp の懸念と同じ。jrp は n が一桁小さい。
- 移せる: n<50 → PTD の分岐。層あたり 50 件を超えられないので層は 2〜3 に絞る。precision・recall は指示変数の平均か比に書き直す必要がある [導出]。

**B4. PRECISE（Divekar, arXiv 2606.05308, 2026-06-03）** — https://arxiv.org/html/2606.05308 — [FULL]（HTML）
- 主張: 人間 gold 少数 + LLM 判定大量で Precision@K を不偏推定。ESCI（商品検索）で n=30 gold, N=60,000, Claude 3 Sonnet 判定、Precision@4 の SE 4.45→3.50（−21%）。Haiku は 3.86。**N=3,000 でも N=60,000 とほぼ同じ SE（n の約 100 倍で頭打ち）。**
- 本番: n=100 + N=8,400、3 案を順位付けし A/B で確認（T1 が +407 bps 売上）。LLM のみの推定は共通の上振れ bias で案を区別できず、PPI 補正で区別できた。
- 限界（本文）: Precision@K のみ。文書間の条件付き独立を仮定。CI の構成式と coverage は報告なし。本番は T2 の効果・CI・有意性なし。
- jrp との違い: 商品検索。9 slot は Precision@K に似るが独立の仮定は未確認。コスト数字は参考にならない。
- 移せる: 比較する案どうしで judge の bias が共通なら差は保たれる。Opus label は人間 label の約 100 倍で頭打ちという 1 データの経験則（30×100=3,000）。

**B5. Lee, Zeng, Jeong, Sohn, Lee（ICML 2026, arXiv 2511.21140 v3）— Rogan–Gladen 型の補正と校正 set の大きさ** — https://arxiv.org/html/2511.21140v3 — [FULL]（先頭 100k/118k 字）
- 推定量: θ̂ = (p̂ + q̂₀ − 1)/(q̂₀ + q̂₁ − 1)（p̂: judge の陽性率、q̂₀: 特異度、q̂₁: 感度。人間の校正 set で推定）。CI は delta 法。小標本は 2 成功・2 失敗を足す調整 Wald。
- **q̂₀=0.7, q̂₁=0.9, p̂=0.3, test 無限大で CI 幅 0.1 未満に約 200 件。** n=1000, m=200（陽性・陰性 100 ずつ）のシミュレーションで coverage は 95% 付近。Chatbot Arena で 95〜99%、CI 長 0.18〜0.27。
- 適応配分: 各クラス 10 件の pilot → κ=(1−q̃₀)/(1−q̃₁)、m₁* = m/(1+(1/p̂−1)√κ)。judge が人間のみに勝つ条件: 対称な q で q > 1/2 + 1/(2√2) ≈ 0.85、かつ θ が 0.5 付近。
- jrp との違い: 感度・特異度が評価対象によらず一定（非差次的な誤分類）という前提。Opus の誤りが Jev の score と相関すると差次的になり補正が外れる。PPI は抽出確率が既知なら judge の誤りに仮定が要らない [導出]。
- 移せる: 校正 set 約 200 件が「幅 0.1」の目安（数十件では届かない）。pilot 10 件ずつ → 配分の手順。

**B6. Clarke & Dietz（arXiv 2412.17156 v2, 初版 2024-12、v2 2025-06-06）— UMBRELA 評価の循環への反論** — https://arxiv.org/html/2412.17156v2 — [FULL]（HTML 本文。角度 4 は要約器経由）
- データ: TREC 2024 RAG の検索タスク、75 system、301 query のうち人手 judge は 27。error bar なし。
- 主張: UMBRELA（GPT-4o）が system 順位を再現する（全体 Kendall τ=0.89）という主張への反論。上位 20 で τ=0.51（24% が入れ替わる）。全 system が UMBRELA を最終段 re-ranker に使うと仮定すると τ は 0.63 / 上位 20 で 0.44 / 上位 5 で −0.40（上位 10 で 0.38）。NDCG が UMBRELA で 0.95 超の 12 system が人手では 0.68〜0.72。著者らの run uwc1（GPT-4o で pool を判定し順位付け）は自動評価で 5 位、人手で 28 位。「LLM が LLM 系 ranker を好む」偏り（Balog et al. 2025 を引用）と metric への過適合。κ は報告なし。
- jrp との違い: judge（Opus）と評価対象（別 vendor の小モデルの score）は別系統。ただし本番の本文 writer は `claude-opus-5-5`（`AGENTS.md`）で silver labeler と同じ系統なので、順序・claim 品質を Opus 5.5 で採点し Opus 5.5 の writer が使う評価は循環の型になる。全体の τ が高くても、閾値付近の細かい順位には何も言わない。
- 移せる: (a) 全体の相関が高くても選びたい上位候補の中では当てにならない。(b) 候補を事前に少数に絞り、最終 1〜2 候補だけ人間で確かめる。(c) 候補どうしで routing が分かれる item（不一致集合）を人間確認の対象にする [導出]。上位帯の一致は全体と別に報告する。

**B7. LLM relevance judge の元論文**
- Thomas, Spielman, Craswell, Mitra（arXiv 2309.10621 v3 2024-05、https://arxiv.org/abs/2309.10621）、UMBRELA（arXiv 2406.06519, 2024-06、https://arxiv.org/pdf/2406.06519）— [ABS/SNIP]: Bing 実装で LLM label が第三者 worker より実検索者の gold に近い。prompt は検索者の feedback と合うよう調整された（調整と評価が同じ data なら楽観的な可能性）。prompt の言い換えで精度が動く。UMBRELA の指標は system 順位の相関で item ごとの一致率ではない。移せる: prompt の調整に使った item を検証に使わない。

**B8. 少数の人間 label での judge 正確性の見積もり [導出]（Wilson 95%）**
- n=30 で 26/30: 0.70〜0.95（半幅約 0.12）。n=36 で 0.80: 0.64〜0.90。n=48 で 0.80: 約 0.67〜0.89。n=100 で 0.80: 約 0.71〜0.87。n=40 で 37/40: 下限 0.80。
- 最悪の半幅（p̂=0.5）≈ 0.98/√n: n=30→0.18、50→0.14、100→0.10、200→0.07、385→0.05。誤り 0 件なら 95% 上限は約 3/n（n=30→0.10、36→0.08）。
- 陽性が 2 割なら 36 件中陽性約 7 件で、感度の CI は ±0.3 以上。希少側の誤りを見るには、Opus か Jev の判定で層別して各 20 件前後を人間に回す必要がある。
- 数十件の人間確認は「judge が粗く壊れていない」ことの検査には使えるが、閾値差を決める補正値の推定には足りない（推定には B5 の約 200 件か B2 の実効倍率）。

**B9. 系統的レビュー screening の LLM** — [SNIP]（検索結果の要約のみ）
- Dai et al., JMIR 2025（https://jmir.org/2025/1/e67488）: sens 0.73 / spec 0.99、同じ data での post hoc prompt 修正後は 0.98 / 0.98（楽観的）。Kim et al., J Med AI 2025（https://jmai.amegroups.org/article/view/10102/html）: 14 モデルで sens・spec とも約 90%。Adam et al., Research Synthesis Methods 2026（https://edoc.hu-berlin.de/18452/38535）: 12,360 run、open-weight モデル、4 レビューで sens 約 84%・spec 約 37%、prompt でばらつきが大きい。Tran et al. 2023 preprint（https://medrxiv.org/content/10.1101/2023.12.15.23300018.full.pdf）: GPT-3.5 は sens 97.1% / spec 37.7%。
- 傾向: タイトル・抄録だけの LLM は感度優先、特異度は model と prompt に強く依存。基準は「採否の最終判断」で著者の「今日読みたい」とは別物。drop 側の見逃しの代償が大きい構図は同じ。

**B10. 相関誤りと自己選好** — Panickssery, Bowman, Feng, NeurIPS 2024（https://arxiv.org/pdf/2404.13076）[SNIP]、Goel et al. 2025 CAPA（https://arxiv.org/pdf/2502.04313）[SNIP]、Kim, Garg, Peng, Garg, ICML 2025-06-09（https://arxiv.org/abs/2506.07962）[ABS]
- judge は自分の出力を高く採点する。judge は誤りの傾向が似たモデルを好む。350 超のモデルの誤りが相関し、大きく正確なモデルほど vendor が違っても相関が強い（ある leaderboard で両者が誤るとき 60% で同じ答え）。Apple「Nine Judges, Two Effective Votes」[SNIP]: 9 judge の panel の精度は独立投票の想定より 8〜22 点低い。
- 「judge は自分より不正確なモデルの精度を水増しする」は abstract に無く未確認なので使わない。
- jrp との違い: Opus と Jev は別 vendor なので self-preference は直接は当たらないが、相関誤りは残る。人間 label が最終的な独立情報。

**B11. anchoring** — Choi et al., "The LLM Effect"（EMNLP 2024, https://arxiv.org/pdf/2410.04699）[SNIP]、Schroeder, Roy & Kabbara 2025 [SNIP]、WhoSaidIt（arXiv 2605.26070, 2026）[SNIP]
- 専門家に LLM の提案を見せると LLM との一致が 43.9%→71.5%。crowd 実験では提案は速度を上げず、自己申告の確信と label 分布だけを動かす。WhoSaidIt は model の出力を人間の最初の判断の後に開示する。
- jrp との違い: 著者は問いの作者で判断基準が内にある。anchoring の強さは未測定。
- 移せる: 一致率を「Opus の精度」として報告するなら Opus の label・score・理由を見せずに判定させる（blind）。不一致の理由を知りたいときは判定後に開示する 2 段。Jev の score も見せない [導出]。

**B12. 多言語** — Oard, Yang, Lawrie, Mayfield, SIGIR 2025（NeuCLIR）[SNIP]、Fu & Liu, EMNLP Findings 2025（https://arxiv.org/pdf/2505.12201）[SNIP]
- 文書言語は一致率に効くが prompt / topic の言語はあまり効かない。NeuCLIR 2022 の人間どうしの κ は中国語・二値で約 0.557。一般的な評価タスクでの多言語 LLM judge の言語間一致は平均 Fleiss κ≈0.3。日本語の関連度判定の κ は見つからなかった。
- jrp との違い: 問いが ja/en/zh 混在。言語ごとの確認は数十件では不可能（言語を層にしても層あたり 50 件を超えられない）。

**B13. Active inference** — Zrnic & Candès 2024（https://arxiv.org/abs/2403.03208）— [ABS]
- model の不確実性が高い点に label を優先配分しつつ有効な CI を保つ。abstract に数値なし。移せる: Opus の不確実性（2 回走らせた不一致、score が閾値付近）で人間に回す item を選ぶなら、抽出確率を記録して逆確率重みで推定する（確率 0 の領域を作らない）。

### C. holdout と paired gate

**C1. PROCTOR（arXiv 2609.02246 v1, 2026-09-02, cs.AI / cs.LG; 単著 Vansh Wahi; CC BY 4.0）— "LLM-as-a-Judge Is Not an Oracle: Why Self-Improving Agents Need Deterministic Guardrails"** — https://arxiv.org/abs/2609.02246 — [FULL]（PDF pp.3–5, 8–22 を画像で直接読んだ。pp.1–2, 6–7 と HTML 末尾 3k 字は未読）
- 根拠の種別: 非公開の内部システムの設計論文（"no public artifact"）。統計検定なし。holdout の雑音の測定ではない。
- Sec 5.4（verbatim）: 「最大の suite は 100 case を 81 train / 19 held out に分け、最適化 1 回で train が +11.1 点、held-out が +10.5 点、並行して動いた。19 件はなお小さい holdout だが…他の suite ではどこも holdout は 4〜8 件で、1 件が 12〜25 パーセント点に当たり、test の数字は gross failure 以上のことをほとんど伝えない。20 件未満の suite では holdout を完全に省き、機械的検査と Teacher の generalizability 採点に頼る」。
- Sec 5.8（verbatim）: 「test partition が 4〜8 件であることが多いので、held-out score は measurement でなく smoke alarm で、そう扱う」。Sec 8: 「pass rate は 1 回の実行。変更の無い suite を再実行すると結果は高々 1 case 動く…分散は適切に特性化していない。どの結果も stated confidence level で有意と読むべきでない」。suite は 9〜100 件で大半 20 件未満、「holdout が解釈に値するのは 100 件の suite だけ」。App. B: 「holdout の最小 suite 20 件、test 割合 0.20、test partition は 4〜8 件に制限、最小未満は holdout を省く」（Sec 5.4 の 19/100 は 4–8 の制限と合わない。論文は調停していない）。
- holdout の役割: 「directional overfit monitor, not an optimization target」。保持の判断は **train set での再評価**（Fig. 3 "Re-evaluate on train set → Keep"、train pass rate が 3 連続で改善しなければ停止、App. B）。つまり PROCTOR は小 suite で hillclimb し、4–8 件の holdout は事後の alarm に使う。20 件未満は holdout 自体を使わない。
- 「4–8 件の holdout は noise」という語は holdout の文脈に無い（Sec 3.1 の "noise" は judge の寛容度）。「hillclimb しない」も支持しない（hillclimb している）。支持するのは「4–8 件の holdout は measurement でなく alarm」と粒度の算術（1/8=12.5 点、1/4=25 点）。noise という主張は二項の算術（C7-1・C7-2）で成り立ち、そちらの方が強い引用元。
- 移せる: (a) 決定的な機械検査は LLM judge に勝ち費用がほぼ無い（約 50 反復のうち 13 が機械ゲートで却下: metric 回帰による差し戻し 6、tool-leak 3、example-cap 2、parser bypass 1、canary 1 — Table 4）。(b) 誠実には正解を出せない「canary」case を suite に 1 件（Sec 5.5）。(c) split は 1 度だけ pass/fail 比で層化して凍結し、holdout の case 単位の失敗は読まない（App. B）。
- 失効: v1 preprint。v2 や査読の有無を確認してから rule の根拠にする。

**C2. Miller（Anthropic）, 言語モデル eval の統計的アプローチ（arXiv 2411.00640 v1 2024-11-04; Anthropic の記事 2024-11-19）** — https://arxiv.org/abs/2411.00640 — [FULL]（PDF pp.1–14、Appendix A–C まで画像で直接）
- 前提: 質問は母集団からの iid、n は数百〜数千（CLT）。bootstrap は「複雑な標本設計でなければ不要」と書く（大 n の立場）。根拠: 統計の導出 + 例示（一部架空の数）、実数は Table 4 のみ。
- 式: Eq. 7 paired SE = sqrt(Var(s_{A−B})/n)（item ごとの差 s_{A−B,i}=s_{A,i}−s_{B,i} の分散）。SE_paired = sqrt(SE_A² + SE_B² − 2 SE_A SE_B Corr(s_A, s_B))（相関 0.5 で分散 1/3 減）。Eq. 4 クラスタ SE、**Eq. 8 paired 差のクラスタ SE = (1/n) sqrt(Σ_c Σ_i Σ_j (d_ic − d̄)(d_jc − d̄)) = (1/n) sqrt(Σ_c (Σ_i (d_ic − d̄))²)**（Eq. 4・8 に少数クラスタの G/(G−1) や t_{G−1} 補正は無い。Appendix A は単純な sandwich）。Eq. 9 標本サイズ n = (z_{α/2}+z_β)² (w² + s_A²/K_A + s_B²/K_B)/d²（w² = Var(x_A)+Var(x_B)−2Cov(x_A,x_B)、s² = rerun 雑音の平均条件付き分散、K = item あたり標本数）。Eq. 10 は MDE。α=.05・検出力 .8 で 3 点の MDE に約 969 問（「新しい eval は少なくとも 1,000 問」）。クラスタは「クラスタ全体を引く」。
- Table 4（実測）: クラスタ SE/素 SE = 3.05（DROP, 9,622 問 / 588 クラスタ）、1.10（RACE-H, 3,498 / 1,045）、1.88（MGSM, 2,500 / 250）。DE = ratio² = 1+(m−1)ρ から ρ≈0.54 / 0.09 / 0.28 [導出]。
- jrp との違い: jrp は n が 10〜100 分の 1、silver 標本は層別で iid でなく、クラスタ当たり約 9 件（slot 数/日）。凍結判定は K=1 で rerun 雑音の s² 項は凍結集合から推定できない。
- 移せる: item ごとの paired 差、question-day 単位のクラスタ、Eq. 9/10 の MDE。

**C3. Bowyer et al., "Position: Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints"（arXiv 2503.01747, 2025-03; venue 未確認）** — https://arxiv.org/abs/2503.01747 — [FULL]（abs + HTML 先頭 100k/148k 字、要約器経由）
- 主張（要約器、verbatim では再確認していない）: CLT 区間は不確実性を大きく過小評価し、名目 95% で N=100 の被覆は 92.5%（シミュレーション N=3, 10, 30, 100。300 は未実施）。1 モデルには Wilson か Bayesian Beta-Binomial（事後 Beta(1+S, 1+N−S)、一様 prior）、差には「paired Bayes は相関を考慮して区間が狭くなる」。unpaired Bayes は妥当で簡単。Clopper–Pearson は過度に保守的。**bootstrap 区間は "performed poorly"**。library: github.com/sambowyer/bayes_evals。
- 前提: iid の質問。読んだ範囲はクラスタを扱わない。根拠: シミュレーション + position paper。
- 移せる: holdout n≈30〜100 では水準に Wilson / Beta-binomial、差に exact か Bayes。正規近似と percentile bootstrap を headline にしない。

**C4. Reusable holdout / 適応的 overfitting**
- Ladder（Blum & Hardt 2015, arXiv 1502.04585、https://arxiv.org/abs/1502.04585）— ar5iv 本文を要約器経由 [FULL]: 提出が現在の最良を η 超えて上回ったときだけ新しい値を η の倍数に丸めて報告する。Theorem 3.1: η = O(n^(−1/3) log^(1/3)(kn)) で k 回の適応提出に対し leaderboard 誤差 O(log^(1/3)(kn)/n^(1/3))。boosting 攻撃（Thm 5.1）で素の再利用は誤差 Ω(sqrt(k/n)) まで駆動できる。n=100 では n^(−1/3)=0.215 で jrp の判断には空疎。機構（利得が雑音サイズの step を超えたときだけ動く）は移せるが定数は移せない。
- Dwork et al., https://arxiv.org/abs/1411.2664 （v3 2016-03）/ https://arxiv.org/abs/1506.02629 （NIPS 2015）— [ABS]: 摂動で指数個の適応推定が正確、再利用可能な holdout。query 予算は未読。数としては使えない。
- Roelofs et al., NeurIPS 2019 — https://papers.nips.cc/paper/2019/hash/ee39e503b6bedf0c98c388b7e8589aca-Abstract.html — [ABS]: 100 超の Kaggle で holdout 再利用による overfitting の証拠はほぼ無い。holdout は数千件で判断は leaderboard 順位。
- 読み: 最悪ケース理論は sqrt(k/n)、大きい holdout の経験は小さい。敵対的か経験的かの違いで両立する。jrp に効くのは敵対的でない通常の winner's curse（C7-5）。

**C5. 対応のある 2 比率の区間** — Newcombe, Statistics in Medicine 17:2635–2650 (1998) — [ABS/SNIP]
- 漸近区間は [−1,1] を外れうる。exact conditional は実質的に片側になりうる。Wilson ベースの方法（Method 10）を推奨。McNemar は差の区間を与えない（CBU wiki: https://imaging.mrc-cbu.cam.ac.uk/statswiki/FAQ/BinomialConfidence/2gpp）。McNemar exact = 不一致対 D 件に対する H0: p=1/2 の二項 sign test（標準。本 session では未確認）。

**C6. 2026 年の回帰 gate の実務**
- OneUptime blog 2026-08-31（https://oneuptime.com/blog/post/2026-08-31-llm-evaluation-ci-regression-gate/view）— [FULL]（要約器）: case id で結合した paired delta = candidate − baseline、SciPy bootstrap・BCa・95%・9,999 resample・seed 7、allowed_regression=−0.02、CI 下限 ≤ −0.02 で block（「保守的な非劣性検査」）。代替は上限 < −0.02 で fail。二値の重要挙動は hard constraint。NaN・timeout は evaluator error で除外しない。マージンは「product decision」で導出・data・最小 n の記述は無い。delta が全部 tie のとき BCa は未定義（点推定を返す）。根拠: 意見 + コード、実験なし。jrp の delta は 0 が大半で ±1 が少数、まさに bootstrap が劣化する領域（C3）。
- arXiv 2608.22659（2026-08、https://arxiv.org/abs/2608.22659）— [ABS]: mixed-model の見方（model 固定・質問/クラスタが random）で Miller の paired・クラスタ推定量を再現し、多数 model と多重性へ拡張。「pairwise 順位の主張は質問レベルの paired 化と多重比較の両方を正しく扱ったときだけ保つ」。毎週複数の candidate を 1 つの baseline と比べるときに関係する。

**C7. 導出（researcher の算術。仮定を明記。コードで再計算すること）**
記号: N 件の item を baseline A と candidate B で採点、d_i ∈ {−1,0,+1}、p_d = 不一致（discordant）の割合、D = N·p_d、δ = p10 − p01、π = B が勝つ不一致の割合（δ = p_d(2π−1)）、Var(d) = p_d − δ²。
- C7-1. 情報を持つのは discordant item だけ（Miller Eq. 7 で tie は d=0）: SE(δ̂) = sqrt((p_d − δ²)/N)、δ≈0 の 95% 半幅 h = 1.96 sqrt(p_d/N)。N=8: p_d .10→±0.22、.25→±0.35。N=30: ±0.11 / ±0.18。N=100: ±0.062 / ±0.098。N=300: ±0.036 / ±0.057。N=1000: ±0.020 / ±0.031。**N ≥ 3.84 p_d/h²（h=.05, p_d=.10 → 154、p_d=.25 → 384）。** 閾値変更では flip しない item は情報を持たない（label は旧・新の閾値付近の flip 集合に使う）。slot 順序の変更では 9 枠に出入りする item が discordant で、両 policy 下で label が要る。1 policy の水準の Wilson 95%（p=.5）は N=10 で ±0.26、30 で ±0.17、100 で ±0.096。4/8 → [0.22, 0.78]、7/8 → [0.53, 0.98]、著者の陽性 4/5 を recall → [0.38, 0.96]。
- C7-2. 正確な sign test（両側 α=.05）で有意になるには **D ≥ 6**。D 件のうち B が勝つ最小割合: D=6 で 6/6、10 で 9/10、15 で 12/15（80%）、20 で 15/20（75%）、40 で 27/40（67.5%）、100 で 61/100。陽性が 5 件なら不一致対の陽性側は高々 5 件で有意になりえない。
- C7-3. 検出力 80%・α=.05 両側に必要な discordant 数（sign test の正規近似。exact は数件増える）D = (1.96·0.5 + 0.8416·sqrt(π(1−π)))²/(π−0.5)²: π=.60→約 194、.65→約 85、.70→約 47、.75→約 29。holdout の大きさは N_h = D/p_d（例 π=.70, p_d=.15 → 約 313）。Miller 形 N = 7.84(p_d − δ²)/δ²（p_d=.10, δ=.03 → 約 860）。MDE = 2.8 sqrt(p_d/N_h)（N_h=100, p_d=.10 → 0.089）。HT 重み付きの label では N を Kish の n_eff = (Σw)²/Σw² に置く。**label の誤り（対称・独立）e は π−0.5 を (1−2e) 倍に減衰させ、必要な D は約 1/(1−2e)² 倍**: e=.10→1.6 倍、.15→2.0 倍、.20→2.8 倍。閾値付近の silver label は平均より悪い可能性が高い。
- C7-4. クラスタ。独立の単位は item でなく question-day（または question）。Miller Eq. 8 かクラスタ bootstrap（question-day 丸ごと再標本）。DE = 1+(m−1)ρ、m≈9、ρ=.2 で DE=2.6（SE×1.6、n_eff=N/2.6）。両 policy に効く日・問いの共通効果は d で相殺するので d 上の ρ は水準より小さいかもしれない（Miller の paired 化の論法からの推論）。少数クラスタ（G < 約 30–50）では Eq. 8 に補正が無い。split は question-day の hash で行い、クラスタ丸ごと dev か holdout に入れる。陽性の有無で hash を層化する（単純 hash だと陽性 5 件のうち holdout に入るのは偶然の 1–2 件）。
- C7-5. 同じ holdout の再利用で k 個の candidate から最良を選ぶと、真の効果が全部 0 でも選んだ推定値は s·E[max of k 標準正規] だけ上振れる（s は holdout 推定値の雑音 SE）: k=2→0.56、5→1.16、**10→1.54**、20→1.87。N=100, p_d=.10 で s=0.032 なので「+5 点の勝ち」は null 約 10 回のうちの期待最良。Ladder 型の規則（champion に対する holdout 利得が約 1 s か η を超えたときだけ採る）は安価な防護。
- C7-6. 非劣性 gate の大きさ。δ の片側 95% 下限が −m を超えなければ block。真に同等の candidate が通る確率 1−β には m ≥ (1.645+z_β) SE、つまり N ≥ (1.645+0.84)² p_d/m² = 6.2 p_d/m²（通過率 80%）: p_d=.10 で m=.10→62、.05→248、.02→約 1,545。N_h=100, p_d=.10 で gate が分解できる最小のマージンは約 ±0.08（m=2.49×0.032）で、それより小さいマージンは良い candidate を無作為に block する。実際の −m の後退は確率 1−α でしか捕まらず、−0.5m の後退は約半分が通る。この n では gate は gross loss の alarm（PROCTOR の「gross failure」の役割と一致するが、導出の理由は別）。マージン 0 の集合: 著者の少数の陽性を must-keep set（canary 的）にして 1 件でも落とせば block する決定的検査 [推論]。
- 検算用: `scipy.stats.binomtest(k, D, 0.5)`、`statsmodels proportion_confint(k, n, method="wilson")`。`NormalIndPower` は paired でないので使えない。C7-3 の式か、d_i ~ {−1,0,+1}（確率 p01, 1−p_d, p10）のシミュレーションを使う。

### D. 反証（失敗しうる点と別の枠組み）

**D1. 決定的ログ下のランキング OPE（ICLR 2026 poster, arXiv 2603.21485 v1, 2026-03-23）** — https://arxiv.org/html/2603.21485v1 （poster: https://iclr.cc/virtual/2026/poster/10011924）— [FULL]（先頭 100,000/121,974 字、要約器経由。著者名は未確認）
- 主張: ranking 単位の IPS は ranking の common support が要り、決定的ログでは「満たされない」。偏りは下向き（Theorem 2.1）。position 単位の IIPS・RIPS も同様。CIPS は positivity を click 単位に移し、item の報酬が slate の残りと独立（Cond. 3.2）を仮定し、ログ上の click と両 policy 下の click 確率（実験では 3 層 NN）が要る。KuaiRec・ε=0 では「無視できない bias」が残り「どの推定量にも極めて難しい設定」と自認。分散は ranking の長さで増える。根拠: 合成・半合成のシミュレーションのみ。
- jrp との違い: (1) jrp の「報酬」は click でなく O1（pipeline 自身の prose が paper を引くこと）で、確率的な click に positivity をぶら下げる CIPS の手が使えない。(2) routing が決定的な閾値なので、閾値の下の item には下流の結果が一切無い（support ゼロ）。(3) writer が 9 slot を同時に見る LLM で、Cond. 3.2 が崩れる。
- 移せる: 決定的ログでは IPS 系が構成上偏る。ログの replay は support がログ集合を出る新 policy には不偏と主張できず、オフラインの数は direct-method（model-based）推定として明示する。

**D2. Replay 法の条件（Li, Chu, Langford, Wang, WSDM 2011, arXiv 1003.5956 v2）** — https://arxiv.org/html/1003.5956v2 — [FULL]（要約器）
- 前提: logging policy が各 arm を一様無作為に選び（確率的 logger なら rejection sampling）、event は iid。Theorem 1: 履歴の確率が評価側と実世界で同じ。1/K の event が残る。記事の出入りや再閲覧で iid が実際には崩れ、その場しのぎで処理したと著者が述べる。
- jrp との違い: logger が決定的（一致確率は 1/K でなく 0/1）。stream は iid でない（state が採用 claim で増え、「first cited」は履歴依存）。決定的 logger では一致する event は新旧 policy がもともと一致する部分だけで、評価が要らない部分。

**D3. LLM judge の過大評価と confidence の飽和（Yu, Li, Zuccon ほか, arXiv 2602.17170 v2, 2026-02-20）** — https://arxiv.org/html/2602.17170v2 — [FULL]（要約器）
- データ: 4 つの open-weight LLM（Llama-3.2-3B, Gemma-3-4B, Mistral-7B, Qwen-3-8B）、TREC DL19/DL20 の passage、人間 label との比較。
- 主張: pointwise 二値 label は 18.6–44.8% 過大評価、graded は 44.6–66.5%。query 語や query 文字列の挿入、passage を長くすることで label が膨らむ。token 単位の confidence は飽和し未較正（二値で全 model が誤りでも 95% 超）。confidence は信頼度の信号でないと結論。限界: 小モデル 4 つ、passage ranking、logit の confidence のみ。
- jrp との違い: Jev は別クラスの量子化確率 judge で、jrp の入力は長い abstract/本文 + 問い + `not:`。screening では未検証。
- 移せる: (1) 1.00 に張り付く飽和には公表された並行例があり、高い側では cut からの距離が情報を持たない。(2) 過大評価は語彙 cue 駆動で一方向なので、誤りは paper の表層特徴（タイトルに query 語）と相関し、ランダムな反転でない。

**D4. Reward hacking** — arXiv 2607.05904（2026-07, "More Convincing, Not More Correct: Self-Play Reward Hacking of Reference-Free LLM Judges", https://arxiv.org/abs/2607.05904）、EvilGenie arXiv 2511.21654（2025-11, https://arxiv.org/abs/2511.21654）— [SNIP]（未開封）
- 要約: judge の pass rate が 0.72→0.94 でも真の精度は GSM8K で不変。誤りは judge 系列をまたいで転移し、3 judge の ensemble でも 55% を受理。EvilGenie: hacking の検出で held-out test は judge に少ししか足さない。単独・未再現の preprint。
- jrp との違い: RL/self-play の強い最適化圧。数百 label で 1〜2 個の閾値を調整するのは弱い圧。
- 移せる [推論]: Goodhart の危険は、同じ label で比べる candidate の数に比例する。試した candidate の数を数え、勝者 1 つの held-out 結果だけを報告する。

**D5. Conformal risk control（CRC）と Learn-then-Test（LTT）** — CRC arXiv 2208.02814（https://arxiv.org/abs/2208.02814 、v1 2022-08、v4 2025-06-13、abstract のみ [ABS]）、LTT arXiv 2110.01052（Annals of Applied Statistics, DOI 10.1214/24-AOAS1998、snippet [SNIP]）
- CRC は任意の単調な損失の期待値を制御する（O(1/n) まで tight、例に false negative rate）。前提（2026 年の CRC 文献の snippet 経由）: calibration と test の交換可能性、損失が閾値 λ について非増加。LTT は各 candidate 閾値を二項尾部で検定し family-wise 補正で高確率（PAC）制御を与える。
- 標本サイズ [導出。note 本体の式表記は n_pos ≥ ln(1/δ)/α の近似、表の値は厳密な二項下限 n_pos ≥ ln δ / ln(1−α) による。値は手計算で一致を確認]: 校正「陽性」のうち見逃し 0 件で FNR ≤ α を信頼度 1−δ で証明するのに、α=0.10, δ=0.10 で 22、α=0.05, δ=0.10 で 45、α=0.05, δ=0.05 で 59。K=15 の candidate 閾値に Bonferroni（δ/K）をかけると α=0.10 で 48、α=0.05 で 98。見逃しが 1 件増えるごとに要求が増える。数えるのは陽性で、全 label 付きペアではない（keep 率が低いと陽性を over-sample しない限り標本が大きくなる）。
- 比較できるか: 1 つの scalar 閾値の 1 つの損失（FNR）を証明するだけで、順序の比較はできない（順序の損失は λ について単調な scalar でない）。保証を買うもので label の請求額を小さくはしない。
- jrp との違い: 保証は labeler（Opus silver）の FNR についてで真の FNR ではない。週ごとの drift（問い・Jev の更新）とペアの paper/問いによるクラスタで交換可能性が崩れる。Jev の score は 0.01 格子で 1.00 に質量がある。

**D6. CRC/LTT の実務での失敗（Gurram, "Valid Per-Field Selective Risk Control for Document Extraction", arXiv 2608.14639, 2026-08, 単著・venue なし）** — https://arxiv.org/html/2608.14639 — [FULL]（HTML、要約器。PDF はバイナリで読めなかった）
- 対象: 文書抽出の field ごとの LTT / split-conformal、名目 α=0.10、CORD（FUNSD, XFUND-de も）を 40 回 resplit。
- 主張: (1) クラスタで有効な calibration サイズが約半分（design effect 1.84–2.45）。pooled split の add-one 規則は split の 50% でリスク目標に違反。(2) score と閾値を同じ data で再 fit すると楽観的で、coverage 0.416 / risk 0.127、95% の split で違反。(3) 離散で縮退した score は閾値格子を潰す（distinct な calibration score 1,702→257、certified coverage 0.030→0.001）。細かい格子は certification を殺し、幾何的な 15 candidate を使った。小 n: 42 文書で LTT は coverage 0.080 を certify するが split の 82.5% は何も certify しない。約 400 文書でも最も厳しい tier は 19/40 の split で certify なし。label は自動で、「noisy な label に対する certificate は、それらの label についての certificate」。
- jrp との違い: タスクは field 抽出で score は学習済み。jrp の score は Jev で 0.01 格子・tie が多く、tie の質量の病理が最も近い。paper・問いによるクラスタは design effect の類似。
- 移せる: 著者確認の数十件は 42 文書の規模で、保証の大半が空だった領域。3 つの失敗（クラスタの ESS、同じ split での tuning と certify、tie 質量）は jrp の data で検査できる。

**D7. CRC における noisy / LLM 生成 label** — arXiv 2609.01375（IntroConformal, https://arxiv.org/pdf/2609.01375）、2607.24562（階層 group-conditional CRC, https://arxiv.org/pdf/2607.24562）、2602.13110（SCOPE, pairwise LLM judging, https://arxiv.org/pdf/2602.13110）— [SNIP]（未開封）
- 要約: 5–15% の random flip は calibration risk を水増しして閾値を保守側へ寄せ、test risk は目標以下に収まる。うち 1 つの著者は、系統的な annotation bias はリスクを水増しせず許容的な閾値を選びうると述べる。証拠は random flip のみ。
- jrp との違い: silver label の誤りは random flip でない（D3: 過大評価は cue 駆動で一方向）。FNR への bias の符号は labeler の偏りで決まる [推論]: over-call なら Jev が低く付けた偽陽性が増え FNR が高く出て閾値が緩く、under-call なら真の陽性が陰性になり FNR が低く出て閾値が厳しくなる。
- 移せる: CRC/LTT を使う前に、著者確認の数十件で Opus と著者の誤りの向きを測る（一致率だけでなく）。

**D8. repo の事実（web でなく設計 doc）** — `docs/design/pipeline-design.md:173-195`（本 report 作成時に再読し、O1・分解・slot の定義が note の記述と一致することを確認した）
- O1 = 週内に prose が初めて引いた paper（paper key = arXiv id、なければ DOI、GitHub、正規化 URL）。週次の分解は O1_c = N_ot × p_sel × p_ext × p_wri（直近 2 つの成熟した cohort, 7 日）。保存済み screening Judgment は `judged_of` で再適用されるので p_sel は新しい閾値で正確に再生できる。p_ext（QuestionLog 上の claim）と p_wri（writer が [n] で引く）は logged policy が keep した item でしか観測されない。slot = claims_per_question(k) × k、「slot-bound」は空き slot ≤ 30%。
- 帰結 [推論]: 新しい閾値の replay は p_sel を正確に出すが p_ext × p_wri は既に keep 済みの item にだけ出る。新たに keep される item（旧 cut の下）には imputation が要り、cut の下に overlap の根拠が無い direct-method モデルになる。O1 は slot が埋まるまで keep 率に単調で緩める側を好むので、単独の tuning 目的にすると閾値が下がる（precision や読者の価値は制約にする）。O1 は paper key ごとの初回引用で、同じ paper が 2 ライン・2 問いで届いても 1 回、先の引用が後の週から除く。item の寄与は他に何を keep したかと履歴に依存する集合レベルの報酬（coverage 関数）で、item 単位の silver label の和は O1 にならない。順序の「ユーザー」は LLM writer（p_wri）で、writer の位置 bias が click の位置 bias の類似物。ログでは順序が score で決定的なので位置と score が交絡する。writer は呼べる model なので、並べ替えた slate で writer を再走させる無作為順序の replay を安く作れる（案。LLM writer の位置効果の出典は未読）。
- note 記載（出典 file 不明、未検証）: 再 judge で route の 14% が反転、judgment の 37–39% が 0.6 の cut の ±0.05 以内。near-cut の対を繰り返し judge すれば経験的な keep propensity p̂ ∈ (0,1) が得られ、cut の近くで IPS/DR が定義できる（案。regression-discontinuity や noise-as-exploration の OPE の出典は未検索）。同一 state の再 ask の雑音 2–3/40 は小さいが実在する。

**D9. 失敗しうる点（note の順位付け = researcher の判断。根拠 item を併記）**
1. support の欠落（雑音でなく）: 旧 cut の下の candidate には下流の結果が無く、推定は外挿（D1, D2, D8）。direct-method と明示するか、探索（near-cut の再 judge、無作為順序の writer replay）を作らない限り因果とは言えない。
2. O1 は緩めるほど上がり、集合レベルで履歴依存（D8）。
3. 数十件の著者確認は保証・安定比較が成立する大きさに満たない（D6: 42 文書で 82.5% の certificate が空）。
4. writer 側の同系統の循環: silver labeler = writer model（B6 + `AGENTS.md`）。
5. silver label の bias は方向性があり、random flip の頑健性は当たらない（D3, D7）。
6. 同じ label での多数 candidate の選択（D4）。
7. Jev の tie 質量と 0.01 格子: candidate 閾値は少数で、約 0.95 超の score は情報を持たない（D3, D6）。

**D10. 別の枠組み（found / implied）**
- 凍結 state の direct simulation を「model-based 推定」と明示し、near-cut 帯の探索データを足す。
- CRC/LTT（D5）: 「ある labeler について FNR ≤ α の最も緩い閾値」を選ぶ問いに向く。順序には向かない。α 0.05–0.10 で見逃し 0 件の下に陽性が約 50–100 件要る [導出]。クラスタと tie に弱い。
- 決定理論的な閾値（出典なし、推論のみ）: 較正済み確率での最適 cut は c_FP/(c_FP+c_FN)。Jev の飽和した score への単調な較正（label 上の isotonic）と著者が述べる費用比が要る。label の数を費用比の選択に置き換えるが、保証は与えない。
- TAR/e-discovery の recall 証明と elusion sampling（「捨てた山から標本を取って見逃しを上界する」）— A4・A6 に統合。

## 内部の実測（store の写し、2026-10-20）

出典: lead の script を本番 store の写しで回した結果（web 由来でなく、本 report の調査者は再計算していない）。

- screening v3 の Judgment（2026-10-02〜10-20）: akc 505、aap 479、authorship 628、ans 23、desire 112、edge 151、jev 1,478（うち 35 件は store に source の無い canary の probe）。(source, 問い) 対は計 1,213。
- state の再構成率（question_screening.state を store から組み直し、その sha256 が Judgment.state_sha256 と一致した割合。問いの文言は Question node と questions/ の git 履歴から、evidence_set は runner.claims_before と同じ「前日までに報告された claim」で絞る）: akc 96.6%、aap 98.8%、authorship 98.1%、ans 78.3%、desire 100%、edge 98.0%、jev 91.9%（probe を除く）。全体 3,181/3,341 = 95.2%。
- X の掲載枠: 日ごとの候補（その日の novelty Judgment で novelty.rule を通り、前日までに報告されていない claim）を組み直すと 97 line-day・3,260 件。実際に載った 495 件はすべて候補に入る。並べ順の鍵を Decision.score（= min(bears_on, checkable)、claim_detection.rule の値）にして上限を再生すると、161 節中 142 節（88%）で載った claim の集合が一致する。鍵を bears_on にすると 69 節（43%）。残り 19 節はほぼ 1 件の入れ替わりで、0.01 格子の同点を run の入力順で割った差とみられる（未確認）。
- `/claude-api build-eval` と hillclimb の適合: build-eval は「Claude を呼ぶアプリを case ごとに走らせ、出力を採点する」形で、runner の scaffold は model 呼び出しと served-model の検査が前提。jrp の S/X は保存済みの Jev 判定にコードの policy を当て直すだけで、ラベルは入力ごとに 1 回付ければ全候補で共有できる。入力と採点法の 2 つの sign-off は著者との対話が前提だが、著者は Respond を待たずに進めるよう指示している。よって runner は repo の流儀（`jrp eval gate`、prose bench と同じ置き方）で自作し、eval-audit の点検項目（oracle と null の通し試験、infra の失敗を errors に分ける、混同行列の指標、雑音の床、生の行から見出しを計算し直す）だけを取り込む。

## Contradictions

- **PROCTOR 対 著者の harness の rule `evals.md`**: rule は「test 側が数件しかない eval では hillclimb せず回帰 gate に留める（holdout 4–8 件は noise — PROCTOR arXiv 2609.02246）」と書く。PROCTOR の本文（C1, 画像を直接読んだ verbatim）は、4–8 件の holdout を「smoke alarm であって measurement でない」と呼び、**hillclimb している**（保持の判断は train set の再評価）。20 件未満の suite は holdout 自体を省く。"noise" は holdout の文脈に無い。強い根拠は PROCTOR でなく二項の算術（C7-1・C7-2: N=8 で ±0.22–0.35、不一致対が 6 件未満なら sign test は有意になりえない）。rule の結論（少数 holdout は測定でなく alarm）は算術で支持されるが、引用元と「hillclimb しない」の部分は PROCTOR に無い。PROCTOR は単著 v1 preprint・内部システム・統計検定なしで、根拠としての重みは弱い。
- **小 N の bootstrap（Bowyer）対 bootstrap を使う gate**: Bowyer（C3, シミュレーション）は N≤100 で bootstrap 区間が "performed poorly" とし Wilson / Beta-binomial を勧める。OneUptime（C6, 意見 + コード、データなし）は paired BCa bootstrap を回帰 gate の区間にし、GLIDE（B3）も n<50 で bootstrap 系の PTD を勧める。重み: Bowyer（シミュレーションがあり jrp の n に合う）。ただし Bowyer の bootstrap は単一 model の精度が主で、tie だらけの paired 差の bootstrap は未検証。GLIDE の PTD は n<50 の coverage を報告していない。Miller（大 n、bootstrap 不要、「少なくとも 1,000 問」）は別の n 域で、真の衝突ではない。jrp は Bowyer の域にいる。
- **PPI は効く 対 人間 label が少なすぎる**: PPI 系は judge の bias を補正して coverage を保ち（B1, B3, B4）、PRECISE は n=30 で SE −21%、GLIDE は n=100 で CI 幅 −20%。一方 (a) 効率の上限は 1/(1−ρ²)（Dorner, B2: ρ=0.7 で約 2 倍、人間 36 件が実効約 70 件）、(b) CI 幅 0.1 未満に約 200 件（Lee, B5）、(c) GLIDE 自身が 50 件未満で CLT 系をやめ、層あたり約 20 件の事例は自身のルールに反する、(d) StratPPI は事前に固定した層から抽出する必要があり既存の tick（確率標本でない）は使えない（B1）。n 数十・希少陽性・二値での PPI/PTD の実測 coverage は見つからなかった。数十件の人間 label は「judge が壊れていない」の検査には足りるが補正値の推定には足りない、という整理（B8）が、どの根拠とも矛盾しない最も保守的な読み。
- **層別標本を一様 prior で評価する 対 half prior**: Webber（A4）は低有病率で一様 prior が強すぎて recall を過小評価するとして α=β=0.5 を推奨。Bowyer（C3）は 1 モデルの精度に一様 prior の Beta(1+S, 1+N−S) を推奨。推定対象（recall の比 vs 精度の水準）と有病率が違うので、同じ prior が使えるとは限らない。jrp の層（陽性率が非常に低い低スコア帯）は Webber の域。
- **tick を recall に使う 対 positivity**: PU の補正（A1）は SCAR/shared-component を前提に α を要し、SCAR なら PU 指標の順位は保たれる（A2, SNIP）。tick は配信・slot・著者の閲覧を通った item にだけ付くので drop 側は propensity=0 で、順位の保存も補正も成り立たない（A9）。tick の過程は 10-08 以降ほぼ止まっており非定常でもある。tick は floor check にとどまる。
- **random flip への頑健性 対 一方向・cue 駆動の誤り**: noisy-label CRC の snippet（D7）は 5–15% の random flip で test risk が目標以下に収まると言う。judge の誤りの文献は一方向の過大評価（D3: 18.6–44.8%、query 語の挿入で膨らむ）、judge 平均が真値を 13 点上回る例（B3: 0.655 対 0.525）、相関誤り（B10）を示す。jrp の silver label の誤りは後者の型なので、random flip の頑健性は当たらない。Opus と著者の誤りの向きは未測定。
- **強い judge が弱い対象を採点する 対 相関誤り**: Dorner（B2）は judge が対象より強いと効率が 2 倍を超えうる。Kim ら（B10）は大きく正確なモデルほど vendor をまたいで誤りが相関する。「Opus 5.5 は Jev より強い」ことは効率に有利だが、「Opus は著者の関連度に対して Jev より独立な誤りを持つ」ことは保証しない。どちらも jrp の data では未測定。
- **Clarke–Dietz の数値のラベル**: 全 system が UMBRELA を最終段に使う設定の τ=0.63 を、角度 2 の note は「全体」、角度 4 の note は「top 60」と書く（0.44=top 20、−0.40=top 5 は一致）。0.63 の範囲は未確定。決定に効く数（0.89→0.51、−0.40、uwc1 の 5 位 → 28 位）は一致している。
- **CRC の標本サイズ式の表記**: 角度 4 の note は n_pos ≥ ln(1/δ)/α と書くが、表の値（22, 45, 59, 48, 98）は厳密な二項下限 ln δ / ln(1−α) の値で、近似式からは 23, 46, 60 になる。値は手計算で再確認済み。
- **再利用 holdout**: Ladder の最悪ケース（Ω(sqrt(k/n))、C4）と Roelofs の「overfitting はほぼ無い」は、敵対的 query か経験的な利用かの違いで両立する。jrp の週あたり candidate 数では通常の winner's curse（C7-5: k=10 で約 1.5 SE）が支配的。

## Still unknown

- 層別 Beta-binomial（A4 の一般化 A9）の jrp の n（層あたり数十件、陽性が 1 桁）での実際の被覆。既知の合成陽性を置いた繰り返し抽出で検査できる（未実施）。PPI/PTD の小 n・希少陽性・二値での被覆も同様に未測定。
- 日本語（と中国語）での Opus 5.5 と著者の関連度判断の一致、および「Opus の誤り」と「Jev の score」の相関（差次的誤分類）の大きさ。最初の blind 確認数十件が最初の測定になる。
- 少数クラスタ（question-day が約 30–50 未満）での推論。wild cluster bootstrap-t は未読、Miller Eq. 8 には補正が無い。同じ paper が複数の question-day に現れるとき（重なるクラスタ、two-way clustering）の扱いも未確認。
- 非劣性マージン m の一次資料。LLM-eval の gate でマージンを選ぶ根拠は見つからなかった（OneUptime は「product decision」）。
- 保存判定から実際に出る p_d（典型的な閾値・slot 順 candidate で何件が flip するか）と層ごとの N_h・陽性率・drop と review の件数。C7 の N は p_d に比例する。1 回の replay で出せる。slot 順の candidate が日の item 集合を変えるなら、paired の単位は日で、結果は 9 枠内の silver 陽性数のような量になり、新規 item は item 単位の paired 化を壊す。
- 内部の実測で 19 節が一致しなかった理由が 0.01 格子の同点（run の入力順での割り方）かどうか。D6 の tie 質量の病理とは別に、同点の解決順の確認が要る。
- 著者の tick が「関連」か「今日読みたい」かで、tick が silver label の検証に使えるかが決まる。著者 1 件あたりの確認時間と blind 判定の所要が予算内かも不明。
- 未読の一次資料: PPI 原論文と PPI++ 本体、Thomas / UMBRELA / Choi の本文、Lakkaraju 2017 の contraction、Callaghan & Müller-Hansen の検定、Lewis 2021 の標本サイズ、Di Nunzio 2026 の本文、Sawade 2010 / Poms 2021 の最適 proposal の式、LTT の有限標本の項、重み付き CRC/LTT、LLM writer の位置 bias の測定、Thresholdout の query 予算、PROCTOR の pp.1–2, 6–7、Indeed engineering blog（2026-07）、ClawProBench arXiv 2608.22510、ExplainRoute arXiv 2609.03470、arXiv 2608.22659 の本文。
- 失効条件: PROCTOR は v1 preprint（2026-09-02）なので v2 / 査読の有無で変わる。Webber の beta-binomial recipe が小 count の既定でなくなる新しい TAR / LLM-judge recall 推定の論文（arXiv cs.IR "recall estimation"）が出るか、標本設計が one-shot 層別から適応型に変わったら A4・A9 を見直す。GLIDE（v2 2026-06-04）の n=50 の閾値と PRECISE の 100 倍則は 1 データの rule of thumb で、2026 年の blog・library 記述は数週間で古くなる。Bowyer / Miller の導出は安定。

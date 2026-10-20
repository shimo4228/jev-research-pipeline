kind: external
# intake の候補構成を、凍結した fetch 結果の上で比較・採点する方法（`jrp eval intake`）
as-of: 2026-10-20（4 本の notes の統合。各 claim の日付は出典の公開日または取得日 2026-10-20）

この report は 4 角度の notes（freeze-replay / capture-recapture / query-performance / adversarial）を全部 Read して統合したもの。notes に無い主張は足していない。Verdict は plan 側で書く。読み手は次セッションの LLM で、各項目に「読んだ範囲」を付けた。決定に効く主張でも snippet / abstract 止まりのものはそう書いてある。

## Scope searched

4 角度の呼び出し数は目安（10〜15）を超えた。freeze-replay 約 20 回（うち 4 回は PDF が decode できず読めず）、capture-recapture 約 38 回（PDF のページ画像読みと、PMC / PubMed / BMJ の captcha・403 が多かった）、query-performance 約 19 回（Springer のリダイレクト loop 2 回と接続拒否 1 回）、adversarial 18 回 + 保存 PDF の Read 1 回。

読んだ範囲の凡例（以降、各項目に付ける）:
- FULL: 本文を読んだ。FETCH-SUMMARY: fetch tool が返した要約で、逐語ではない。ABSTRACT: abstract / landing page のみ。SNIPPET: 検索結果の文面のみ。META: registry の JSON。NONE: 取得できなかった。
- [INFERENCE] / REASONING: 出典が無く、researcher が jrp の状況に合わせて導いた推論。事実として扱わない。

角度ごとに見た source:
- freeze-replay: pooling の reusability と pool bias、bpref / condensed list / judged@k、MTC（Carterette）、arXiv 2503.09899、Rank1、BrowseComp-Plus（arXiv 2508.06600）、arXiv 2502.20937、LLM 判定者（UMBRELA / Thomas / Soboroff / Yu / Gienapp）、vcrpy の設定 doc。
- capture-recapture: Chao 1987（FULL、9 ページ）、Gotelli & Colwell 2011 ch.4（FULL、Box 4.1）、Chao & Colwell 2017 SORT 41(1)（FULL §1–2.4）、vegan::specpool、arXiv 2404.01176（FULL、26 ページ）、Spoor 1996、Kastner 2009 系、Motschall 2009、Tsay & Chao 2001、Sampson 2006（FULL）、Bramer 2017、scikit-bio / PyPI / python-allib。
- query-performance: Lagisz 2025（relative recall）、Hausner（objective approach）、Wang 2025 / Staudinger 2024 / 2026 追随（LLM Boolean query）、Bramer 2017、living review / surveillance、QPP-GenRE、Ntoulas 2005、Smucker 2009（FULL）。
- adversarial: Chatterjee & Bhuyan（arXiv 1703.03022）、Chao 推定量の lower bound 性、Cochrane Colloquium 2009、pool bias（Lipani / Buckley / SIGIR 2015）、OPE（Tanaka ICLR 2026）、LLM judge の偏り（Balog 2025 / Alaofi 2024 / Clarke & Dietz）、PPI（ARES / GLIDE）、TAR stopping（Repke / Lewis 2021）、interleaving（Amazon / Airbnb）。

探したが見つからなかったもの:
- 同一入力で LLM 判定者を繰り返し走らせ、その分散を system / config の順位に結びつけた研究。「同一状態で classifier を再質問して noise floor を先に測る」手順は、この調査で引ける先行例が無く、jrp 側の自前プロトコルになる。
- 「nDCG と併せて judged@k を報告せよ」という正式な基準。診断の習慣として語られているだけ。
- Python の Chao2 / iNEXT / ICE 実装（PyPI `inext` は 404、web 検索 3 回でも未発見。PyPI 索引外の存在は排除できない）。
- 「ゼロ新規が n 回続いたら query を退役させる」型の規則（SR の living review・研究アラート。2 回検索して無し）。search-term 単位の unique yield を扱う SR 実務も無し（database 単位のみ）。
- 「at least 10 sampling units」という Chao2 の最小 unit 数の一次根拠（Contradictions に詳細）。
- 依頼 brief にあった「Repke 2026 CMH」の論文（2025 年の preprint と data record までで、本文は 403 で未読）。
- 単一ユーザーの switchback / N-of-1 の設計指針と標本数。
- pytest-recording / respx の挙動（検索結果が vcrpy に偏り、検証していない）。
- infAP / statAP の原論文、Zobel 1998、Buckley & Voorhees 2004 (bpref)、Sakai 2007、Buttcher 2007 の原本。
- EstimateS User Guide と Chao & Chiu 2016（Wiley StatsRef）。
- Goodhart / 固定 judge への過適合、bandit による query 選択、test collection の時間 drift（adversarial は検索せず）。

## Found

### A. 凍結と replay（freeze-replay 角度）

#### A1. depth-k pooling と、pool に寄与しなかった system への bias — State of practice（SNIPPET）
- 何か: test collection は寄与 run の上位 k 件の和集合（pool）だけを判定し、未判定は非関連と仮定する。出典: https://webis.de/downloads/publications/slides/froebe_2023a.pdf（検索経由の snippet）。
- 根拠の種別: collection 実験（leave-one-run-out 型）、人手判定。snippet で見えたこと（as-of 2026-10-20）: Zobel の初期研究は pooling が関連文書の最大半数を取りこぼしても system の順序はあまり変わらないと見た一方、より新しい collection では重い bias が出ている。NIST の AQUAINT 2005 研究は、寄与 run が多様でも pool が collection の大きさに対し浅すぎて bias が出たとする（https://www.nist.gov/node/620291）。SIGIR 2015 の open test collection 研究は、pooling の影響が目立ち、非 pool の system が過小評価されるとする（https://www.e.humanities.uva.nl/publications/2015/hash_on15.pdf、PDF は NONE で数値未読）。TREC-COVID では、title の語を多く含む文書など特定の性質を持つ文書が pool に偏るとする（https://ir.nist.gov/trec-covid/papers/halfround.pdf、snippet）。
- こちらとの違い: jrp の判定者は自動で 1 件あたり安い。全候補の凍結出力の和集合を丸ごと判定でき、人手予算を理由に pool を浅くする必要が無い。pool bias が再び出るのは、(a) どの凍結出力にも入っていない item（新候補、cassette の miss）と、(b) classifier 費用を惜しんで判定を省いたときだけ。
- 移せる部分 [INFERENCE]: pool = 全候補の凍結 item + 過去の store item。1 つの judge version で一度だけ全部判定し、全候補を同じ判定済み集合で採点する。firehose cap は depth-k pooling に対応する（候補の並び順が「system」、300 が深さ k）。pool は全候補の並び順の上位の和集合にするか、overflow が小さければ cap 外の未判定 overflow を丸ごと判定する。候補ごとに、取得 item のうち delta を判定する前から保存済み判定があった割合（judged@k の類似物）を報告する。

#### A2. 不完全判定の metric: bpref / condensed list / judged@k — State of practice（SNIPPET）
- 何か: 欠けた判定への対処は 2 系統。metric を変える（bpref）か、判定を変える（Buttcher らは偏った pool 判定から偏りの小さい判定集合を作り、判定が豊富で偏る場合は bpref より高精度と報告）。condensed list（未判定を順位から除いてから計算）は判定が不完全だが偏りが無いときに効く。AP' と Q' は bias 下でも bpref・RBP・condensed RBP より概ね良い（Sakai 系、https://ipsj.ixsq.nii.ac.jp/records/66516 の snippet）。judged@k は教科書 "Pretrained Transformers for Text Ranking"（https://arxiv.org/pdf/2010.06467、snippet）で、上位 10 の 80% が未判定なら P@10 は 0.2 が上限、と最も単純な診断として述べられる。未判定を非関連にも関連にもする素直な解は無い。
- 根拠の種別: metric 比較の simulation（Sakai・Buttcher）、教科書。原論文は未読。
- こちらとの違い: これらは人が全部判定できないから存在する。jrp の目的量 N_ot は順位 metric でなく集合の件数なので、condensed list や bpref に対応物は無い。judged coverage の報告には対応物がある。
- 移せる部分 [INFERENCE]: 候補ごとに judged coverage を出す。100% 未満なら穴を判定する（安い）か、件数に明示の下限ラベルを付ける。未判定を黙って off-topic に畳まない。

#### A3. MTC — 系 A と B を分ける文書だけ判定する — Prior implementation（SNIPPET）
- 何か: Carterette, Allan, Sitaraman, "Minimal Test Collections for Retrieval Evaluation"（SIGIR 2006）と Carterette & Allan 2005。https://ciir-publications.cs.umass.edu/pub/web/getpdf.php?id=619（および id=852, 809, 588。PDF の fetch は NONE）。snippet によれば、貪欲なオンライン算法で、各未判定文書を「判定すると 2 system のどちらが良いかがどれだけ明らかになるか」で重み付けして次に判定し、可能な判定の分布から信頼水準を出して停止規則にする。絶対値でなく system の順位付けを目的とし、小グループが 3 時間未満で 95% 信頼の順位付けができたとする。
- 根拠の種別: TREC data での collection 実験（snippet による）。
- こちらとの違い: MTC は AP のような measure の下で人間の評価者に判定させる文書を選ぶ。jrp の count 型 measure では「重み」が単純。
- 移せる部分 [INFERENCE、算術]: 集合 count では N_ot(A) − N_ot(B) = on-topic(A\B) − on-topic(B\A) で、共通部分は相殺する。ペア比較に必要な判定は対称差だけ。絶対 N_ot と new-rate には共通部分も要る。判定を (item の content hash, question, judge version) で cache すれば、共通部分は両候補で同じ label になり judge の揺れは相殺し、delta item だけが揺れを持ち込む。候補ごとに引き直すと全体の揺れが入る。MTC の信頼度による停止は、delta item をランダム順に判定し、ペア差の区間が 0 を外れるか delta を使い切ったら止める、に移せる。集合 count での検証例は見つからなかった。

#### A4. Abbasiantaeb et al. 2025 — LLM で pool の穴を埋める — Claim of a paper（FETCH、https://arxiv.org/html/2503.09899v1）
- 設計 [FACT]: 1 system（または 1 team）だけが取った判定済み文書を pool から除き（P_hole）、LLM の label で穴を埋め（P_filled）、P と P_filled で system を再順位付けして、除いた system の動き D を測る leave-one-out simulation。collection は TREC iKAT 23（28 system）と CAsT 22（38 system）。穴の指標は missing judgments / missing relevant judgments / Unjudged@k。一致は Cohen's kappa、順位は nDCG@5 上の Kendall tau。Llama-3.1 は公式 label の 70/15/15 分割で fine-tune。
- 数値 [FACT、Table 2 の伝聞]: GPT-3.5 one-shot 文脈なしの tau は iKAT で 0.862（complete pool）/ 0.778（test）、CAsT で 0.900 / 0.676。fine-tune した Llama-3.1 は iKAT test 0.841、CAsT test 0.881。Llama-3.1 one-shot 文脈ありは 0.550（iKAT）/ 0.710（CAsT）。穴埋め自体の数値 tau は無いが、few-shot Llama-3.1 での穴埋めは穴を残すより元の pool との相関が高く順位の動きが小さい。
- 注意 [FACT]: GPT-3.5 は関連を過剰に予測する。二値一致が高くても順位相関が高いとは限らない。GPT-3.5 の穴埋めは Unjudged@10 が増えるほど順位の動きが大きくなったが Llama-3.1 は違った。8B モデルと 2 collection のみ。fetch 要約は結論の zero-shot と §4.3 の one-shot の内部不整合を指摘したが、原文では未確認。
- こちらとの違い: この論文の難所は人の label の近似。jrp には item ごとの人手 label が無く classifier が on-topic の操作的定義なので、「穴を埋める」は delta に同じ classifier を走らせるだけで proxy gap が無い。
- 移せる部分: 評価設計。ある net / query 集合の固有 item を pool から外して全員を採点し、候補順位の動き D を見る leave-one-candidate-out は、pool 再利用の自己点検になる。Unjudged@k 類似の coverage を追う。

#### A5. Rank1 — judged@10 と穴の annotate — Claim of a paper（SNIPPET、https://arxiv.org/pdf/2502.18418）
- 何か: TREC DL19 で nDCG@10 に Judged@10 を併記。reranker は baseline より judged fraction が低い（RankLlama で 81.9% 対 96.1%）。著者が未判定の上位 10 を annotate するとほとんど関連で、一部 model の nDCG@10 が目立って変わった。新判定は公開。
- 根拠の種別: 1 collection の事後 re-annotation。
- こちらとの違い: 同じ現象（新 system が pool に判定されたことの無い物を取る）だが annotator は人。
- 移せる部分: 比較表に judged fraction を常設の列にする。未判定は非関連と仮定せず判定する。

#### A6. BrowseComp-Plus — live 検索 API の代わりに凍結 corpus — Prior implementation（FETCH、https://arxiv.org/html/2508.06600v1、2025-08、NeurIPS 2025。103,301 字中先頭 100,000 字）
- 構成 [FACT]: o3 + web 検索で BrowseComp の QA に証拠 URL を挙げさせ（1,266 件中 124 件で失敗）、Selenium + Trafilatura で取得、scrape 不能 URL で 137 件を落として 1,005 件、人手が証拠 span と gold document を付け 830 query が通過（一致率 80% 超、400 時間超）。hard negative は GPT-4o が各質問を約 7 個の sub-query に分け SerpAPI（最大 100 件）で取得。最終は 100,195 文書、830 query、1 query あたり証拠 6.1 / negative 76.28 / gold 2.9。
- live 検索への主張 [FACT、ただし論証で実測ではない]: live API は内容が動的で時間とともに変わり、運用費と検索品質のばらつきが大きく、corpus を制御できない。live 検索の実験は無く、snapshot 日付や凍結手順の明示も固定 corpus 以外に無い。
- 頑健性 [FACT]: 約 977 万件の FineWeb-Edu（約 10 倍）を足しても retriever / LLM agent の順位と効果水準の結論は変わらず、絶対精度は下がった（Qwen3-32B + Qwen3-Embedding-8B で 10.36% から 7.11%）。
- 根拠の種別: benchmark 構築 + 1 回の scale-up ablation。
- こちらとの違い: BrowseComp-Plus は corpus を凍結して任意の retriever を local で走らせる。jrp の keyword net（OpenAlex・HF paper search・GitHub・Tavily）は遠隔の ranking 関数で、cassette は記録した request にしか答えず新しい query には答えられない。cassette は「corpus」でなく「記録済み request 集合の pool」。pipeline のうち順位を local で再現できる部分（保存済み日次 firehose への BM25 順序、過去の store item）だけが live 呼び出し無しで新設定を再実行できる。
- 移せる部分: 候補は 2 種に分ける。(i) 凍結済み item 集合の並べ替え・絞り直し（firehose cap・順序・body floor・閾値）は完全に offline で無料。(ii) 新しい request 文字列（query・新 net）は 1 回の live fetch の後に凍結。候補同士の相対比較は 10 倍の distractor 変更に頑健だが絶対水準は動いたので、候補は相対で比べ、絶対 N_ot は日ごとの値として扱う。store と cassette に入った全 item の累積和集合を、並べ替え実験の local test corpus にできる [INFERENCE]。

#### A7. Variations in Relevance Judgments — Claim of a paper（FETCH、https://arxiv.org/html/2502.20937v2、2025）
- 結果 [FACT]: TREC DL'19 の再 annotation。4 段階で Fleiss' kappa 約 0.17〜0.28、Cohen's kappa 約 0.11〜0.19（ほぼ偶然）、二値の Fleiss' kappa 約 0.31〜0.44。annotator の組合せ間で system 順位の Kendall tau 平均 0.879、Spearman rho 0.972 で、著者は評価者の不一致は順位に影響しないとする。例外は LLM 系 reranker とそれから蒸留した system で最も順位が動いた。annotator の nDCG@10 約 0.81 は大まかな上限。
- 実務的助言 [FACT、伝聞]: 複数の判定集合で比較を確かめる（pairwise の順は反転しうる）。人手の上限を超える改善には懐疑的に。
- 根拠の種別: 1 collection の re-annotation 実験。
- こちらとの違い: 異なる人の不一致であって、1 つの classifier の同一入力での揺れではない。多数の item を平均すれば label 水準の noise が集計水準で消える、という最も読み込んだ根拠だが、種類の異なる system（LLM 系）が最も動いた。
- 移せる部分 [INFERENCE]: jrp の「複数の判定集合」= 同じ classifier の 2 回以上の繰り返し（可能なら 2 つ目の prompt / model）。全てで保たれる候補選好は信頼し、反転するものは未解決と報告する。

#### A8. LLM 判定者: UMBRELA / Thomas / TREC 2024 RAG と批判 — State of practice（主に ABSTRACT）
- UMBRELA（arXiv 2406.06519、SNIPPET）: Thomas らの GPT-4o での open-source 再現。TREC DL 2019–2023 で LLM 判定は効果的な multi-stage system の順位と高く相関。
- Upadhyay ら TREC 2024 RAG（arXiv 2411.08275、2024-11、ABSTRACT）: 4 つの評価方式（完全手作業 1 + UMBRELA を使う 3）、19 チームの 77 run 超で、完全自動の UMBRELA 判定は手作業判定と nDCG@20 / nDCG@100 / Recall@100 で高く相関し、run 水準の効果は置換できると著者は示唆。LLM の補助は手作業との一致を上げず、人間の評価者の方が厳しい。読んだ page に kappa・tau は無く、301 topic で run 水準 tau >= 0.86 とする thesis の snippet が二次情報（https://uwspace.uwaterloo.ca/items/4d18073e-d9b6-45e5-91b3-e530dd88dd5f）。
- Thomas ら（arXiv 2309.10621 v3、2024-05、ABSTRACT）: 彼らの gold に対し LLM label は人手と同程度に正確。prompt の体系的変更や単純な言い換えでも精度が変わる。繰り返し実行の揺れの情報は page に無い。
- Soboroff（arXiv 2409.15133、SIGIR 2024 LLM4Eval keynote、ABSTRACT）: TREC 型評価の関連判定に LLM を使うなと勧める。論拠（循環・bias）は未読。
- Yu ら "When LLM Judges Inflate Scores"（arXiv 2602.17170、SIGIR '26）: 題名と venue のみ。本文 NONE。
- Mohtadi ら（arXiv 2512.05334、2025-12、ABSTRACT）: 要約に基づく判定は全文判定と同程度の順位安定性だが label 分布は model・dataset ごとにずれる。ここでの「安定性」は要約対全文で、繰り返し実行ではない。
- Gienapp ら（arXiv 2510.04633、2025-10、SNIPPET）: 1 topic・1 評価者の判定で LoRA fine-tune した topic 固有 monoT5 が正解 system 順位と Spearman rho > 0.94、topic あたり 128 件の初期人手判定から比較可能性が上がる。
- 根拠の種別: 人手 qrels に対する system 順位の相関、および論証による批判。
- こちらとの違い: 全部「LLM 判定者を人手 qrels で検証する」研究。jrp で未解決なのは、自分の item での判定者の再現性と閾値感度、on_topic >= 0.5 が著者の考えと合うか。文献の多くは jrp が比べる集計水準と同じ run 順位水準で検証しており、label 水準の揺れは少ない。
- 移せる部分: (a) judge の prompt / model / version を全候補で固定する（Thomas の言い換え感度）。(b) 一様な judge bias は絶対 count をずらしても候補順は変えないことがありうるが、item の型（query 文との語の一致、abstract の有無）で変わる bias は 1 つの net に有利に働く。pool が title 語に偏る問題と同じ類 [INFERENCE]。(c)「同一入力の揺れを先に測る」手順を与える source は無かった。

#### A9. vcrpy — cassette 設計の照合 — Prior implementation（FETCH、https://vcrpy.readthedocs.io/en/latest/configuration.html、as-of 2026-10-20）
- [FACT] 既定の match_on は method / scheme / host / port / path / query で、request body は既定では照合しない（body / raw_body は opt-in）。同じ URL と method は同一視される。読んだ page は record_mode='once' の例示以外の意味論、header の filter、httpx に触れていない。tessl mirror の snippet（二次）では custom matcher の登録と Cassette.find_requests_with_most_matches による miss の診断ができる。
- こちらとの違い: jrp の cassette は method + URL + body hash で照合し header を保存しない。body については vcrpy の既定より厳しく、POST の net（Tavily、JSON の検索 body）で 2 つの異なる query が同じ URL に行く場合に vcrpy の既定なら混同する。header 非保存は secret を持たない利点がある（vcrpy 側は filter_headers で対処、この page では未確認）。自前 cassette で良く、既製ツールが jrp に必要な物（JSON で diff 可能・hash key）を足す根拠は見つからなかった。
- 未検証: pytest-recording と respx（背景知識では respx は httpx の mock 用で record-to-disk を持たず、pytest-recording は vcrpy を包む plugin。引用しない）。replay 時の miss は offline gate では error にすべきで、vcrpy の record_mode none がそうする、と背景知識で思うが未検証。

#### A10. BrowseComp-Plus 以外の「live 検索の凍結」 — 該当なし
2025–2026 についてはこの検索では BrowseComp-Plus しか見つからなかった。ClueWeb22 などの凍結 web corpus は個別に検索していない。

#### A11. jrp への横断的な対応づけ（freeze-replay 角度。数値引用を除き全て [INFERENCE]）
1. pool 対 corpus: cassette は request 集合を記録するので、記録済み候補の pooling 型比較と凍結集合の並べ替え replay は支えるが、新しい query は支えない。ここが BrowseComp-Plus・TREC（文書を凍結して任意の retriever を走らせる）との大きな違い。
2. union を一度だけ判定し (content hash, question, judge version) で cache し、候補を同じ判定済み集合で比べる。自分が寄与していない item で採点した候補には judged coverage を報告する。
3. ペア差は対称差だけで足りる（集合 count の算術）。MTC が「A と B を分ける物だけ判定する」の最も近い先行実装だが、snippet 以上は読んでいない。
4. 判定の揺れ: 0.5 判定の繰り返し反転率と、p の 0.01 刻みでの広がりを先に測る。候補差を hard count（p >= 0.5）と soft count（p の和）の両方で、かつ繰り返し実行ごとに報告する。この手順は A7（複数の判定集合）からの類推で、見つけた source ではない。
5. 日ごとの分散: IR 評価は多数の topic で平均する。jrp の「topic」は line-day で、1 日の snapshot は line ごとに 1 つのペア標本。複数日が要るかは設計上の問いで、この角度の source では決まらない。
6. leave-one-candidate-out（A4）は pooled 比較を信じる前の安い自己検査。

### B. capture-recapture / 種の豊富さ推定（capture-recapture 角度）

#### B1. Chao2 の式 — Claim / State of practice（FULL、一次）
出典: Chao & Colwell 2017, SORT 41(1):3–54（eq 2b, 3a–3c）、https://gwern.net/doc/statistics/order/capture/2017-chao.pdf。T = sampling unit 数、Q_k = ちょうど k unit で検出された item の数、S_obs = 見えた distinct item 数。

```
S_Chao2 = S_obs + ((T-1)/T) * Q1^2 / (2*Q2)            if Q2 > 0
S_Chao2 = S_obs + ((T-1)/T) * Q1*(Q1-1) / 2            if Q2 = 0
A = (T-1)/T
var (Q1>0,Q2>0) = Q2 * [ 1/4*A^2*(Q1/Q2)^4 + A^2*(Q1/Q2)^3 + 1/2*A*(Q1/Q2)^2 ]
var (Q1>0,Q2=0) = 1/4*A^2*Q1*(2*Q1-1)^2 + 1/2*A*Q1*(Q1-1) - 1/4*A^2*Q1^4 / S_Chao2
CI95 = [ S_obs + (S_Chao2-S_obs)/R ,  S_obs + (S_Chao2-S_obs)*R ],
R = exp{ 1.96 * sqrt( log( 1 + var / (S_Chao2-S_obs)^2 ) ) }
Q1 = 0  ->  S_Chao2 = S_obs ("sampling complete"); variance of S_obs by analytic (Colwell 2013) or bootstrap.
```
- log-normal の CI は log(S_Chao2 − S_obs) を正規とみなすので、下限は常に S_obs 以上（Chao & Colwell 2017 p.12）。これは Chao 1987 の式 12（C = exp{1.96[log(1+σ²/(N̂−S)²)]^½}、log 変換は Burnham の私信による提案、FULL）。
- 下限の由来: Chao 1987 式 8 `N̂ = S + f1²/(2 f2)` は、heterogeneity model Mh の下の Jensen の不等式 E(f0) ≥ [E(f1)]²/[2E(f2)] と Poisson 極限近似から来る（t が大きく p が小さいことが要る）。Chao 1987 の分散（(m-1)/m の因子なし）は `f2[.25(f1/f2)^4 + (f1/f2)^3 + .5(f1/f2)^2]`（FULL、p.786）。「Chao2」の名は Colwell & Coddington 1994 による（Chao & Colwell 2017 §1）。
- 流通する 2 つの規約（Q2>0 で数値が違う）:
  (i) Chao & Colwell 2017 eq 2b と vegan::specpool（FULL、https://rdrr.io/cran/vegan/man/specpool.html）: Q2>0 では古典形 Q1²/(2Q2)、Q2=0 のときだけ Q1(Q1−1)/2、いずれも × (N−1)/N（vegan の既定は smallsample=TRUE）。
  (ii) Gotelli & Colwell 2011 Box 4.1（FULL、https://gwern.net/doc/statistics/order/capture/2011-gotelli.pdf）: 全データに使える「bias-corrected」形 `S_obs + ((m-1)/m) * q1(q1-1) / (2(q2+1))`、因子なしの古典形も併記。分散は q1,q2>0 のとき `q2[1/2(q1/q2)^2+(q1/q2)^3+1/4(q1/q2)^4]`（A 因子なし）。それ以外の場合と非対称 CI は Colwell 2009 EstimateS Appendix B に委ねる（未取得）。
  Bron の count（Q1=40, Q2=33）での例: 古典形 24.24、bias-corrected 22.94（1560/68）。いずれも (T−1)/T 因子の前の値。code にはどちらの規約かを名前で書く。
- こちらとの違い: T は net や request を定義上は意味しない（B3）。T と Q_k を定義すれば式はそのまま移せる（約 15 行）。
- 根拠の種別: 一次文献の式。

#### B2. arXiv 2404.01176 が実際にしていること — Claim of a paper（FULL、26 ページ、simulation 根拠）
Bron, van der Heijden, Feelders, Siebes, "Using Chao's Estimator as a Stopping Criterion for Technology-Assisted Review", arXiv 2404.01176 v1, 2024-04-01（cs.IR）、https://arxiv.org/abs/2404.01176。
- 対象: active learning の TAR（SR の abstract screening）でいつ止めるか。推定対象は候補集合中の関連文書数 |D+|。`N̂ = n + f̂0`、n = 見つかった distinct な関連数、f_k = ちょうど k 人の「reviewer」に見つかった文書数（§3.1.1）。
- unit = ensemble の member: C = 5 個の active-learning classifier（NB, LR, RF, LightGBM, random sampler）が各自の順位で文書を提案し、人手 label ごとに N×C の incidence matrix X（文書 × member）を作り直す。各 member は自分の labeled set を持ち、ある member i が最初に提案した文書は i に帰属し、後で member j が提案したら label を j に移す（Fig. 1）。
- 推定量: Chao (1987) の moment 推定量 eq. (1): `f̂0 = f1²/(2 f2)` if f2>0；`f1(f1-1)/(2(f2+1))` if f2=0（後者は Chao の後の論文 "[11]" 由来）。**(T−1)/T 因子なし、「Chao2」の名なし、Good–Turing や「incidence matrix」という語としての言及もなし。** 依頼 brief の「Chao2 / Good–Turing」は Chao & Colwell 2017 由来の言葉で、この論文のものではない。分散 eq. (2) と log-normal CI eq. (3)–(4) は Chao 1987 のもの（B1 と一致）。2 つ目の推定量は Rivest & Baillargeon の Poisson 回帰版で R の Rcapture で当てはめ（§3.3）、profile-likelihood CI。
- golden test に使える worked example（手計算で再確認済み: 40²/66 = 24.24; var = 33·(0.25·2.1587+1.7809+0.5·1.4692) = 100.82; R = 2.181; CI = 92 + 24.24/2.181, 92+24.24·2.181）: n=92, f1=40, f2=33 → N̂=116.24, var 100.82, 95% CI [103.11, 144.88]。Poisson 回帰版は 125.18、CI [108.88, 146.39]。真の N=120。
- 明示された前提（§3.2.2）: model Mh（捕獲確率は文書で変わり member では変わらない）、「ある文書を見つけた member 数はゼロ切断 Poisson の実現値」、「member は独立に探索し contagion は無い」、Chao の推定量は下限であり一般に良い N の推定量。
- 結果（§5.3、Tables 7–8、94 dataset × 30 seed = 手法あたり 2,820 run、有病率 1.5–2.8%）: 保守的規則（CI 上限に対する再現率が目標以上で停止）の 95% 目標で平均再現率 95.9 ± 5.0%、**目標達成は 70% の run**、再現率の 5 percentile は 0.87（Fig. 5）、100% 目標では 53% 達成。楽観的規則（点推定）は 95% 目標の達成が 10% の run のみで再現率 84 ± 11。すべての手法が関連文書数を過小推定する傾向があると述べる（§5.3.2）。Chao (1987) の基準は推定が序盤に大きく揺れるため |L|>100 label 後にだけ発火させる（§3.4）。
- 選別: 関連文書 10 件以上の dataset を残し、各 member は関連 1 + 非関連 1 の seed が要るので 5 件の関連 seed が必要（§3.5.4）。**この論文は「10 以上の sampling unit」とは書いておらず、unit は 5。**
- こちらとの違い: 彼らの 5 member は 1 つの固定・有限 corpus を探索し（各文書はどの member にも検出される機会があり、benchmark では真の N が既知）、jrp は開いた stream 上の 5 つの異質な net で真値が不明。彼らの member は同じ label で学習した同一 corpus の ranker（依存はあるが著者は論拠で退ける）。jrp の net は自分の accepted paper で seed される。
- 移せる部分: N×C の incidence matrix の作り方、f_k の数え方、式 (1)–(4) のそのまま、「点推定でなく推定と CI 上限を報告する」型、C=5 では 95% 目標が 70% でしか満たされなかったという実証的警告。
- code: 著者の library `python-allib`（PyPI META 2026-10-20: v0.5.3、2024-12-19 upload、LGPL-3.0+、Python >=3.8、依存は numba / numpy / pandas / h5py / tables / scikit-learn / scipy / lightgbm / gensim / instancelib 等）。GitHub page（snippet 水準）は `CHAO` を実験 option としてのみ挙げ、install 手順が要るとし、§3.3 では Poisson 回帰が R の Rcapture を使う。単体で使える Python の Chao2 ではない。

#### B3. sampling unit は何でなければならないか — Chao2 の前提（FULL、一次）
- Chao & Colwell 2017 §2.1（p.7）: T 個の sampling unit は無作為かつ独立に標本化され、各 item i は unit 間で一定の incidence 確率 π_i を持つ。unit は trap・quadrat・時間を区切った調査で、時間的研究では「同じ場所に独立な別時点で配備した T 個の unit」。閉じた assemblage で復元抽出（Gotelli & Colwell 2011 p.41。実在の群集で完全に閉じたものはほとんど無い、とも述べる）。
- Gotelli & Colwell 2011 §4.2.8: 標本は局所 assemblage から独立・無作為に引かれ、標本の順序は重要でないと仮定。
- 近似不偏の条件（Chao & Colwell 2017 §2.3, eq 5e, Good–Turing 導出）: 未検出 item と singleton の平均検出確率が同じ（φ0 ≈ φ1）なら Chao2 はほぼ不偏。そうでなければ下限（φ0 ≤ φ1 が「直観的」な順序）。beta-binomial / negative-binomial のクラスタ化の下でも有効（§2.2）。題名と abstract で Chao2 は "lower bound"。Chao 1987 p.787: f3, f4… が無視できない情報を持つなら下限としてのみ見なせる。
- こちらとの違い: unit = net は「π_i が unit 間で一定」に反する（net ごとの検出確率: M_t / M_th 型で未読）。unit = 日は、一次文の「時間反復」用法として明示的に許されるが、同じ item が別の日に再検出できることが要る（S2 / OpenAlex の seed 型 net は再浮上するが、日次 arXiv firehose は item を 1 回しか見せない）。unit = request（query）は、各 query が同じ検出法則からの無作為抽出であるときだけ反復になるが、question ごとの authored query はそうでない。どの unit にするかは lead の設計判断で、一次文が支持するのは「無作為・独立・同じ法則」だけ。seed 型の net は構造的に独立を破る（B6）。
- 移せる部分: φ0 ≈ φ1 は「at least」が何に依存するかの原理上検査可能な記述。式は Q_k の count だけを要する。

#### B4. unit 数はいくつ要るか — 書かれている閾値（FULL）
- Chao 1987 p.787: 一般に標本数は少なくとも 5 を推奨（simulation による）、t が大きく p が小さいことに依存。simulation（Tables 2–3、N=200/400、E(p)=0.05–0.1、100 試行）: t=10 で 8 母集団すべて点推定は真の N を下回った（N=400 で 355, 349, 362, 345、N=200 で 176, 152, 173, 190）。log 変換 95% CI の被覆率は 88, 81, 88, 83, 99, 74, 73, 89%（8 つ中 7 つが名目未満）。t=5 では被覆 79–99%（母集団 6 の t=7 は 79%）。捕獲確率が比較的大きい場合（Uniform(0,1)、Beta(2,2)）は、この方法は機能しない（p.790）。
- Gotelli & Colwell 2011: rarefaction 曲線は少なくとも 20 標本、できれば遥かに多く。121 標本の dataset で Chao2 は約 30 標本で安定（Fig 4.4）。ICE の分割は「10 標本以下」で infrequent とする（この 10 は class 境界で、最小 T ではない）。
- Bron 2024: C=5 unit（B2）。
- 「10 以上の sampling unit」を規則とする一次 source は見つからなかった。最も近い数は ≥5（Chao 1987）、≥20（Gotelli & Colwell の rarefaction）、10（ICE の class 境界、Bron の dataset あたり関連文書 ≥10）。brief の「≥10」は出典なしとして扱う。

#### B5. SR 検索での capture-recapture — State of practice（FULL / SNIPPET 混在）
- Spoor ら 1996, BMJ 313:342（Cochrane Colloquium abstract の page で FULL: https://abstracts.cochrane.org/1996-adelaide/using-capture-recapture-technique-systematic-literature-searches。BMJ 本体は 403）: 2 source（MEDLINE と 1 誌の 10 年分の手検索）で、両方 115、MEDLINE のみ 35、手検索のみ 8、両方が見逃した RCT は推定 2.4。手計算の確認: Lincoln–Petersen 150·123/115 = 160.4 対 観測 158 → 2.4。2 source で独立を仮定。
- Kastner ら 2009 J Clin Epidemiol（log-linear、複数 source）: abstract は未取得。引用側 snippet の事実: 外科系 CMR は見逃し 3（95% CI 0–6）、検索は既知論文の 93% を発見（https://core.ac.uk/works/100848577）。B 型肝炎 review は 3 source の log-linear で見逃し約 5（95% CI 4.2–6.2）、完全性 87.2%（https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3082794/）。critical-care review の database 検索母集団 28,839（95% CI 12,393–70,990）（https://experts.mcmaster.ca/scholarly-works/433385）。「Horizon Estimate」停止規則を骨粗鬆症 review で後ろ向きに検査: 68% 捕捉、約 592 件欠落（Kastner/Straus/Goldsmith AMIA 2007、https://experts.mcmaster.ca/scholarly-works/837966、SNIPPET）。
- Motschall ら Cochrane Colloquium Singapore 2009（SNIPPET: https://abstracts.cochrane.org/2009-singapore/number-needed-read-are-capture-recapture-techniques-feasible-searching-literature）: 6 database、Poisson log-linear で主効果 model は欠落 56、全 2 次交互作用 model は 1,439（過適合でほぼ非現実的）、BIC 選択は 82。model の選び方で推定が約 25 倍動く。database 間の重複同定が実務上の問題。
- 2023–2026: 新しい SR 検索の capture-recapture 研究は 2 回の検索で見つからず、最新は Bron 2024（TAR 停止、B2）。実務の状態は「疎・小 n・model 依存」。
- こちらとの違い: SR は 2–6 個の名のある database を source とし、採用 study の一覧を真値にする。jrp は 5–8 個の net、関連 label は classifier（on_topic >= 0.5）、真値は開いている。移せる教訓は、推定が依存 / model 形に敏感なことと、著者が小さな絶対数と広い CI を報告すること。

#### B6. source 間の依存 — 分かっていること（SNIPPET のみ。PMC / BMJ は閲覧不可）
- 正の依存（A で見つかる item は B でも見つかりやすい）は capture-recapture を過小推定にする（Hook & Regal 1995 を引く 2017 年頃の arXiv 論文: https://arxiv.org/pdf/1703.03022 の snippet。引用年は D1 と食い違う、Contradictions 11）。Tsay & Chao 2001, J Appl Stat 28(1):25–36: overlap が低いと N は精密には推定できず、正（負）に依存する list では下（上）限のみ、sample-coverage 法（https://ideas.repec.org/a/taf/japsta/v28y2001i1p25-36.html の snippet、全文未読）。
- "Recapture or Precapture? Fallibility of Standard Capture-Recapture Methods in the Presence of Referrals Between Sources"（PMC4036210）: source 間の直接の紹介があると標準 log-linear model は重い bias を持ちうる（snippet のみ。jrp の「accepted paper で seed される net」に最も近い類似だが未読）。
- Wesson ら 2022 の simulation（PMC9826711、snippet）: log-linear の model 選択・Bayesian model averaging・SparseMSE・Sample Coverage を比較し、model 選択を誤ると非現実的な推定になりうる。
- Chao 自身の枠組み（FULL、B3）: Chao2 は heterogeneity の下の下限。unit の独立は式の仮定であり、下限の議論が補修するものではない。依存する net について、読めた source は「依存が正で heterogeneity 由来のときだけ『少なくとも』と読む」以上の補修を与えない。
- 移せる部分: 結果を「at least」と言えるのは正の依存 / heterogeneity のときだけで、負の依存では符号が逆（Tsay & Chao 2001、snippet）。jrp の seed 型 net（S2 recommendations、accepted paper の OpenAlex forward citation）は、accepted paper 近傍の item について keyword / arXiv 系 net と正の依存を持つ。「下限」という方向と矛盾しないが、大きさは不明。

#### B7. pooling に基づく relative recall と source ごとの unique 寄与 — State of practice（Sampson は FULL、Bramer は SNIPPET）
- Sampson, Zhang, Morrison ら 2006, BMC Med Res Methodol 6:33、https://pmc.ncbi.nlm.nih.gov/articles/PMC1557524（fetch で FULL）: relative recall は、ある system が、総（pool した）関連文書のうち取った割合。gold standard は 105 件の Cochrane review の採用 RCT のうち MEDLINE で見つかったものを OR で集めた物で、Highly Sensitive Search Strategy の 3 変種の relative recall は 0.91〜0.98（網羅的な strategy ほど高い）。自らの限界として、relative recall は個々の検索の和までしか良くない、ある system の relative recall が高くても実際の recall はほぼ 0 でありうる、MEDLINE にない study を分母に入れると recall は 0.66〜0.70 に落ちる。review の 87% が CENTRAL を使うので、包括的な register が分母を膨らませる caveat もある。
- Bramer ら 2017, Syst Rev 6:245、https://pmc.ncbi.nlm.nih.gov/articles/PMC5718002（SNIPPET）: 58 SR、database 検索で見つかった採用参考文献 1,746 件と他の方法で見つかった 84 件、16%（291 件）が単一 database でのみ発見、Embase の unique は 132、最良の 4 database 組合せ（Embase, MEDLINE, Web of Science Core Collection, Google Scholar）の recall は 98.3% で review の 72% で 100%。recall の分母の定義と、database 以外の方法でだけ見つかった参考文献の扱いは未確認（page 閲覧不可）。
- どちらも、seed 型の source（citation chasing）を別扱いしていない（読めた範囲）。Sampson の caveat は net の和集合の pooling にそのまま当たり、和集合に対する recall は、全 net が見逃す物については何も言わない。それが Chao2 が下限を置こうとする穴。f̂0 が見逃し数の下限なら、絶対的な pooled recall ≤ S_obs / (S_obs + f̂0)（自前の導出で source には無い）。Bron 2024 も N̂ の CI 上限を同じ形で使う（N̂_sup に対する再現率）。
- net ごとの relative recall・unique 寄与の区間: この角度の source に方法は無く、兄弟角度か標準の binomial / bootstrap（日で cluster）が当たる。出典なしの自前の提案。

#### B8. Python 実装 — Library / tool choice（META / FULL の docs、as-of 2026-10-20）
- scikit-bio 0.7.4: 2026-09-21 upload（PyPI META https://pypi.org/pypi/scikit-bio/0.7.4/json）、BSD-3-Clause、Python >=3.10、依存は requests / decorator / numpy>=2.0 / pandas>=1.5 / scipy>=1.9 / h5py>=3.6 / biom-format>=2.1.16 / statsmodels>=0.14 / patsy>=0.5 / array-api-compat>=1.3（重い）。docs の dev page https://scikit.bio/docs/dev/generated/skbio.diversity.alpha.html は alpha 関数 38 個（`ace`, `chao1`, `chao1_ci`, `singles`, `doubles`, `osd`, `goods_coverage`, `robbins`, `esty_ci`, `lladser_pe/ci`, `michaelis_menten_fit`, `sobs` ほか）を挙げるが、**chao2・ICE・incidence / sample-based richness は無い**。`chao1` は abundance vector を取り、(m−1)/m 因子を持つかは未読。
- iNEXT は R のみ（CRAN iNEXT 3.0.2、SNIPPET）。他の R の incidence Chao2: vegan::specpool（B1 で検証済み）、spacc `chao2()`、wiqid `richChao2`、fossil、SpadeR（snippet）。PyPI `inext` は 404（META）。PyPI 検索 page は取得不能。Python の Chao2 / iNEXT / ICE の package や GitHub 関数は web 検索 3 回で見つからなかった。索引外の package の存在は排除できない。python-allib は B2（LGPL、重い依存、Chao は R 経由）。
- 結論: 手で書く（S_obs, Q1, Q2, T から推定・分散・CI、約 15 行、numpy のみ）。golden test は一次文から取れる: Bron eq. (1)–(4) の例（B2: 116.24 / 100.82 / [103.11, 144.88]、(T−1)/T なし）、Spoor の Lincoln–Petersen 2.4（2 source の健全性確認）、R が手元にあれば vegan::specpool の規約（B1）との突き合わせ。失効条件: 保守されている PyPI package に `chao2` が現れたらこの勧めは失効する（PyPI と scikit-bio の changelog を確認）。2026-10-20 に freshness を確認。

### C. 個々の query の測定と query 集合の選択（query-performance 角度）

#### C1. relative recall（benchmark）— label が軽い標準的な検索式の採点 — State of practice + Claim of a paper（FULL、14 ページ中 pp.1–8）
- 何か: Lagisz, Yang, Young, Nakagawa, "A practical guide to evaluating sensitivity of literature search strings for systematic reviews using relative recall", Research Synthesis Methods 16:1-14、2025-03-07 online。https://doi.org/10.1017/rsm.2024.6（PDF: https://www.cambridge.org/core/services/aop-cambridge-core/content/view/BC6A8387DAB7539D7F96EBD5965ECC32/S1759287924000061a.pdf/a-practical-guide-to-evaluating-sensitivity-of-literature-search-strings-for-systematic-reviews-using-relative-recall.pdf）。pp.9–14（5 database の worked tutorial）は未読。
- 内容: 検索式の sensitivity とは、評価する式と、benchmark 出版物だけを捕らえる式との retrieval overlap（abstract）。Fig.1: 検索 sensitivity は、検索式で見つかる、index された benchmark study の割合。precision は関連で見つけた数 / 見つけた全数で、検索結果の無作為標本を screening して推定できる（例: 100 件中 5 件関連なら 0.05）。真の sensitivity には未知の関連 study 総数が要るので、実務は既知の部分集合（benchmark / gold / validation / seed set）を使う。
- 前提: benchmark は対象の database 検索より前に集め、多様な source（先行 review、個人 collection、類似度・citation 追跡による検索、専門家の査読）から来なければならず、代表的でない benchmark 集合は数値を偏らせる。database に無い benchmark study はその database の分母から除く。その不在自体が source 選択の情報。
- State of practice（彼らの調査、2022 標本、SR 100 本 + Cochrane protocol 100 本）: 一般 SR の 13/100 が検索式の開発を記述し、変種の検証を記録したのは 1 本のみ。Cochrane protocol は 4/100 が開発を記述し、変種の記録は 0。SR 実務でも式の評価はほとんど報告されない。
- 根拠の種別: tutorial と小規模な文献調査。relative recall が実際の recall を予測するかの benchmark は無い。
- こちらとの違い: 人が整えた benchmark は無く、classifier（on_topic >= 0.5）が item に label を付ける。query 不要の net（RSS、S2 recs、OpenAlex citations）は「他 source 由来の benchmark」の役を担いうるが、下記の caveat がある。
- 移せる部分: (1) adapter ごとの分母: adapter は、その adapter が index する benchmark item だけで採点する（arXiv に限った OpenAlex を GitHub だけの item のせいにしない）。(2) precision は標本抽出で、jrp では返った item のうち on_topic の割合。(3) benchmark は試験する query 集合と独立な経路から来なければならない。我々の caveat（推論で source に無い）: BM25 順位付けの RSS overflow や S2 recs で見つかる item は、authored query の元と同じ question 文に条件づけられるので、重なりが循環しうる。これは adversarial 角度（D）の担当。

#### C2. 客観的（Hausner）アプローチ: 開発集合で語を導き、保留集合で検証 — Claim of a paper（SNIPPET のみ）
- 何か: Hausner ら, "Development of search strategies for systematic reviews: validation showed the noninferiority of the objective approach", J Clin Epidemiol 2015（PubMed 25464826）。先行の BMC Med Res Methodol 2012 と Cochrane colloquium abstract。見つけた経路: https://git.lsit.ucsb.edu/publicdata/nih-gov/raw/branch/main/pubmed.ncbi.nlm.nih.gov/25464826/index.html と https://abstracts.cochrane.org/2015-vienna/objectively-derived-approach-enables-development-high-quality-search-strategies。検索 engine の abstract 要約のみ。
- 内容: 公開済み Cochrane review の参考文献を開発集合（text 分析で語を選ぶ）と独立な検証集合に分け、13 検索で平均 sensitivity 96%。概念的（同義語）アプローチに非劣性（P < 0.002）。元の MEDLINE 戦略は 86%（主に 1 review に牽引）。方法が「透明」になると主張。
- 根拠の種別: 公開 13 review での後ろ向き検証。
- こちらとの違い: そちらは label 付き参照集合があり、固定された有限 topic での recall が設計を決める。
- 移せる部分: 開発 / 検証の分割。凍結 item で点数を見て query 集合を選ぶこと自体が、その item への過適合になる。凍結 window を時間か item で分け、選んだ集合を選択に使わなかった側で採点する。これは設計からの推論で、Hausner が jrp の状況を論じているわけではない。

#### C3. LLM が作る Boolean query の採点（Wang 2023/2025、Staudinger 2024）— いずれも label 付き collection に対して
- (a) Wang, Scells, Koopman, Zuccon, "Reassessing Large Language Model Boolean Query Generation for Systematic Reviews", arXiv 2505.07155（v2、2025）、https://arxiv.org/html/2505.07155v2（FETCH-SUMMARY、逐語でない）。query を PubMed Entrez に流し、返った PMID を abstract 水準の関連判定と突き合わせて集合ベースの precision / recall / F-measure（表には F3 もあるが本文に定義は無い）。collection は CLEF TAR（重複除去後 72 topic）と Seed Collection（35）。1 から 1,000,000 件を返す query が「valid」で、invalid は最大 20 回再生成し、それでも駄目なら最後のものを残す。各 topic の元の検索日で実行。有意性は「Bonferroni 補正つきの paired t 検定」p<.05、最良 prompt / 最良 model 変種 / 手作業 baseline に対して。要約によれば式・NNR・費用の報告は無い。所見: Staudinger 対 Wang の定式化の差には query の validation が最も効き、guided 定式化には seed 選択が最も効き、出力 format に有意差なし、平均 recall は手作業 query より約 15% 低い（当初報告された差は 35% と 60%）、LLM の refinement は precision を上げ recall を下げる、全 seed の query を合わせると recall は手作業に近づくが precision を失う。
- (b) Staudinger ら, "A Reproducibility and Generalizability Study of Large Language Models for Query Generation", SIGIR-AP 2024, arXiv 2411.14914（2024-11）、https://arxiv.org/pdf/2411.14914（SNIPPET）。再現では Wang 2023 より recall がずっと低く、open-source model（Mistral, Zephyr）も試験。
- (c) 2026 の追随（SNIPPET のみ）: AutoBool（retrieval feedback を報酬にした RL 訓練 LLM、EACL 2026、arXiv 2602.00005、https://arxiv.org/html/2602.00005、一覧に日付の不整合の注記あり）。SR4CS benchmark（近似した専門家 Boolean query、arXiv 2604.16330、https://www.emergentmind.com/papers/2604.16330）。どちらも label 付き集合（CLEF TAR、Seed Collection、新 dataset）に依る。
- 根拠の種別: 過去 collection 上の benchmark 実験。評価の型（固定した label 付き collection 上の集合ベース P/R/F、topic をまたぐ paired 検定）はこの subfield の実務。
- こちらとの違い: 静的で有限、label が完全で、query は結果集合の全体を返し、解析の単位は topic。jrp は classifier 以外の label が無く、日次の top-N で、結果は drift し、単位は query / line / day。
- 移せる部分: (1) 再現性の隔たりは protocol の細部への警告（validation の gating、seed 選択、temperature / seed の記録。35–60% の隔たりが 15% になった主因は文書化されていない手順）。offline の採点器では protocol を凍結して記録する（classifier の version・閾値・重複除去規則・どの send を数えるか）。(2) 多重性: Wang は prompt / model の比較に Bonferroni を使った。K 個の候補 query 集合から最良を選ぶ場合に同じ注意が要る。(3) validity gate（1〜1M 件）は「>0 件返る」のような採点前の床に相当。

#### C4. source の unique 寄与（Bramer 2017）— leave-one-out の count
- 何か: Bramer, Rethlefsen, Kleijnen, Franco, "Optimal database combinations for literature searches in systematic reviews: a prospective exploratory study", Systematic Reviews 6:245（2017）、https://doi.org/10.1186/s13643-017-0644-y。SNIPPET のみ（Springer の page が cookie handshake に飛び fetch が追えなかった）。数値は要約由来で本文では未検証。
- 内容（要約による）: 58 の公開 SR。参照集合は最終 review の採用参考文献。採用参考文献の 16%（291 件）は 1 つの database でしか見つからず、unique が最も多いのは Embase（132 件）。最低限 Embase・MEDLINE・Web of Science・Google Scholar を勧める。
- 根拠の種別: 58 review の前向き研究。参照集合は人が screening した採用。
- こちらとの違い: 単位は query でなく database。参照集合は人が screening。静的。
- 移せる部分: 「unique」とは、集合の中のちょうど 1 member に見つかる item。member でなく集合の性質なので、冗長な良い query 2 本はどちらも unique 0 に見える。つまり query ごとの unique-yield 表は冗長な対の価値を過小評価し、1 本ずつ抜く解析は両方を抜く効果を教えない（推論）。search-term 単位の unique-yield を適用する SR 実務の source は見つからなかった（2 回検索して無し）。

#### C5. monitoring / living review の実務: 更新手法の workload と recall。query 退役規則は見つからず — State of practice（SNIPPET）
- (a) "Surveillance search techniques identified the need to update systematic reviews", J Clin Epidemiol 2008、https://pubmed.ncbi.nlm.nih.gov/18586179/: 77 SR に 5 つの surveillance 手法。単一で確実に新しい関連証拠を見つけた手法は無く、最良の組合せ（PubMed related-article + 主題検索）は 68 件で新しい関連 record を全部見つけ、review あたりの screening 負荷の中央値は新 record 71 件。
- (b) LOCATE: 3 つの更新手法（全自動検索、PubMed similar articles、Scopus citing references）を参照標準に対して前向きに評価（https://www.springermedicine.com/locate-a-prospective-evaluation-of-the-value-of-leveraging-ongoi/23012164）。source ごとの数値は見えず。
- (c) Akl ら "The life and death of living systematic reviews: a methodological survey"（https://scholarworks.aub.edu.lb/items/171d1efd-46d1-49c3-a46d-06fae58b87be 経由）: 76 本の living review の多くは予定を守り、一部は遅れた。query の退役でなく更新の予定の話。
- 根拠の種別: 後ろ向き・前向きの手法比較、調査。
- 欠けているもの: 「n 回送って新規ゼロなら query を退役する」型の規則を置く source は、これらの結果に無い。そこでの測定語彙は参照標準に対する recall と、更新あたりの screening 負荷（費用軸 = screening する record 数）。
- こちらとの違い: SR の surveillance は更新窓内の新 record を参照集合に対して数えるが、jrp は成長する store に対する新規性を数えるので、「0 件」は 3 つの原因（query pool の枯渇、その日はたまたま静か、別の net が既に保持）を混ぜる。count だけでは 0 がどれかを判別できない（推論）。
- 移せる部分: 費用の類似物として「更新あたりの screening 負荷」を使う。jrp では、新規 on-topic item あたりの classifier call 数と request 数。

#### C6. QPP: label なしの予測はあるが、label が軽い版は既にある classifier — Claim of a paper（SNIPPET）
- (a) Meng ら, "Query Performance Prediction using Relevance Judgments Generated by Large Language Models"（QPP-GenRE）, arXiv 2404.01012（v3、2025-05-26）、ACM TOIS 2025、https://arxiv.org/pdf/2404.01012。順位付き list の各 item を LLM に判定させ、その擬似 label から query ごとの IR metric を計算して予測（recall 系は近似）。人手 label で open LLM を fine-tune（open model の zero/few-shot は不調）。TREC DL 2019–2022。
- (b) ACM TOIS の QPP 特集 2026 の巻頭言（SNIPPET）は、QPP が LLM 系・表現系の手法、query 変種、比較評価へ移りつつあるとする（https://www.citedrive.com/en/discovery/introduction-to-the-special-issue-on-query-performance-prediction/）。
- (c) QPP++ 2025 workshop と "Can LLM Rerankers Predict Their Own Ranking Performance?"（alphaxiv 2606.03535、一覧に不自然さの注記）は reranker 内部の話で、jrp に reranker が無いので移せない（SNIPPET のみ）。
- 根拠の種別: 人手 label で訓練・評価する TREC DL の passage ranking の benchmark。
- こちらとの違い: QPP は我々が走らせられる / 中を見られる ranker の順位 list を前提にする。jrp の adapter は score なしのブラックボックスな web / API 検索。QPP の予測器は予測と真の query ごとの効果の相関で検証され、label が要る（背景知識で、今回は未 fetch）。
- 移せる部分: 構造だけ。「各 query の top-k を LLM で判定し、query ごとの点に集計する」は、jrp の on_topic classifier が返却 item に対して既にしていることで、QPP の段を足しても classifier から precision@k を読む以上の物は増えない。古典的な pre / post-retrieval 予測器（IDF・score の分散）は取得しておらず、76 query で効くとは主張しない。(c) への答えは、見つけた範囲では、既にログされている実現 yield を超える安価で label なしの物は無い。

#### C7. 固定予算での選択: 「request あたりの新規 item」の貪欲法が確立した形式 — Claim of a paper（SNIPPET）
- 何か: Ntoulas, Zerfos, Cho, "Downloading textual hidden web content through keyword queries", JCDL 2005, DOI 10.1145/1065385.1065407。Crossref の記録 https://api.crossref.org/works/10.1145%2F1065385.1065407 と二次的説明（US patent https://patents.google.com/patent/US7685112、Liakos ら WWW 2016 https://db.cs.pitt.edu/assets/pdf/2016.www.LiakosNLD16.pdf）経由。本文は接続拒否で NONE。
- 内容（二次要約による）: 既にダウンロードした page から推定した効率（query 費用あたりの期待新規 page）で次の keyword query を選び、隠れた page の大半が見つかるまで繰り返す。後続研究は query ごとの課金を動機として挙げる。
- 根拠の種別: crawling 実験、2005 年。
- こちらとの違い: 有限 database の被覆が目的。jrp は動く corpus 上の日次 top-N で、目的は被覆でなく on-topic。
- 移せる部分: (1) 目的関数「request あたりの新規 on-topic item」は標準。(2) query q を外す限界価値 = q だけが返す item − 空いた枠が他で生む yield。後者は送ったことのない代替 query の yield を要し、凍結結果は供給できない。offline の採点は「外すだけ」の集合を順位付けられるが、「外して置き換える」集合は、置き換え query が少なくとも 1 回送られていない限り部分的にしか順位付けられない（推論）。予算付き被覆の submodular / (1−1/e) の貪欲保証は教科書的背景知識で、今回は取得せず未検証。

#### C8. 同じ item 上の 2 system の差の区間: ペアで、単位ごとに、小 n では bootstrap が anti-conservative — Claim of a paper（SIGIR'09 は FULL、2 ページを画像で読んだ）
- 何か: Smucker, Allan, Carterette, "Agreement Among Statistical Significance Tests for Information Retrieval Evaluation at Varying Sample Sizes", SIGIR 2009。https://ciir-publications.cs.umass.edu/pub/web/getpdf.php?id=885（および https://ir.webis.de/anthology/2009.sigirconf_conference-2009.82）。補完: Smucker, Allan, Carterette, CIKM 2007（SNIPPET、https://ciir-publications.cs.umass.edu/getpdf.php?id=744）は、paired t・Wilcoxon・sign・bootstrap・randomization を TREC run で比べ、randomization・bootstrap・t は一致し、Wilcoxon と sign はそれらと不一致。
- 内容: TREC 3, 5–8 の ad-hoc run 18,820 ペア。平均 AP の差の両側 p 値を randomization・shifted bootstrap・paired t で出し、topic を非復元で 10/20/30/40/50 に subsample、10 万回 resample。Table 1 の検定間 RMSE は topic が減ると増える（p>=0.0001 のペアで rand 対 t は 50 topic で 0.007、10 topic で 0.037）。bootstrap は t 検定より p 値が系統的に小さい側へ偏り、topic が減るほどその偏りが増す。randomization 検定を推奨し、統計量が平均なら topic が少なくても t 検定が妥当。
- 根拠の種別: 実際の TREC run 上の simulation（共有 topic 上の system ペア = ペア設計）。
- こちらとの違い: 単位は topic で topic ごとの点があり、10〜50 単位、独立な topic。jrp は候補集合が数本の query で違う（76 本から 1 本外す）、request ごとの結果は日ごとの新規 on-topic 件数、日同士は相関しうる（週の効果、突発的な topic）。jrp の日が交換可能な単位として振る舞うかは未検証。
- 移せる部分: (1) 同じ凍結単位で 2 集合をペアにして、単位ごとの差を検定する。(2) 単位が少ないときは randomization（符号反転）検定か平均差への t を使い、素の bootstrap の p 値は楽観的とみなす。この結果は shifted bootstrap の p 値についてで、n<=30 の percentile-bootstrap CI の被覆率に関する source は見つからなかった（未検証）。(3) 2 集合が 76 本中 75 本を共有するとき、query にわたる bootstrap は resample する物がほぼ無い。識別可能な変動は日（または line）にわたる（推論）。(4) item 水準の McNemar 型: A だけが返す on-topic item 数と B だけが返す数が不一致ペアを作り、正確二項検定ができる。1 つの paper が複数 query に当たる、日次バッチで来る、という場合は item が独立でない（推論。この使い方の source は未取得）。
- 多重性: Wang 2025（C3）は比較をまたいで Bonferroni を使った。K 個の候補集合から勝者を選ぶと点が膨らむ（winner's curse。Hausner の分割が C2）。

#### C9. 組み立てた形（query-performance 角度の推論、source の推奨ではない）
1. 点 = request あたりの新規 on-topic item（classifier >= 0.5）、adapter 別、加えて precision = 返却 item のうち on_topic の割合。費用軸は request 数（固定）と新規 on-topic item あたりの classifier call。
2. query ごとの leave-one-out unique yield と、unique の count が集合依存なので drop-pair の検査（C4）。
3. 集合と独立な net が得た on-topic item に対する relative recall、adapter が index する item に限る（C1）。循環のリスクは兄弟角度（D）へ。
4. 凍結 window の一部で選び、後の保留部分で報告する（C2）。
5. 区間: ペアの日（または週 block）単位の差、randomization / 符号反転検定または平均差への t と CI、副次的に不一致 item の count（C8）。
6. 凍結 item が順位付けできる集合を明言する。外すだけの集合は可、置き換えた集合は置き換えを送った場合だけ（C7）。

### D. 敵対的検討: 手法が何故ここで失敗・誤導するか（adversarial 角度）

読んだ範囲の凡例は冒頭と同じ（FULL / ABS / SNIP）。[SoP] = State of practice、[CLAIM] = Claim of a paper / post。

#### D-a. Chao2 / capture-recapture の失敗様式

**D1. 正の依存 → 過小推定 [SoP] — FULL（pp.1–2、Intro のみ）。** Chatterjee & Bhuyan, arXiv 1703.03022 v5（2019-01-17）、https://arxiv.org/pdf/1703.03022。対象は 2 list の Lincoln-Petersen（= model Mt）推定量。Mt（= LP）は 2 list 間の正の依存でしばしば失敗し、N の過小推定につながる（Hook & Regal 1982; Chao ら 2001 を引用）。負の依存は過大推定（同じ page）。根拠の種別は先行理論・応用を引く review の記述で、論文自身の貢献は 2 list の依存 model。こちらとの違い: Chao2 は incidence ベースの multi-unit 下限（Mh 系）であって LP ではない。「正の依存は未見の推定を縮める」という方向は定性的には移るが、Chao2 での大きさはここに無い。2 list では依存はデータだけからは識別できない（一般知識で、読んだ page には無い）。含意（注意）: 正の依存は jrp で構造的。S2 recommendation net と OpenAlex citation net は他の net で既に accepted された paper で seed されるので、firehose で accepted になった paper がその近傍を seed 型 net に見つかりやすくする seed になる（trap-happy / 行動反応）。Chao2 の出力は「少なくとも」と読み、Chao2 の式が示す値より低い可能性が高い。R2 参照。

**D2. Chao 推定量は heterogeneity の下でのみ下限で、分散が大きく、小標本版がある [SoP] — SNIP。** Böhning ら, Biometrics 2013（共変量情報への Chao 推定量の一般化）: 観測されない heterogeneity の下で開発され、その場合は下限（https://repository.li.mahidol.ac.th/handle/123456789/30943）。Niwitpong ら, Metrika 2013: Chao 推定量は MLE に比べ分散が比較的大きい（https://research-portal.uu.nl/en/publications/capture-recapture-estimation-based-upon-the-geometric-distributio/）。Southampton の thesis の snippet: 小標本用の bias 補正版がある（https://eprints.soton.ac.uk/361660）。こちらとの違い: 下限の保証は heterogeneity を所与とした独立に条件づく。依存（D1）は前提を壊すので、ここでは「下限」は定理でなく model への主張。unit が少ないと Q1/Q2（singleton / doubleton）の count が小さく、推定が高分散になる（「unit が少ないと不安定」は一般知識で、snippet は小標本の bias 補正があると言うだけ）。含意（注意 + 防護）: unit にわたる bootstrap 区間と、それに入る Q1/Q2 の count の両方を報告し、Q2 が 0 のとき、または Q1+Q2 が床を下回るときは数を出さない（床の値は結果を見る前に決める設計判断）。

**D3. 文献検索の capture-recapture では、仮定する依存構造で答えが振れる [SoP] — SNIP。** 検索結果の要約経由（元 page は Cochrane Colloquium abstract）: https://abstracts.cochrane.org/2009-singapore/number-needed-read-are-capture-recapture-techniques-feasible-searching-literature。同じ結果集合に Kastner らの停止規則の論文が出た（https://pmc.ncbi.nlm.nih.gov/articles/PMC2655834、開いていない）。報告: Poisson の主効果 model で欠落 56 件（95% CI 36–86）、全 2 次交互作用で 1439（410–5045）で過適合による「ほぼ非現実的」、交互作用 1 つの model が妥当だった。著者らは、database 間の重複を自動で同定できないことも実現可能性への疑問として挙げた。こちらとの違い: Chao2 でなく log-linear、数個の database、2009 年。教訓は同じで、source が約 6 以下だと依存構造は推定でなく選択になり、その選択で推定が約 25 倍動いた。jrp の重複除去は paper ID でできる（安い）ので、重複同定の心配はほぼ当たらない。含意（注意）: seed 型の net（S2、OpenAlex-citations）を含めた場合と除いた場合の Chao2 を感度の範囲として出し、1 つの数にしない。

#### D-b. offline replay / pooling / 反実仮想の落とし穴

**D4. pool bias: pool に寄与しなかった system は過小評価される [SoP] — SNIP。** Lipani ら "Fixed-Cost Pooling Strategies"（https://discovery-pp.ucl.ac.uk/10083262/13/Lipani_Fixed-Cost%20Pooling%20Strategies_AAM.pdf）、Buckley, Dimmick, Soboroff, Voorhees "Bias and the Limits of Pooling for Large Collections"（一定サイズの pool は大きな collection では被覆が縮み、AQUAINT の判定は topic title の語を含む文書に偏った、検索要約経由）、SIGIR 2015 の open test collection の再利用性研究（非 pool の system は過小評価、https://www.e.humanities.uva.nl/publications/2015/hash_on15.pdf、要約経由）。根拠の種別: TREC 型 collection での実証。こちらとの違い: 全候補の全 fetch item を classifier が判定する（未判定の穴が無い）なら、precision 型の count での古典的 pool bias は消える。残るのは**分母としての pool** で、構成 config の和集合に対して計算した「recall」や Chao2 は、その和集合を作った net、つまり現行 config に偏る。Buckley の発見（topic 語を含む文書が pool に過剰）は D7 に似る。含意（防護）: config の比較は新規 on-topic の絶対 count（N_ot）と区間で行い、pool に対する recall は副次的にのみ示し、どの config が pool を作ったかを書く。

**D5. 決定的な logging policy では、順位 / cap policy の OPE が失敗する [CLAIM] — ABS のみ。** Tanaka ら, ICLR 2026, arXiv 2603.21485, https://arxiv.org/abs/2603.21485。abstract: ranking 単位・position 単位の IPS はデータ収集 policy が十分に確率的であることを要し、logging policy が完全に決定的だと重い bias に苦しむ。彼らは click の乱雑さを使う click ベースの IPS / DR を提案。ほかに（SNIP）Yata, AAAI、contextual bandit での support 不足の logging policy。こちらとの違い: jrp の現行 logging policy は決定的（BM25 順位 → 300 での hard cut）で、cut の下の paper は propensity が 0 になり、何も判定されない。support は構造的に不足。Tanaka の処方は click を使うが jrp に click は無い（oracle は classifier）ので、その推定量は移らない。移るのは前提で、決定的な cut は、見せなかった item について off-policy 評価できない。含意（別の方法）: 納品物 (i) に対し、計画の「過去の overflow で埋める」により、未判定の overflow を事後に判定すれば、その 1 つの policy の support 問題は classifier 費用で消える。今後の cap には、cut の下から毎日少数をランダムに足す（包含確率が既知）と、tail の on-topic 率が design ベースで推定でき、正確な二項区間を持ち、独立性の仮定が要らず、Chao2 より「cut は何を落とすか」に直接答える。「ランダム slice を足す」ことは D5 の前提からの推論（REASONING）で、D5 が試した物ではない。

#### D-c. oracle としての classifier

**D6. LLM 判定者は LLM 系と非 LLM 系の system の順位を反転させる [CLAIM] — FULL fetch（下の数値は fetch tool の HTML 要約から、逐行の再読ではない）。** Balog, Metzler, Qin ら 2025（著者は検索要約による。題名は未取得）, arXiv 2503.19092 v2, https://arxiv.org/html/2503.19092v2。設定: TREC DL 2019/2020（43/54 query）、BM25 の top-100 を rerank、NDCG@10、Gemini 判定者 4 種（v1 Nano は kappa≈0 で使えず、v1.5 Flash/Pro）、4 段階、T=0。人手 label から作った oracle ranker。結果: 人手 NDCG@10 は Perfect 0.892 > RankT5 0.731、v1.5 Pro の判定では Perfect 0.864 < RankT5 0.916。Gemini-Flash reranker は人手 0.747 に対し判定 0.947。著者は、bias が相対順位を完全に反転させるのに十分と述べる。二値 kappa ≈ 0.36–0.46、段階 kappa ≈ 0.19–0.27。全 system の Kendall tau は 0.077/0.143（v1.5 Pro）だが、oracle のみの system では 0.600/0.867 で、system の選び方が見かけの一致を膨らませる。判定者は有意差を見逃し、人手に無い差を報告もする。LLM が書いた text への bias は見つからなかった（予備的と明記）。自ら述べる限界: 2 collection、1 つの model family、「例示的」。指針: 全 system に同じ judge config、version / prompt を報告、複数の judge、人手の標本で検証、judge は置換でない。こちらとの違い: passage の query への関連 対 paper の question への on-topic 性、Gemini 対 TypeSafe Jev、system 対 system の試験。移る前提: 判定者は自分の好みに似た出力を好みうる。集計の一致度（tau）は、近い system 間の失敗を隠しうる。これはまさに似た 2 config を比べる状況。含意（防護）: (1) 循環が効く唯一の場所を確認する。S2 / OpenAlex の net は**この同じ classifier が accept した** paper で seed されるので、classifier 自身の好みの近くを取る。seed 型 net に寄る候補は、人の blind 読みなら認めない oracle 上の利点を得る。(2) 著者が各 config の**限界的な** item（その config だけが見つけたもの）の小標本を blind で読む。repo は prose bench で著者の blind 読みを正解として既に扱っており、同じ規律。

**D7. 判定者は query 語を含む passage を、無関係でも関連と判定する [CLAIM] — SNIP（検索要約のみ。PDF は開いていない）。** Alaofi, Thomas, Scholer, Sanderson, SIGIR-AP 2024, arXiv 2501.17969, https://arxiv.org/pdf/2501.17969。報告: ランダムな無関係 passage に query 語を注入すると、多くの LLM 判定者が関連と判定する。全体の一致 metric はこれを隠す。それらの label で訓練する ranker にリスク。2026 の追随（https://arxiv.org/html/2602.17170v2 "When LLM Judges Inflate Scores"、https://arxiv.org/pdf/2607.10080 多言語・keyword 敵対注入）も SNIP。こちらとの違い: Jev が question の keyword を見るか、どれだけ強く重みづけるかは不明。jrp の authored-keyword query と BM25 順位付き overflow は、どちらも question / query との語の重なりで選ぶので、最も露出する候補。含意（防護）: keyword query や BM25 順位付きの fill で config が N_ot に勝つとき、その増分を語の重なり terciles（title / abstract の query 語数）と Jev score 帯で層別する。高重なり + 0.5–0.65 の item に増分が集中するのは疑うべき型。これは反証可能な検査で、Jev についての既知の結果ではない。

**D8. 循環: 判定者が自分の仲間を評価する。論争あり [CLAIM] — SNIP。** Clarke & Dietz, "LLM-based relevance assessment still can't replace human relevance assessment", arXiv 2412.17156, https://arxiv.org/abs/2412.17156。検索要約: LLM 判定は循環的だと論じ、TREC RAG 2024 の全 system に Umbrela を最終 reranker として使った simulation で順位が動くことを示す。Faggioli らは NDCG@10 の一致 tau = 0.86 を報告しつつ人手の置換には警告する。要約は、集計の相関が強く見えても、上位の近い system は誤順序になる、という論争も記す。2026 の snippet: reranker 型の判定者は全て自分の system を最高と評価した（source 未特定）。含意は D6 と同じで、追加の action は無し。

**D9. 雑音のある判定者の count を小さな人手 label 集合で補正する（prediction-powered inference）[SoP] — SNIP。** ARES（arXiv 2311.09476）は小さな labeled 集合 + 大きな unlabeled 集合の PPI で CI を出す。GLIDE library（arXiv 2605.31278、2026）が PPI を産業化。"Efficient Inference for Noisy LLM-as-a-Judge Evaluation"（2026、arXiv ID は結果から未確認）は、PPI++ の区間が測定誤差補正より最大約 10 倍狭く妥当な被覆を持つと主張（abstract のみ、要約経由）。小標本の caveat: label が少ないと正規近似の区間は信頼できない（Kluger ら 2025 の bootstrap 版、要約経由）。count の差を扱う source は見つからなかった。item ごとの pass 指示子の差が自然な推定対象（私の読みで未確認）。こちらとの違い: 推定対象は pass 事象の平均 / count、判定者は Jev、label は著者の blind 読み。著者の label 予算は単一ユーザーなので極小で、小標本の caveat が支配する。含意（別の方法）: 著者が限界的 item を約 50–100 件 label できるなら、N_ot の差の PPI 型 debias。できないなら省略し、計画の classifier だけの noise floor を fallback にして「judge-relative であって truth-relative でない」とラベルする。

#### D-d. その他の枠組み

**D10. TAR の停止規則と recall 推定 [SoP] — SNIP。** Repke らの preprint、https://doi.org/10.22541/au.175074486.66241013/v1（Authorea は 403 で**未読**。data record https://www.pik-potsdam.de/~hellmann/zenodo-mirror/records/17497378/ は読み、raw dataset・ranking・simulation log の一覧のみで所見は無い）。検索要約（SNIP）: Buscar package は「bias=1（Callaghan 2020 CMH）以外では未検証」と記す。2022 年の評価は完了済み 159 review を使った。2024 年の commentary は、いつ安全に止めてよいかの合意は分野に無いとする（https://link.springer.com/article/10.1186/s13643-024-02699-7）。Lewis/Yang/Frieder, CIKM 2021（https://arxiv.org/pdf/2108.12746）: 1 phase の停止規則の多くは統計的保証を欠き、未 review の tail の無作為標本で保証する。Di Nunzio 2026（初期の recall 推定 = ranking model + 小さな確率標本。論文は未発見）。こちらとの違い: TAR は有限固定 collection、review 順位、未 review の tail を前提にする。jrp の日次 firehose の cut はまさにこの構造（BM25 順位、300 で cut、tail = overflow）なので、納品物 (i) には TAR の道具が当てはまる。「どの query を替えるか」には当てはまらない（query ごとに順位付き有限 pool が無い）。brief にあった「Repke 2026 CMH」は見つからなかった。見つかったのは 2025 年の preprint で、その結果は未読。含意（別の方法）: (i) には、300 の cut を停止点として扱い、tail の on-topic 件数を Chao2 で model 化せず、無作為標本で保証 / 推定する（D5 の処方）。有病率が低いと費用が嵩む。標準の「rule of three」（一般統計で出典なし）: tail から n 件を標本抽出して陽性 0 なら、95% で tail 率の上限は約 3/n なので、on-topic 率が数 % なら n は大きくなる。まず tail の有病率を確かめる（安い: 未判定の overflow を標本抽出できる）。

**D11. click と大きな traffic がある場合、ranker 比較は A/B より interleaving [SoP] — SNIP。** Amazon Science の論文（https://cdn.amazon.science/c1/4d/7945330e47539fdd870cb5c73613/interleaved-online-testing-in-large-scale-systems.pdf）: 文献は 10–100 倍の感度を報告。DoorDash: user 内制御で 100 倍超。Airbnb（arXiv 2508.00751、https://arxiv.org/pdf/2508.00751）: interleaving + 反実仮想評価で、randomisation が検索ごとなので、連続実験に carryover を見なかった。教材 page の caveat: click が無いと価値が無い、page 全体・長期の効果は見えない、ペアのみ、効果の大きさでなく変種の順位付け。こちらとの違い: user ごとの impression の click が無く、oracle は classifier、ユーザーは 1 人、周期は日次（≈ 1 日 1 単位）。interleaving の利点はペア設計（各単位が自分の対照）で、凍結 replay は同じ日の fetch を両 config の下で判定するので既に得ている。interleaving / switchback が足すのは drift と feedback に対する live の検査。単一ユーザーの switchback の source は無かった。carryover はここでは無視できない（store の状態と seed が毎日の accepted paper で進む。R2・R8）。含意: replay が主で、live の検査は勝ち候補だけの短い交互日の run を同じ classifier で判定し、推定でなく確認として受け入れる。標本数の根拠は無く、設計上の未決。

#### D-e. REASONING — 外部 source のない推論（brief の事実から導いた仮説。行動の前に repo で確認する）

- **R1 — 「store に対して新しい」は、現行 config が埋めた store に対する測定。** replay が今日の store に対して新規性を計算すると、現行 config が既に fetch した物は全て「新しくない」ので、現行と違う候補が有利に見え（新奇性 bias）、現行 config は net を使い尽くしたように見える。防護: 新規性は replay する各日の時点の store（snapshot か日付で絞った ingest）に対して計算し、自己検査として、現行 config を自分の cassette で replay して N_ot がその日の live pipeline の記録と一致することを要求する。
- **R2 — seed は時間依存。** S2 / OpenAlex の net を今日の accepted paper を seed にして過去の日に replay するのは時代錯誤（未来の seed、加えて D1 の feedback loop）。防護: replay 日ごとに seed 集合を凍結し、忠実に replay できない net を文書化し、その候補の数値は上に偏るとして扱う。
- **R3 — 下限は「足す」を許すが、「落とす / 止める」は許さない。** Chao2 ≥ X は「少なくとも X を見逃している」を支えるが、「この query 群は枯渇した」は支えない（語彙を共有する query の Q1 = 0 は正の依存が作るもの）。どの net にも捕獲確率ゼロの paper（arXiv RSS の category 外で、どの seed にも似ない物など）は推定対象の外。防護: Chao2 は「被覆を足す」方向にだけ使い、検出できる母集団の境界を明記する。
- **R4 — query ごとの unique 寄与は重なりがあると破綻する。** leave-one-out は A の寄与 0（B が覆う）、B の寄与 0（A が覆う）と言うが、両方を落とせば失う。防護: swap は**集合として**評価する（候補集合 S を除き T を足して再計算）。1 つずつ落とす貪欲法で、query ごとの unique の和でなく。
- **R5 — count の差への閾値 noise。** 判定を 1 回 cache（凍結）すれば共有 item は厳密に相殺し、差の分散は対称差からだけ来る。brief の反転確率 q: 2–3/40 ≈ 0.05–0.075（同一状態）、0.14（下流の経路が反転）。反転が item ごとに独立なら Var(Δ) ≈ n_sym · q(1−q): n_sym = 100 で sd ≈ 2.2–2.6（q 0.05–0.075）〜 3.5（q 0.14）。config 固有の item は閾値の近くにある可能性が高く、実際の q はおそらくもっと高い。再質問の平均は無作為 noise しか消さず、Jev の系統的 bias（D6–D8）は消さない。防護: 対称差の各 item を k 回判定し、hard 閾値の count の横に平均確率の count（部分 pass の和）を報告する。上の sd より小さい効果は勝者でない。測定した noise floor 未満の N_ot 差を示さない。
- **R6 — Goodhart: N_ot は「良い intake」の proxy で、下流の slot の上限はノートあたり 9 claim。** on-topic の到着が既に多くの日で 9 を超えるなら、on-topic を増やしても出力は増えず screening 費用だけが増え、利得は上位 9 の質にある。firehose の「fill」で BM25 の低い overflow を足すと、事前確率の低い item が増える。この枠組みの source は無し（検索せず）。防護: slot を意識した metric（候補が上位 9 の集合を変える日の割合、9 番目の item の Jev score）を足し、N_ot の隣に費用（classifier call / 日）を報告する。
- **R7 — Chao2 の sampling unit の選択。** 日は独立でない（paper は日をまたいで再出現し、arXiv / HF の stream は時系列）。query は authored で rotate され、標本ではない。unit が少なく、heterogeneity があり、依存があると（D1・D2）、unit の resample から出す区間は不確かさを過小評価する。防護: 走らせる前に unit を定義し、resample が何を意味するかを書き、「at least」の言い方を保つ。
- **R8 — 時間 drift。** 凍結した日は、その日々の arXiv / HF の構成（学会 deadline、topic の突発）を反映するが、候補は明日走る。source は取得せず。防護: 平日 / 週末と少なくとも 1 回の deadline 周期を含む長さの window で replay し、週ごとの結果を報告し、最後の live の交互日確認（D11）を残す。

## Contradictions

1. **brief の arXiv 2404.01176 の読みは、論文本文と合わない。** brief は「Chao2 / Good–Turing」「10 以上の unit」と見ていたが、論文本文（FULL、26 ページ）は TAR の停止規則で、unit は C=5 の ensemble member、(T−1)/T 因子なし、「Chao2」の名なし、「≥10 sampling units」の記述なし（B2）。「Chao2」「Good–Turing」「incidence」の語は Chao & Colwell 2017 由来。論文本文を読んだ capture-recapture 角度の根拠が強い。

2. **「unit は少なくとも 10」は出典なし。近い数は ≥5・≥20・10（class 境界）で、互いに食い違う（B4）。** Chao 1987 は少なくとも 5 を推奨するが、その simulation 自体が t=10 でも 8 母集団すべてで点推定が真値未満、CI 被覆は 8 つ中 7 つで名目未満、t=5 でも被覆 79–99% と示す。つまり推奨値と simulation の結果が一致しない（FULL、一次）。Gotelli & Colwell の ≥20 は rarefaction 曲線の話で Chao2 の最小 T ではなく、ICE の 10 は class 境界。現代の T<10 の simulation は見つからなかった。

3. **Chao2 の規約が 2 つ（Q2>0 の数値が違う）。** Chao & Colwell 2017 / vegan::specpool は古典形（Q2>0 で Q1²/(2Q2)）、Gotelli & Colwell 2011 Box 4.1 は常に使える bias-corrected 形（`q1(q1-1)/(2(q2+1))`）。Bron の count（Q1=40, Q2=33）で 24.24 対 22.94（どちらも (T−1)/T の前）。さらに Bron 2024 の golden example は (T−1)/T 因子なし（Chao 1987 の式）なので、Chao & Colwell 2017 の A 因子つき式と同じ入力でも出力が異なる。どちらが「正」かでなく、規約の名前を code とテストに書く必要がある。Q2>0 での EstimateS の現行規約は Box 4.1 経由でしか分からない。

4. **Chao2 の「下限」は、独立・無作為 unit という前提が満たされるときだけ成り立つ。** capture-recapture 角度（FULL の一次）は、下限性は heterogeneity（φ0 ≤ φ1）から来ると示す。adversarial 角度は、seed 型 net が正の依存を作るので前提が壊れる、と論じる。ただし依存の方向（正なら過小推定）の根拠は 2 list の Lincoln-Petersen（Chatterjee & Bhuyan、FULL だが Intro のみ）と、Tsay & Chao 2001 の snippet 止まりで、**multi-unit の Chao2 についての方向と大きさを示す source は無い**。両者は方向では矛盾しない（過小推定側）。Tsay & Chao は負の依存では符号が逆と言う。加えて Bron 自身が「contagion は無い」と仮定した上でなお、保守的規則の 95% 目標が 70% の run でしか満たされず、全手法が過小推定する傾向を報告している（B2）。下限の主張は「少なくとも」まで、「CI 上限が保証」までは言えない。

5. **判定者の noise は集計で消えるのか、系統的に順位を反転させるのか。** freeze-replay 角度: 人の annotator 間の不一致は大きい（Cohen's kappa 0.11〜0.19）のに system 順位 tau は 0.879（A7、FULL fetch、1 collection）、UMBRELA は run 水準で人手と高く相関（A8、abstract / snippet）。adversarial 角度: 判定者の bias は LLM 系と非 LLM 系の順位を反転させ、全 system の tau は 0.077/0.143 だが oracle のみでは 0.600/0.867（D6、fetch 要約、自称「例示的」で 2 collection・1 model family）。矛盾というより別の noise を言っている。無作為な不一致は平均で消え、系統的な好みは消えない。A7 自身も種類の違う system（LLM 系）は最も動いたと認めている。jrp にはどちらの根拠も直接は当たらず（passage 対 paper、人 対 classifier）、どちらが強いかは決まらない。繰り返し再質問は前者にだけ効く（R5）。

6. **pool の偏りが消えるか残るか。** freeze-replay: 全 item を判定して cache すれば、未判定の穴という意味の pool bias は避けられる（A1・A3）。adversarial: precision 型の count では消えるが、分母としての pool（relative recall・Chao2）は構成した config に偏る（D4）。Sampson の caveat（relative recall が高くても実際の recall はほぼ 0 でありうる、B7）も同じ側。矛盾でなく範囲の違い。どれも snippet 水準の pool 研究に依る。

7. **区間の作り方。** query-performance: shifted bootstrap の p 値は topic が少ないと anti-conservative（Smucker 2009、FULL）で、randomization か平均差への t が勧められる（C8）。adversarial: bootstrap 区間を unit にわたって出すべき（D2 の含意）、ただし unit が依存するなら resample は不確かさを過小評価する（R7）。capture-recapture: 日で cluster した binomial / bootstrap（出典なしの提案、B7）。resample の単位は日・line・query・net のどれか、source は決めない。Smucker は p 値の話で percentile-bootstrap の CI 被覆の source は無い。日が交換可能かは未検証（C8）。

8. **tail（cut の下）の見逃しの推定法。** capture-recapture は Chao2 で下限を置く（出典あり、ただし前提が B3・B6 で弱い）。adversarial は無作為 slice / TAR の標本認証が、独立の仮定が要らず直接答える、と論じる（D5・D10。D5 の slice は推論、TAR は snippet と未読の preprint）。freeze-replay は overflow が小さければ cap 外の未判定 overflow を全部判定する案（A1 の移せる部分、overflow 件数は repo の問い）。3 案は排他でない。出典の強さは Chao2 の式が最も強く、jrp の前提への適合は最も弱い。

9. **Motschall 2009 の数値の食い違い。** capture-recapture は主効果 56 / 全 2 次交互作用 1,439 / BIC 選択 82 と読み、adversarial は 56（95% CI 36–86）/ 1439（410–5045）/ 「交互作用 1 つの model が妥当」と読む。どちらも snippet 水準で、82 と「交互作用 1 つ」が同じ model かは確認できない。model の選び方で推定が約 25 倍動く、という結論は一致する。

10. **brief の「Repke 2026 CMH」は未確認。** 見つかったのは 2025 年の preprint（Authorea、403 で本文未読）と data record だけで、2026 年版は見つからない。TAR の停止規則を借りる根拠はまだ読めていない（D10）。

11. **Hook & Regal の年の食い違い（正の依存で過小推定という引用）。** capture-recapture 角度は arXiv 1703.03022 の snippet から 1995 と記録し、adversarial 角度は同じ論文の Intro を読んで 1982（と Chao ら 2001）と記録した。本文を読んだ adversarial 側が強い。年は結論（正の依存は過小推定）を変えない。

## Still unknown

- 同一入力で classifier / LLM 判定者を繰り返したときの揺れが、候補の順序に及ぼす影響: 研究が見つからない。LLMJudge challenge overview（TREC 2023 DL、42 の LLM 生成判定集合）と Yu ら SIGIR '26 の本文に安定性の解析があるかは未確認。Jev の 0.01 刻みの p が同一入力で決定的か、0.5 判定の反転率は jrp 側の測定。
- Chao2 の方向と大きさ: multi-unit の incidence 推定量での依存 bias は source 無し（LP の 2 list のみ）。jrp 自身の cassette に既知の依存を注入する simulation の方が文献より早く決着する。net ごとの検出法則（M_t / M_th）、Chao・Lee・Jeng 1992 の coverage ベース推定量（ACE / ICE）は未読で、時間 / source 効果があると保証が弱くなるという記憶は未検証。T<10 の現代の simulation は無い。
- seed 型 net（S2、accepted paper の OpenAlex citations）の bias の大きさを定量した source: 無い。Tsay & Chao 2001 と "Recapture or Precapture?" が手がかりだが、どちらも snippet 水準。Kastner 2009 / Bramer 2017 が citation-seeded な source を別扱いするかは確認できず。
- EstimateS User Guide Appendix B と Chao & Chiu 2016: 未取得。Q2=0 の分散と非対称 CI の規約は Chao & Colwell 2017 と Chao 1987 から取った。
- unit の定義（日 / net / query）と resample の単位は設計の選択で、repo のデータ次第。net ごとの relative recall・unique 寄与の区間の方法は source 無し。
- 「n 回ゼロ新規が続いたら query を退役」の数値規則: 2 回の検索で無し。Bramer と Hausner の全文は未読で、数値は検索要約水準。Staudinger 2024 と QPP-GenRE は要約水準、Wang 2025 の NNR・metric 式は未確認。Ntoulas 2005 の貪欲基準の厳密な形と費用 model、Lagisz pp.9–14 も未読。
- n=20〜50 の単位・自己相関のある単位での、平均差に対する percentile-bootstrap CI の被覆率。古典的な pre/post-retrieval QPP 予測器がブラックボックス API adapter で信号を持つか。
- 原本の pool 再利用性の数値（Zobel 1998、Hashemi ら SIGIR 2015、NIST AQUAINT 2005）と MTC の停止規則の詳細、集合 count での挙動: 二次の snippet のみ。infAP / statAP（tail の on-topic 率の推定、見逃し下限と重なる）の原論文は未検索。
- Alaofi、Clarke & Dietz、Tanaka（前提）、Buckley ら 2007、PPI 論文の小標本挙動の本文チェック。Repke らの実際の所見（停止法が目標 recall を守ったか、dataset の大きさ・有病率）: 次は Zenodo record 10.5281/zenodo.17497378 かそこから辿れる GitHub repo。
- 単一ユーザーの switchback / N-of-1 の設計指針と標本数。Goodhart / 固定 judge への過適合を intake system で論じた source。ClueWeb22 などの凍結 web corpus。pytest-recording と respx の機能。
- jrp 側の問い（source では決まらない）: overflow の件数（未判定 overflow を全部判定するか depth-k pooling にするかを決める）、store の日ごとの snapshot と seed の日ごとの凍結が可能か（R1・R2）、Jev が question の keyword を見るか（D7 の適用度。非 on-topic の約 40 item への keyword 注入 probe で検査できる）、複数の snapshot 日が要るか（A11 の 5 番）。
- 失効条件: freeze-replay の知見は「同一入力の judge 揺れを検索結果の比較で測った研究」が現れるか、vcrpy / BrowseComp-Plus の docs が変わるまで有効。Python の Chao2 は、保守されている PyPI package に `chao2` が現れたら手書きの勧めが失効する。いずれも as-of 2026-10-20、この分野は 1 週間で古くなりうる。

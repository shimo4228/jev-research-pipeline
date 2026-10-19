# jrp 品質計測の棚卸し（パーツ別の指標を置く前の調査）

as-of 2026-10-19。repo main（HEAD fa67ed5）、本番 store（`store/lines/*.jsonld` ほか）、vault-stage と vault のノート 99 本、`~/Library/Logs/jrp-run.log` / `jrp-drift.log`、`~/.config/jrp/env`（値は読まない）を読むだけで調べた。`jrp run` / `jrp try` / `jrp prose` は走らせていない。
方法: 担当を 9 つに分けて計測を洗い出し、0 や定数が続く計器 12 件を個別に調べた。各判定にはコードを読み直す反証役と、データを数え直す反証役を 1 本ずつ付けた。最後に抜けの点検を 1 本回した。外部手法は 5 つの角度で一次資料にあたり、それぞれ裏取りした。数値は反証で直した後の値。

## 要旨

1. 毎朝の運用欄にある数の多くは、品質を測っていない。**壊れているもの**: Time-to-Discovery。**縮退しているもの**: 収束推定 f、topic クラスタ数、rubric の gold 一致、rule 候補、support の段。**誤ラベル**: claude_calls、cost、ans の「3 run 未満」。動いているのは、ほとんどが予算・上限・曜日の写しになっている（Jev 質問数・取得数）。
2. 本当の 0 もある。firehose の月曜 0（arXiv / HF の公開日程）と記入率 0.00（著者のチェックが 10-08 以降ほぼ無い）は計器どおり。ans の 0 claims は計器の故障ではない。収集の穴、選別の policy、claim_detection の定義の組み合わせで起きている。ただし、0 claims を DEGRADED にしないため 13 回黙って空のノートが届いた。
3. **警報の経路が 1 本も無い**。通知チャネルが env に無く、DEGRADED（18 run 中 4 回）も drift もログにしか出ない。ログには時刻も無い。
4. **10-20 に始まる used rate は、本番では vault を見ない**。stage には jrp のノートしか無く、used は jrp 名を読み飛ばす。11-19 までは 1.00 か「測定中」しか取れない。
5. store には、パーツごとの指標を自動で出す材料がほぼ揃っている（StageRecord・Judgment・Decision・QuestionLog・Label）。無いのは、終了時刻、net ごとの cap 前件数と新規件数の台帳、負例のラベル、Jev の実 token 数。
6. 全パーツを横切る**反復**が目立つ。keyword の新規 source 率はほぼ 0〜8%、Review の 8 割が再掲、掲載上限で落ちた claim が毎日戻ってくる。

## 計測の地図

272 項目（critic の追加分を含む）。パーツは著者のたたき台に置いた。

| パーツ | 動く | 定数 | 常に 0 | ほぼ 0 | 未生成 | 毎日見える | 見える場所が無い（store だけ / dev だけ / 誰も） |
|---|---|---|---|---|---|---|---|
| P1 問いと検索語 | 7 | 9 | 0 | 1 | 6 | 5 | 14 |
| P2 収集 | 15 | 2 | 2 | 4 | 0 | 16 | 3 |
| P3 選別 | 29 | 3 | 4 | 2 | 11 | 17 | 19 |
| P4 根拠の抽出 | 17 | 8 | 3 | 4 | 8 | 22 | 13 |
| P5 執筆 | 26 | 6 | 3 | 2 | 3 | 6 | 30 |
| P6 運用 | 27 | 10 | 0 | 7 | 24 | 24 | 29 |
| P7 成果 | 1 | 5 | 1 | 4 | 8 | 10 | 5 |

データはあるが表に出していない指標の候補は 133 件ある（P3 24、P6 22、P5 21、P2 18、P1 17、P4 15、P7 14）。項目ごとの producer（path:line）と根拠は、調査時の作業ファイルに全件ある。この報告には判断に効くものだけを載せる。

## 0 と定数の判定

| 計器（運用欄） | 判定 | 仕組み | 主な箇所 |
|---|---|---|---|
| net 取得数の firehose 0（09-28・10-05・10-12・10-19、すべて月曜） | 本物の 0 | 05:00 JST の run は、arXiv RSS の前日 ET の feed を読む。この feed は日・月の JST に空になる（休日 10-12 の影響で 10-14 も空）。HF daily は `hf_date` が「UTC の前日」なので、月・火の JST は土日分を引いて空になる。表示は cap 後の値で、300 は飽和。成功した StageRecord が `outputs=[]` で残っているので、失敗の握りつぶしではない | `adapters/firehose.py:67-71`、`pipeline/nets.py:229-238,462-476` |
| net 取得数の citation 0（jev は全期間） | 縮退 | 毎朝 3 本の `cites:` が成功して空を返す。種は最初の問いの evidence を新しい順に 3 件取るので、公開 3〜47 日（中央値 5 日）の preprint になり、まだ誰にも引用されていない。OpenAlex は arXiv だけで出た work の参照をほぼ持たない。S2・HF の URL は種にならない（jev は 129 件中 63 件だけが種になれる）。古い種で取れた分は 200 字未満で「本文なし」になる。citation 由来の claim は全期間 0。全要求が失敗した日は 0 でなく欠落になる | `pipeline/run.py:626-635`、`pipeline/nets.py:247,552-564` |
| topic クラスタ数 0（5 ライン） | 縮退 | topic を本文に持つのは openalex adapter（citation / exploration）の source だけ。exploration は既知の topic が無いと計画されない。予算 1 で、@id 順で先頭の topic を毎回歩く。「前回」は前の run でも累計でもなく、「最後の取得が今日より前の source」 | `pipeline/meters.py:52-54`、`adapters/openalex.py:142-184`、`pipeline/run.py:1161-1162` |
| ans の 0 claims（09-23 以降 13 run） | 複合 | 全滅する段が run ごとに移る。① 形式モデルの論文が Tavily の 200 字未満スニペットで届き、prefilter の前に「本文なし」で捨てられる ② firehose の prefilter 通過は 0/2420、q1 は 0 ③ triage と trust が理論・解説を落とす ④ screening で evidence_strength が asserted と読まれる（同じ論文でもスニペットの版で重み付き 0.535〜0.62）か、min_certainty 0.5 の床に止まる ⑤ 唯一の Keep（Thoughtseeds）の 7 文を claim_detection が「own setup = unrelated」で全部落とした ⑥ claim も ⭕ も無いので、recommendation / citation / exploration が cold start のまま。desire の 09-29 / 10-01 の 0 は、報告済みの claim を除いて消えたもの | `pipeline/run.py:728`、`jev/question_screening.py:211-260`、design「Discovery gaps on ans / desire」 |
| Time-to-Discovery（jev が毎日 +1、rotation は 0.0） | 壊れている | 両端とも最新の時刻で上書きされる。Label は毎 tick に全ラインで収穫し直され、`harvested_at=now` になる（store の Label 163 件はすべて 2026-10-19T05:00）。SourceItem は再取得のたびに `fetched_at=now` になる。jev では中央の source が 10-06 から再取得されていない。store から正しく出すと jev は約 1 日で、著者は届いた朝にチェックしている | `report/vault.py:173-178`、`pipeline/runner.py:209-214`、`adapters/base.py:248`、`pipeline/meters.py:76-98` |
| 記入率 0.00（10-10 以降） | 本物の 0 | 著者のチェックは jrp:qday の [x] だけ（29 個。10-08 以降は 2 個）。harvest → Label → 次 run の記入率の経路は、収穫できる 28 個すべてで通る。ただし「label N 件」は在庫の累計で、「取り消し」は 10-01 以前は誤計数だった。後から付けたチェックは印字に出ない。rotation ラインでは、run しない日の harvest がどこにも残らない | `pipeline/run.py:1585`、`pipeline/runner.py:114-131,251,276` |
| 収束推定 f（0.72〜0.88 に張り付き） | 縮退 + 誤ラベル | `ceiling = 最新累計 × 1.2` で固定するので、直線の累計は約 0.75 に写る（N=25 で 0.752、極限 0.745）。入力は掲載上限（1 ノート 9 件）を通った後の Report.claims で、ほぼ直線になる。docstring の言う per-net でもない。ans の「データ不足 (3 run 未満)」は、実際には `cumulative[-1] <= 0` の分岐 | `pipeline/meters.py:57-73`、`pipeline/run.py:1173-1174`、`note_text.py:306` |
| claude_calls: 0 | 誤ラベル | リテラルの 0 で、schema も `Literal[0]`。本番は 10-03 から claude -p で、17 朝に 198 回呼んでいる。実数は GenerationMeter.requests が持っている | `pipeline/run.py:1227,1241`、`model/nodes.py:568`、`generation/client.py:267` |
| cost | 誤ラベル（大半が映らない） | 「Jev 質問数 × 仮定単価 0.00002」と、サブスクで 0 と数える writer の和。API 換算で消費の約 93% が映らない。$1 の cap は Jev 50,000 問相当まで発火しない（実際の最大は 3,523）。Jev の実 token は応答の usage にあるが捨てている | `pipeline/costs.py:33-46`、`pipeline/run.py:1189-1196` |
| 段の所要 support 0s / rubric 0s | 縮退 / 本物 | claim は逐語なので string_match が常に真で、source_support の Jev 呼び出しは全 store で 0 件。rubric は数件の並列呼び出しが 1 秒未満で終わるだけ。queries 段の秒は store の書き直しで、prefilter は fetch 段の中で走る | `jev/source_support.py:77-78`、`pipeline/run.py:516-522,582` |
| rubric 各軸の gold 一致 | 縮退 | gold は、qday の [x] を配下の claim に伝播したものだけ。全件 correct で負例は 0。一致率は「ラベル付き claim のうち軸が pass を出した割合」になる。grounded は全 498 判定が pass で定数。`tests/test_quality.py:119-126` がこの縮退を期待値として固定している。trusted_axes は、常に pass する軸ほど信頼する | `quality.py:77-105`、`report/vault.py:185-189` |
| canary（jev-papers が 10-08 以降 drop） | 混在 | probe の state に入る evidence_set が 0→77 claim に増えるにつれ、on_topic が 0.68→0.48 に下がった（Spearman −0.83）。10-02 には bundle も 1 度変わった。server 側のモデル変化とは分けられない。canary を持つのは 21 問中 1 問 | `pipeline/run.py:802-845`、`jev/question_screening.py:171-185` |
| drift / OTel | 未生成 / 設計どおり停止 | drift は毎週月曜に env の門で exit 2 になる。基準の live cassette は一度も作られておらず、門を開けても「0 answers compared」で exit 0。ただし Judgment の state は store から再構成できる（jev 88%・desire 96%・edge 98%）。jev では 64 の (source, 問い) 対が 10 日以上、自然に判定し直されている | `pipeline/drift.py:54-87`、`cli.py:265-279` |
| rule 候補（毎日 13〜17 行） | 死んだ計器 | 「一致率」は、特徴で切った split の中での Decision.outcome の多数派の割合で、著者ラベルとの一致ではない。当日に作り直した Decision を二重に数える。採否の記録も、読むコードも無い。`jrp fit` / `export-cases` は一度も走っていない（fit は gold が 1 クラスなので全部 skip する）。行が 12 KB 枠を食い、Review を推定 70〜100 件押し出した | `reduction/rules.py:42-104`、`reduction/log.py:52-55`、`pipeline/run.py:1216-1217,1448-1470` |

## 0 以外の重い事実

- **used rate（10-20 開始）は vault を見ない**。launchd の wrapper は python に iCloud を触らせないため、`JRP_VAULT_DIR` を stage に向ける（`scripts/launchd-jrp.sh:142-145,165`）。stage には `*_jrp_*.md` しか無い。used は jrp 名のファイルを読み飛ばす（`reduction/used.py:186,214`）ので、vault 経路は常に空になる。見えるのは対象 repo の graph.jsonld と ADR だけ（7 ライン中 4 ライン）。さらに、初回 scan より前に出た source は窓が閉じても unknown になる（`used.py:275-277,318`）。このため 11-19 までは率が 1.00 か「測定中」になる。S2 の URL（`semanticscholar.org/paper/<hash>`）は照合できない（jev の引用 source 39/128）
- **通知の経路が 0 本**。env に Slack / macOS の設定が無い（`JRP_SLACK_NOTIFY` はコメントの中）。`notify()` は False を返すだけで、`cli.py:175` はそれを見ない。DEGRADED でも exit 0。doctor は存在しか見ないので ok を出す
- **ログに時刻が無い**。開始は Judgment.judged_at（run の now）、終了はノートの mtime で推定できる。ふだんの tick は 4〜7 分。10-15 は Maintenance Sleep で約 16 分遅れたが、段の所要には見えない（monotonic clock）
- **反復が支配している**。keyword は 76 クエリ中 16 が枯渇し、`hf:` は 53 送信中 46 が新規 0。Review の再掲は 8 割。10-19 の jev の Keep のうち新規は 1/35。novelty の判定の 62% が判定し直し。掲載上限で落ちた claim が毎日戻ってくる（jev は Claim 678 件中 473 件が一度も掲載されていない）
- **net 別の歩留まり**（jev、取得 1000 件あたりの掲載 claim）: recommendation 254、firehose arXiv 7.5、web 0、citation / exploration 0（本文が無い）。ans は Jev の回答の 88% を firehose に使い、掲載は 0。firehose arXiv は 13,708 件中 35% しか判定に届いていない（cap）
- **screening の境界が厚い**。question_screening の判定の 37〜39% が採用線 0.6 の ±0.05 に集まる。続けて判定し直すと 14% で route が変わる（同じ state での雑音は 2〜3/40、design 2026-10-01）。prefilter は 9 割を落とすが、design が約束した「落とした側の無作為標本の監査」（pipeline-design.md:303-304）は実装されていない。bridges は v3 以降 0/1,478 で、閾値 0.8 は分布の上限 0.77 より上にある
- **P5**: 本番の template 率は 6.9%（10-02〜10-19）、第2稿は 9/101。rubric_report v2 の unsupported_statement は一度も足切りしていない。claim_fidelity は中央値 0.45 で、判別が弱い。bench の cases は 10-01 で凍結され、10-02 以降の本番の本文 94 本が入っていない。bench のコード検査（`prose_bench.py:242-310`、純関数で無料）は本番に当てていない。本文で一度も触れない source が 19〜24%、[n] と (Sk) の食い違いが 2.5%、根拠段落の数値は 93% 以上が材料にある
- **P4**: 「引用が本物か」は、設計上ほぼ自明（claim = unit の逐語）。崩れるのは、再取得で source の本文が上書きされたとき（jev の逐語保持は 96.9%）。実際に効いている判断は claim_detection・novelty・掲載上限で、上限を通るのは claim の 8〜21%。照応語で始まる claim が 18.6%
- **P1**: open な 21 問のうち 9 問が 14 日以上動いておらず、6 問は一度も動いていない（ans 3 問ほか）。問いごとの prefilter 通過率は、ans の 1 問で 0/2611。question_movement はほぼ常に accept（jev 71/72）なので、「動いた」は「claim があった」とほぼ同じ意味になる
- **Jev の版**: jev-1.14.0 が 2026-10-14 に出た。jrp は jev-1.13.0 に固定（`jev/core.py:55`）。外部監査（Meng 2026-09-24、preprint）によると、1.13.0 の確率は 0.01 格子で 1.00 に飽和し、質問の形で ECE が変わる

## パーツごとの棚卸し

各パーツを、ある・見ている（ただし中身の注記つき）、あるが見ていない、無い、著者の判断が要る、に分ける。

### P1 問いと検索語

- 毎日見える: 「open な問い 3 件」（`run.py:1245`。設定の写しで情報なし）、「query: 問いファイルの n 件を使用」（`run.py:172`。keyword の予算は 10 件なので、1 件は毎回送られていない。`nets.py:274-278`）
- あるが見ていない: クエリ × 日 → source の StageRecord（`adapters/collect.py:29-49`）、問いごとの prefilter の on_topic（Judgment の `q{i}_on_topic`）、QuestionLog.movement、Question.evidence の伸び、`jrp queries check`（dev のみ）
- 無い: 「2 週間動いていない問い」の検知（AGENTS.md の起動条件。今は著者が気づくのを待つ）、クエリの枯渇（新規 source 率）、on-topic なのに根拠が弱い率（evidence: 行のずれ）
- 著者の判断: 問いの書き換え・退役、evidence: 行（例: ans で理論を証拠に数えるか）

### P2 収集

- 毎日見える（注記つき）: net 取得数（cap 後で、予算の読み値）、net 採用率（中身は 9 件以下の claim の構成比）、topic クラスタ数（縮退）、収束推定 f（縮退）、Time-to-Discovery（壊れている）、openalex credit（tick の累計の途中値）、firehose の省略行、検証落ち、本文なし、タイトル重複
- あるが見ていない: net ごとの cap 前件数と新規件数（StageRecord.outputs）、net 別の漏斗と歩留まり、firehose の切り捨て率、canary を net が持ってきた率（jev は 81 日中 1 回）
- 無い: 取りこぼし（recall）の推定、net の台帳（planned / sent / raw / new / kept、0 と欠落の区別）、rotation ラインが見ていない batch の量
- 著者の判断: citation net のデータ源（S2 の key を入れる / 止める / 空のまま残す）、firehose の空き枠の使い方、exploration の予算

### P3 選別

- 毎日見える（注記つき）: (source, 問い) 対の Jev 失敗（分母に cache hit が入り、screen の失敗率が約 1/7 に薄まる）、Review の表示、canary（混在）、rule 候補（死んでいる）
- あるが見ていない: Judgment / Decision の分布から出る境界の厚み、再判定での route 反転率、prefilter と screen の on_topic の食い違い（jev 30%）、adapter 別の reject 率（trust は事実上 web_search のフィルタ）、bridges の分布
- 無い: 較正（ラベルが無い）、prefilter の reject の監査、drift、本文がある日の route 別件数（空の日にしか出ない）
- 著者の判断: 何を証拠に数えるか（問いの evidence: 行）、閾値の変更

### P4 根拠の抽出

- 毎日見える（注記つき）: rubric grounded（定数）、「claim n 件のうち m 件を掲載」（日をまたいで同じ claim を数える）、support 0s（縮退）
- あるが見ていない: claim_detection の歩留まり（jev 35%、ans 0/7）、novelty の判定し直し率、未掲載 claim の滞留、逐語保持率、照応語で始まる claim、Unit の切断の破損
- 無い: claim 抽出の recall（要旨のどこまでを claim が覆うか）
- 著者の判断: claim_detection の「own setup」の扱い（ans に claim を出すか、健全なラインの判定が動くことを受け入れるか。design の Addendum 2026-10-01）

### P5 執筆

- 毎日見える: 「prose 第n稿: 生成 s」、template かどうか（本文）、生成 token
- あるが見ていない: rubric_report v2 の readability / coherence / unsupported、claim_fidelity（`quality.py:205-249`）、Report.rendering（最後の節で上書きされる）、本文の引用 coverage と [n]–(Sk) の整合、数値の根拠率
- dev だけ: bench の足切り・facts・誤解・止まった箇所・字数・コード検査（`pipeline/prose_eval.py`、`prose_bench.py`）。cases は 10-01 で凍結。本番の本文を bench で測ったのは 09-28〜10-01 の 13 件の 1 回だけ
- 無い: 本番の本文に bench の物差しを当てる経路（shadow bench）、template 率の集計（design の Review-when）、self-check での修正量
- 著者の判断: 読みやすさ（blind 読み）。今のところ唯一の正解

### P6 運用

- ログにだけ出る（誰も読まない）: run の題（DEGRADED）、「n claims」、DEGRADED の理由、vault へのコピー、doctor の ok 行
- 毎日見える（注記つき）: Jev 質問数（store 再利用と曜日で決まる）、生成 token、claude_calls（誤ラベル）、cost（大半が映らない）、段の所要（スリープも段の外の時間も見えない）
- 無い: 通知、ログの時刻、終了時刻と総所要、起動しなかった朝の検知、writer の API 換算と Max の使用量、0 claims を DEGRADED にすること、配達の SLO
- 著者の判断: 通知の経路（Slack / macOS）、writer の費用を数えるか

### P7 成果

- 毎日見える（注記つき）: 記入率（本物の 0。「開いたか」と「読む価値」を混ぜている）、harvest の label 件数（累計）、Time-to-Discovery（壊れている）、used rate（10-20 開始。vault を見ない、11-19 まで偏る）
- 無い: 「開いたか」（Obsidian の最近開いたファイル一覧から読める。読むには著者の許可が要る）、relative recall（著者の文書で使われた論文を jrp が先に持っていたか）、窓が閉じた週コホートだけで出す used rate
- 著者の判断: qday の [x] は唯一の著者の信号。「開いたか」を読んでよいか

## パーツの切り方への疑い

- **著者フィードバック（qday の [x]）は横断の入力**: 同じチェックが、P2（recommendation の正例）、P3（fit・silver）、P4（gold 一致・cases）、P7（記入率・TTD）に同時に入る。チェックが止まると全部が同時に固まる（jev の推薦の正例、gold 一致、harvest 70）
- **計測と警報の系**（通知、drift、ログの時刻、OTel）がどのパーツにも属さない。ここが壊れると、全部の数字が黙る
- P1 は「検索語（keyword と firehose の並べ替えに効く）」と「問いの定義（全 net の判定に効く）」の 2 経路。jev では、問いの証拠の大半が firehose と recommendation から来る（jev-failure-modes は keyword 3/67）
- P2 の中に、コードによる選別が 2 段隠れている（firehose の BM25 cap、本文 200 字の床）。prefilter の通過率は「net が問いに合うものを持ってきたか」を表すので、P2 寄り
- P3 と P4 は交互に並ぶ（screen → claim_detection → novelty → support）。evidence_set が screening / novelty の state に入るので、採った claim が翌日の選別を動かす
- P4 の本当の問いは「残すべき文を残しているか」。「主張を支えているか」は P4 と P5 の継ぎ目（[n]・(Sk)・数値の整合、claim_fidelity）
- P5 は「忠実さ（自動化できる）」と「読みの経済（形・取りこぼし・字数は自動、良し悪しは著者）」に分かれる。dev の bench と本番監視の間に橋が無い
- P6 の DEGRADED は、ほかのパーツの失敗の寄せ集め。P6 は「配達（届いたか・いつか・知らされたか）」と「資源（時間・呼び出し量・quota）」に絞れる。実際に効く制約は USD でなく、Max プランの使用量と API の rate limit
- P7 は「開いたか」「読む価値」「自分の文書で使ったか」の 3 つ
- 横断の軸「反復と新規性」が抜けている

## 外部手法（2026-10-19 時点、裏取り済み）

| 用途 | 手法 | 出典 | jrp での前提 | 失効条件 |
|---|---|---|---|---|
| 取りこぼし | reject の無作為標本の超幾何検定（CMH 型）。比較研究で目標 recall を割らなかった唯一の停止法 | Repke 2026 https://onlinelibrary.wiley.com/doi/10.1002/cesm.70068 | 陽性が稀なので Jev の確率で層化する。ラベル役を強い judge で代用するのは、検証されていない仮説 | CMH 以外で recall 保証を持つ停止法が同規模の比較に入ったとき |
| 取りこぼし | net × item の incidence 行列に Chao2 / Good–Turing を当て、未発見数の下限を出す | https://arxiv.org/abs/2404.01176 | net は独立でない（推薦・引用は採用済みを種にする）ので、下限として読む。sampling unit は 10 以上 | unit が 10 に届かない間は出さない |
| 取りこぼし | 既知の当たり（canary）。割合でなく警報として使う。独立に得た当たりに限る | SAFE https://pmc.ncbi.nlm.nih.gov/articles/PMC10908130 | 今の canary は screen の probe で、net の recall は測らない | — |
| 較正 | Brier + calibration-in-the-large + CORP（ECE 単独は避ける）。小 N では区間だけ出す | https://arxiv.org/abs/2008.03033 | ラベル付きの (確率, 0/1) が要る | Jev が連続値を返すようになったとき |
| 較正 | Jev 1.13.0 の外部監査: 0.01 格子、1.00 への飽和、質問の形で ECE が変わる | Meng 2026-09-24 https://escholarship.org/uc/item/4t4449jv | 同じ版・同じ API の形 | Jev の版が上がったとき（1.14.0 は既に出ている） |
| 判別 | PU-AUC（tick された提示 item と、未 tick の提示 item）。事前確率が要らない | https://arxiv.org/abs/2509.24228 | 母集団は提示済みの item に限る。tick は SAR | 著者の tick の習慣が変わったとき |
| 閾値 | 分割 + 事前に 1 つ決めた閾値 + 片側上界。同じラベルで scan すると誤認証する | Meng 2026（同上） | 質問ごとに数十件のラベル | — |
| drift | 固定 probe の再質問。先に、同一入力の jitter を測る | https://arxiv.org/abs/2512.03816 | 本番と同じ batch=1。Jev は logprob でなく量子化した確率を返す | Jev の版の切り替え |
| 忠実さ | claim_fidelity を同じ判定器の週次トレンドで見る（絶対値の目標を置かない）。既知の崩れ型を実在の草稿に注入し、判定器の検出率を測る | https://arxiv.org/html/2607.20527v1 | ラベル 0 | 判定器や Jev の版が変わったら系列を切る |
| 忠実さ | ALCE の citation precision（今は無い）。支持 / 背景 / 推論 / 不支持の 4 値 | https://arxiv.org/abs/2305.14627 、https://arxiv.org/html/2506.01829v1 | Jev の Choice 1 本 | — |
| 抽出 | 要旨から nugget を作り、抽出した claim が各 nugget を覆うかを見る（claim 抽出の recall の代理） | https://arxiv.org/html/2504.15068v1 | 要旨を参照にするのは jrp 独自の適用 | — |
| 成果 | relative recall（著者の文書で使われた論文を、jrp が先に持っていたか）。分母が jrp と無関係 | Sampson 2006 https://pmc.ncbi.nlm.nih.gov/articles/PMC1557524 | 走査先を広げる | 著者の文書の置き場が変わったとき |
| 成果 | 窓が閉じた週コホートだけを主指標にする | https://arxiv.org/abs/1802.00255 | 30 日窓 | — |
| 成果 | interleaving は今の信号量では回らない（勝率 0.6 の検出に約 194 件） | https://arxiv.org/abs/2607.26380 | — | 信号が週 100 件を超えたとき |
| 死活 | 0 の期待値を暦の関数として宣言する。net の台帳。欄の埋まり率。0・定数の 2 段 severity。dead-man's switch | https://info.arxiv.org/help/availability.html 、https://prometheus.io/docs/practices/instrumentation/ 、https://healthchecks.io/docs/ | 依存を足さない（GX / Soda / Elementary は採らない） | arXiv の公開日程が変わったとき |
| 週次の型 | WBR（output 1 つ + controllable input、例外だけを議論、使われない信号は消す）。funnel の対数分解 | https://commoncog.com/the-amazon-weekly-business-review/ | output の系列は当面 1 点しかない | — |
| 小さい数 | 0/n に rule of three（片側 95% 上限 ≈ 3/n）。区間は 1 種類に統一する | Hanley & Lippman-Hand 1983 | 独立性が崩れる（同じ seed・同じ dedupe）ので目安 | — |

採らないもの: 収束推定の今の式（Undermind の f は振幅と τ を両方 fit する）、PKM の再訪率・backlink（実証が無い）、ja に小型 NLI 検出器を直接当てること、長期 surrogate（N=1 では作れない）。

## 提案: パーツごとの主指標と週次の品質レビュー（相談用、未実装）

作り方: 3 つの角度から独立に案を作った（判断から逆算する / 著者の手間ゼロ / 計器の信頼性から）。審査役 3 人（著者・実装・計測の視点）が採点し、統合して、反証役が崩した。審査は 3 人とも「判断から逆算する」案を最も高く評価した（26 / 26 / 24 点。計器の信頼性 22〜23、手間ゼロ 15〜19）。そこに「計器の信頼性」案の台帳と破壊テストを移植した。以下は、反証の must-fix を反映した後の案。

### 芯

週次レビューが毎週答える問いを 1 つにする。**「来週どのパーツに手を入れると、著者に届く新しい根拠が一番増えるか」**。

- **出力 O1**: 本文で初めて語られた論文の数（週）。数える単位は論文の key（arXiv id・DOI・GitHub slug。S2 は externalIds で解決）。URL では数えない。jev では、本文で引用された source の 12% が、URL だけ違う同じ論文だった
- **出力 O2**: 著者の文書（graph.jsonld・ADR・vault の著者が書く folder）に新しく出た key のうち、jrp が先に本文で届けていた割合。分母は、jrp が届ける量を増やしても膨らまない。ただし著者は jrp を読んでから書くので正の依存があり、値は上限寄りになる。判断には率でなく、外れた key がどの段で止まったか（oracle trace）を使う。O2 は used rate を gate や fit に配線しないことが前提（配線すると最適化の的になる）
- **パーツの主指標は O1 の因子として置く**: cohort（初取得の週）ごとに O1_c = N_ot × p_sel × p_ext × p_wri。各因子の分子は前の段の部分集合なので、この式は恒等式になる。そのため Δln O1_c = Σ Δln（因子）が厳密に成り立ち、パーツの改善余地を「週あたりの ΔO1（区間つき）」という 1 つの単位で比べられる
- **比べてよいのは「生きている」数だけ**: 計器の台帳・期待値の暦・verify に入れた破壊テストが live と判定した数だけを比べる。live でない数は、数値を出さず状態の語で書く

### パーツの切り直し

| id | パーツ | 問い | 旧 |
|---|---|---|---|
| M | 計器と警報（前提層） | 数は生きているか。異常は著者に届くか | 新設（通知・ログの時刻・drift・著者の信号の鮮度） |
| Q | 問い | どの問いが動いておらず、どの段で止まっているか | P1 の問いの定義。段でなく列として置く |
| I | 入口 | 問いに合う新しい source を持ってきたか | P1 の検索語 + P2 + 本文の床 + cap + prefilter |
| S | 選別 | 根拠を取りに行く価値のあるものを残したか。落とした側に届くはずのものは無いか | P3（triage → trust → screening） |
| X | 根拠化と掲載枠 | まだ届けていない文を選び、枠に載せたか | P4 + 掲載上限 |
| W | 執筆 | 載せた根拠を、本文が正しく、取りこぼさずに語ったか | P5 |
| D | 配達と資源 | 朝に届いたか。劣化は知らされたか。何をどれだけ使ったか | P6 |
| OUT | 成果 | 届く新しい根拠は増えているか。著者自身の仕事にまで届いているか | P7 |

「反復と新規性」はパーツにせず、X・I・D の診断として週報の 1 欄にまとめる。著者のチェック（qday の [x]）は品質指標にしない。M の中で鮮度だけを見る。

### 主指標（パーツごとに 1 本）

| パーツ | 主指標 | 計算（読む場所） | 自動 | 前提の修正 |
|---|---|---|---|---|
| OUT | O1 本文で初めて語られた論文の数（週、Poisson 区間） | QuestionLog の text の `[i+1]` → claims[i] → Claim.unit → Unit.source → key。[n] は section ごとの番号なので、Report.claims は使わない | code | 論文の key の統一（S2 externalIds）。parity test |
| OUT | O2 先回り率（k/n。n ≥ 20 で Wilson、月で確定） | Sighting.first_seen の月 × jrp の初回引用日 | code | used の vault 走査、除外 folder、key の統一 |
| Q | 動いている問いの割合（k/21）と、動かない問いの遮断段 | questions/ の open（store の Question node は ans の今の 3 問を持たない）× 14 日の O1 | code | prefilter の q_i と問い IRI の対応を残す |
| I | 問いに合う新規 source 数 N_ot（cohort、内訳 N_new × p_body × p_cap × p_pre） | 初取得日 = StageRecord(fetch_*) の初出（`fetched_at` は上書きされるので使わない）、Judgment(question_prefilter) を `question_prefilter.passing` で判定し直す | code | Judgment → Judged の adapter、RunRecord（要求台帳） |
| S | 選別の通過率 p_sel = N_ot のうち 7 日以内に route keep に届いた割合（guard: 境界の厚み B(0.05)、再判定の flip − jitter） | Judgment(question_screening) を `question_screening.route` で再計算（Decision は上書きされるので使わない） | code | adapter と parity test（rule 再計算 = Decision.outcome、route keep ⊆ accept） |
| X | 根拠化の通過率 p_ext = keep のうち 7 日以内に掲載された割合（内訳 p_detect × p_novel × p_shown） | route keep の対 × Decision(claim_detection) × Claim × QuestionLog の初日 | code | adapter |
| W | 忠実さの足切り通過率（本番の本文から週 6〜10 節を無作為に選び、既存の prose-judge で判定） | `docs/prose-rubric.md` の Q1〜Q6、Opus を claude -p で | llm-judge | 監視用 judge の実行枠（著者の判断） |
| D | 朝の約束（28 日の k/n）= 予定 line-run のうち、06:30 までに vault にあり、劣化があれば通知が送られたもの | 分母は暦から作る（起動しなかった朝も入れる）、RunRecord と watch job | code | 通知の経路、watch job、RunRecord、ログの時刻 |
| M | 計器の生存 = 期待されたセル（計器 × ライン × 日）のうち、未説明の 0・定数・矛盾・欠落の数（guard: 破壊テストの検出率） | 型付きの registry（計器ごとの期待値と severity）、期待値の暦（arXiv / HF の曜日・休止日、rotation、jev の citation の縮退宣言） | code | registry・暦・verify.sh の破壊テスト |

W の主指標を被覆（p_wri = 掲載された論文のうち本文で引用された割合）にしなかった理由: v16 は「claim を持つ研究は 1 本も省かず [n] を付ける」ので、p_wri は構造上 1 に近づき、W の主指標が定数になる。p_wri は guard に下げる。W の guard にはほかに、コード検査（`prose_bench.gates()` を本番の本文に当てる + [n] と (Sk)・数値の照合を新しく書く）と、O1 1 本あたりの字数を置く。

主な guard と診断（少数）:
- **OUT の精度標本**: O1 の論文から週 12 件を無作為に選び、judge が「問いを前に進めるか」を判定する（llm-judge）。O1 の Goodhart（gate を緩める・並べ順を変える）を止める唯一の guard。12 件は弱い（真の率が変わらなくても 2 か月に 1 回は偶然で外れる）ので、2 週分を合わせて判定する
- **I の歩留まり表**: net × adapter 別の新規 / 床 / prefilter / keep / 掲載 / 引用、クエリの枯渇（直近 3 送信が新規 0）
- **S の落とした側の replay**（月 1 段）: cap 溢れ・prefilter の reject・screening の drop から、層別に無作為標本を取る（抽出確率を記録）。scratch で下流へ流し、HT 推定で「届くはずだった数」の下限を出す。design が約束した reject の監査は、ここで果たす
- **X の反復と滞留**: 掲載枠に占める既出の論文、差し替えられる枠、keep なのに claim 0（v3 全期間で 39/479）、Review の再掲、未掲載の滞留と、初取得から初掲載までの日数（Time-to-Discovery の置き換え）
- **D の資源**: O1 1 本あたりの Jev 回答数・claude -p の回数・Jev の実 token、function 別の判定し直しの割合
- **M の著者の信号**: 今週の新しいチェック数（`first_harvested_at`）、recommendation の正例の凍結、許可が出れば「開いたか」

### 運用欄から外す・名前を変える

外す: rule 候補、収束推定 f、topic クラスタ数、Time-to-Discovery、rubric の gold 一致と trusted_axes（`tests/test_quality.py:119-126` も同時に直す）、rubric grounded の平均、support の段の秒、日次の net 採用率（週次の歩留まり表へ）。
名前を変える: claude_calls 0 → writer の呼び出し数（`Literal[0]` を外す）、cost → 「Jev 推定費用（仮定単価、生成は含まない）」、net 取得数 → 「新規（dedupe・上限の後）」、harvest の label N 件 → 「チェック在庫（累計）」、openalex credit → 「tick 累計の途中値」、question_movement の「動いた」→「claim があった」。
drift: 比べた数が 0 のときに exit 0 を返すのをやめる。replay の固定 probe に置き換えるまで、月曜の job は止める（著者が決める）。
記入率: 主指標から降格する。design decision 7（`pipeline-design.md:94`）を supersede する。

### 週次レビューの形

- **どこに**: read-only のサブコマンド `jrp wbr` が、store・questions/・stage を読んで作る。出力は `daily-research/YYYY-MM-DD_jrp_wbr.md`（著者が毎朝開く場所）と、追記だけの `<JRP_STORE_DIR>/metrics/weekly.jsonl`。過去の週の値は snapshot から読み、store の upsert で黙って変わらないようにする。名前に `_jrp_` を含むので used の走査から外れ、slug 別の glob にも当たらないので harvest もしない。本文には key と `jrp:` の印を置かない
- **いつ**: 月曜。wrapper の CMD=run の中で、stage → vault のコピーの**後**に作り、wbr のファイルだけ 2 回目のコピーで送る（朝のノートの配達を遅らせない。timeout も付ける）。手動では `jrp wbr --week 2026-W43 --out <scratch>` で何度でも作り直せる
- **構成**（上から）:
  0. 結論 3 行（今週の 1 手・次点（測る手）・例外の手）と、計器の状態 1 行
  1. 出力: O1 の 6 週（区間・遅着・ライン別）と O2（k/n、上限寄り、走査の被覆）。報告だけで、ここでは議論しない
  2. 例外: 区間の外に出たもの、遮断されたライン・問い、未説明の計器だけ
  3. 分解: 成熟 cohort（初取得の週の翌々週の月曜以降）の Δln 表。全ライン、枠律速、供給律速の 3 本で出す（空き枠は問いごとの上限 `min(5, max(2, 9 // k))` で数える。`run.py:1317`）
  4. どこを直すか: 1 手ずつの ΔO1（本/週）[下限–上限]、根拠、費用、著者の手間。区間が重なる手は同順位
  5. 問い: 動いている k/21 と、動かない問いの遮断段
  6. 反復と新規性
  7. 配達と資源
  8. 前回の 1 手の答え合わせ（commit trailer に残した予測と実績）
  9. 計器（無効な指標と理由、破壊テスト、最長の無音、著者の信号）
- **1 手の選び方**: 区間の下限が 0 を超える手の中から、点推定の最大を選ぶ。下限が 0 の手は「測る」手として次点に置く（replay で測る）。上流の手（I・S・Q）の効果は、空き枠で上限を切る。ゲートを緩める手は、精度標本を通ったときだけ採る
- **基準線の切れ目**: Jev の版（jev-1.14.0 は 10-14 公開。jrp は 1.13.0 固定）、本文プロンプト（**v16 は 10-20 の run から**）、policy、問いの版、クエリ集合の hash を台帳に残す。手は 1 週に 1 つずつ入れる。それでも 4 週の区間はたまらないので、どの変更がどの因子の基準線を切るかの表を持つか、ラインの中で run 日ごとに手の on/off を入れ替える（switchback）
- **毎朝の警報**（週次を待たない。code だけで出す）: error として通知するのは次の 6 つ。① 06:30 までにノートが無い（起動しなかった朝を含む） ② FAILED・TIMED OUT・コピー失敗・doctor FAILED ③ DEGRADED（新しい理由として、問いを持つラインで引用 0 が 2 run 続く、claim 0 かつ Review 0） ④ writer の失敗や usage limit で template に落ちた ⑤ 暦で説明できない 0 が 2 日続く（想定内の 429 は除く。rate limit の連発は burst を止めて報告する） ⑥ 新しい矛盾（例: 生成 token > 0 なのに writer の呼び出し 0）。同じ理由が続くときは、1 日目と 7 日ごとにだけ通知する

試算した形の例（2026-10-19 の store、パッケージ外の暫定計算。O1 は URL 単位なので約 1 割多く出る）: O1 は 09-28 週 48、10-05 週 52、10-12 週 46 [34–61]（jev 22 / akc 9 / aap 8 / authorship 5 / edge 1 / desire 1 / ans 0）。動いている問いは 12/21。分解（09-28 → 10-05 の cohort）は N_ot 577 → 367（Δln −0.45、主に firehose の暦と再取得）、p_sel 0.41 → 0.45、p_ext 0.38 → 0.41、p_wri 0.58 → 0.63。最初の 1 手の候補は「同じ問いの掲載枠で、既に届けた論文より初出の論文を先に並べる」で、ΔO1 は +1〜10 本/週（10-05 週 +1〜4、10-12 週 +3〜10。v16 より前の基準）。v16 の後の成熟 cohort が 2 つ揃う 11-09 以降に測り直してから入れるか、switchback で入れる。

### 前提の修正（順序つき）

今すぐ（数が毎日失われている、または計測の始まりが汚れるもの）:
1. **警報の経路を 1 本開く**（env を 1 行変える。著者が経路を選ぶ）。doctor に「経路が 0 本なら FAIL」を足す。notify の戻り値を記録する
2. **used の vault 走査**: wrapper が run の前に、vault の jrp 以外の `.md` を `<JRP_STORE_DIR>/vault-read/` に rsync する。dataless のファイルは写さず unread: に回す（「python は iCloud に触らない」を保つ）。**走査の範囲を足した日に、その範囲の key を baseline にする**（place ごとに開始日を持つ）。これが無いと、直した日に vault の既存 key がすべて新出になり、used と O2 が水増しされる。この規則があれば、10-20 の初回 scan を急いで止める必要は無い
3. **捨てている数を残し始める**: `Label.first_harvested_at`（上書きしない初回時刻）、writer の呼び出し数（GenerationMeter.requests）、Jev 応答の `usage.input_tokens`、ログの各行への ISO 時刻
4. **DEGRADED の理由を足す**: 0 引用・空ノートを足す。keyless の 429 を本物の障害と分ける
5. **死んだ計器を運用欄から外す**: 上の表。design decision 6・7 に書かれた計器なので、外すかは著者が決める

ダッシュボードの前に: registry・期待値の暦・verify.sh の破壊テスト（「registry の全計器に、故障を 1 つ以上注入して検出する試験がある」を assert する）、RunRecord ノード（予定と実行、要求台帳、Review に出した source、section ごとの rendering、通知の成否）、週次 snapshot、Judgment → Judged の adapter と parity test、論文の key の統一、prefilter の q_i の対応、基準線の切れ目台帳、[n]–(Sk)・数値の照合。

後で: replay harness（scratch。reject の層別標本、キャッシュを通さない再質問の jitter、drift の代わりになる固定 probe）、監視用 judge の実行枠（週数回、usage limit で止まり、再試行しない）。

### 著者の手間

- 最初に 1 回: 下の決定（約 20 分）、`jrp wbr` の v0 の形を 1 回見る
- 毎週: 月曜に WBR ノートの冒頭（結論 3 行・出力・例外）を読む（約 5 分）。返事は要らない。コードの手は agent が task branch → verify → ff-only で進める（boundary.md）。著者の確認が要るのは policy の手（問いの文言・evidence: 行・本文プロンプトの受け入れ）だけ
- ときどき: 問いの文言の見直し。jrp-question は対話型の skill なので、遮断された問いが出たときに著者と行う（月 1 回程度）。除外 folder の一覧の更新（agent が新しい folder を作ったとき）
- ラベル付けと読み比べは増やさない。「開いたか」と judge は、許可が無ければ測らないだけで、手間にはならない

### 著者に決めてほしいこと

1. **パーツの切り直しと出力**: 8 パーツに切り直し、出力を O1・O2 にするか（記入率は降格し、design decision 7 を supersede する）。O2 を design 203 行目「Never measure recall against human citation lists」の例外として、監視にだけ使うか
2. **警報の経路**: macOS 通知（外部送信なし）か、Slack（スマホに届く）か。起動しなかった朝の検知に、外部の dead-man's switch（Healthchecks.io）を足すか
3. **used の vault 走査**: wrapper の rsync で vault-read を作るか。「著者自身の使用」に数える folder はどれか（agent が自動で書く folder・wiki は除く）
4. **監視用 judge**: claude -p を週に数回、監視専用で回してよいか（W の忠実さの標本と OUT の精度標本）。design の非目標「Claude at runtime」（894 行目）と「runs call no Claude」（532 行目）への、監視に限った例外になる
5. **「開いたか」**: Obsidian の最近開いたファイル一覧を、毎朝 stage に写して読んでよいか（jrp ノートの名前と初めて現れた日だけを記録する。主指標にはしない）
6. **死んだ計器の退役**: rule 候補・f・topic・TTD・gold 一致・grounded・claude_calls 0 を今すぐ運用欄から外すか。月曜の drift job を止めるか
7. **掲載上限**（1 ノート 9 件、1 source 2 件）: 著者の読む量の予算として固定し、枠の中の配分だけをレバーにするか
8. **jev-1.14.0 への更新**: 計測の土台（registry と RunRecord）ができてから基準線の切れ目として入れるか、先に入れるか

### 決まったこと（2026-10-20、著者）

- **方向**: 出力を O1・O2 にし、8 パーツ（M・Q・I・S・X・W・D・OUT）で進める。記入率を主指標から外すこと（design decision 7 の supersede）と、O2 を design 203 行目の例外として監視に使うことは、この方向に含まれる。どちらも design の該当節への注記として記録する
- **警報の経路**: Slack（`JRP_SLACK_NOTIFY=1`。harness の `~/.claude/scripts/notify-slack.sh` を通り、送り先は著者自身のチャンネル）。2026-10-20 に `~/.config/jrp/env` へ入れた（元の env は `env.bak-2026-10-20`）。10-21 05:00 の run から届く。今の作りでは run ごとに要約を 1 通送るので、毎朝の 1 通が届かないこと自体が「起動しなかった朝」の印にもなる
- **起動しなかった朝の検知**: watch job も外部の dead-man's switch（Healthchecks.io）も足さない。印は「毎朝の Slack の 1 通が来ないこと」だけ。帰結として、D の主指標（朝の約束）は毎朝の警報にならず、週報が後から数える（分母は暦から作るので、走らなかった朝も分母に入る）。毎朝の警報の ①（06:30 までにノートが無い）は外す
- **監視用 judge**: 回す。ただし claude -p でなく Claude API を使う（著者に毎月 $100 の API クレジットがあり、余っている）。用途は W の忠実さの標本（本番の本文から週 6〜10 節、prose-judge の rubric）と、OUT の精度標本（O1 の論文から週 12 件）。どちらも gate や fit の正解には使わない。既定はモデル Opus 5.5、予算の上限は週 $5（超えたら止めて「未測定」、再試行しない）。見積もりは月 $6〜11（`pipeline/costs.py:17` の単価、as-of 2026-10-19）。jrp の env に `ANTHROPIC_API_KEY` が無いので、著者が 1 行足す。design の非目標「Claude at runtime」（894 行目）と「runs call no Claude」（532 行目）に、監視に限った例外として注記する
- **「開いたか」**: 許可する。ラッパーが毎朝 `.obsidian/workspace.json` と `workspace-mobile.json` を stage に写し、python は jrp ノートの名前と、一覧に初めて現れた日だけを記録する（ほかのファイル名は捨てる）。主指標にはせず、M の著者の信号と、「O1 があるのに開かれないライン」の例外にだけ使う
- **死んだ計器の退役**: 今すぐ外す。外すもの: rule 候補、収束推定 f、topic クラスタ数、Time-to-Discovery、gold 一致と trusted_axes、grounded の平均、support の秒。名前を変えるもの: claude_calls → 書き手の呼び出し数、cost → Jev 推定費用、取得数 → 新規、label N 件 → チェック在庫。`tests/test_quality.py:119-126` と README・how-it-works も同じ変更で直す。月曜 05:30 の drift の launchd job は、replay の固定 probe ができるまで止める
- **掲載上限**: 著者の読む量の予算として固定する（1 ノート 9 件、問いごと `min(5, max(2, 9 // k))`、1 source 2 件）。レバーは枠の中の配分だけ。上限を外したときの増分は、週報に「予算の値段」として参考行で出す
- **jev-1.14.0**: 計測の土台（registry・RunRecord・再計算の adapter・週次 snapshot）ができ、`jev-latest` が 1.14.0 を指してから、ほかの変更と重ならない週に単独で入れる。前後で固定 probe を回し、残すかを決める
- **used の走査先**: 今のまま（対象 repo の graph.jsonld と docs/adr）。vault も記事（zenn-content）も足さない。判断の材料は 2026-10-20 の実測で、vault で論文の key を持つファイルは、ほぼ機械の出力だった（daily-research の旧 pipeline のレポート 668 本・key 6,135、wiki/concept の LLM wiki 74 本・key 477、残りは archive/01_Inbox の 14 本）。帰結は次の 4 つ
  - O2 の分母は月に約 12 key（7 ライン中 4 ラインだけ）。率は出さず k/n を出し、四半期で確定する
  - 本番の vault 経路は stage（jrp のノートだけ）を読むので、空のまま残る。表示と registry には「graph と ADR のみ」と明記し、vault の 0 は宣言済みの縮退として扱う（警報にしない）
  - 2026-10-20 05:00 の初回 scan が、graph 320 key と ADR 3 key を baseline にした。走査先を後から足すときは、place ごとの開始日（足した日に、その場所の既存 key を baseline にする）が必要。足さない限り、この修正は要らない
  - O2 が薄いぶん、OUT の外部評価は当面ほぼ無い。順位付けは O1 と内部の推定に頼ることになる（「リスク」の 1 つ目）

### 見つけたが直していないもの（依頼が「実装の前に相談」のため）

- AGENTS.md の「本番のモデルは claude-code:claude-opus-5-5（2026-10-02 から）」: 10-02 05:00 の run はまだ codex で、claude-code の最初の run は 10-03
- AGENTS.md の「ja = v16 + check10（2026-10-19 から）」: commit は 10-19 18:21 で、本番に効くのは 10-20 の run から
- design の v16 節の「Production fails the cutoff 5-6 of 10」: store の判定では、本番の本文の足切り通過が 5〜6/10
- `note_text.py:306` の「データ不足 (3 run 未満)」: claim 0 件でも同じ文言が出る（f を退役させるなら不要）

### まだ分からないこと

- 監視用 judge（Opus）が、著者の判断の代わりになるか。検証していない仮説。used が 30 件たまったら、used になった論文での yes 率で較正する
- O2 の月の n。7 つの track repo の graph.jsonld と ADR に、過去 30 日で足された arXiv・DOI の key は約 12 個（うち 8 個が authorship-strategy）。jev ラインには対象 repo が無い。n が足りなければ、四半期で集計するか、記事（zenn-content）を走査先に足す
- Jev の同じ state を、キャッシュを通さずに聞き直したときの雑音（jitter）の現在値。2026-10-01 の 2〜3/40 が最後の実測
- jev-1.14.0 で、確率の格子・飽和・較正が変わったか

## 追補: 2026-10-20 の edge・desire の 0 claims（回帰ではない）

as-of 2026-10-20。store を読むだけで漏斗を再生し、コードの視点とデータの視点の反証役が 1 本ずつ確かめた。結論は 2 本とも「回帰ではない」。

- **10-19 の変更は claim の段に触れていない**: 10-17 の run から fa67ed5 までの差分は、`jev/`・`pipeline/units.py`・`store/`・`adapters/`・`nets.py`・`questions/` で 0 行。`run.py` は used rate の +23 行だけ。UsedMark は partition に入るが、claim の経路は isinstance か @id で引くので読まない。config.toml の変更は jev の `daily = true` の 1 行だけ。費用上限も働いていない（cost は $0.02）
- **起きたこと（在庫切れ）**: claim の入口は 3 つある。(a) 当日初めて見た source が Keep になる (b) 古い source が初めて Keep になり、claim_detection が新しく走る (c) 以前 novelty を通ったのに掲載上限で落ちた兄弟の claim。edge では (a)(b) が 10-08 から細り続けた（初出の Keep 対 11→4→3→2→0、新しい accept unit 40→20→12→7→0）。報告数は問いごとの上限 5 に押さえられていたので、10-17 まで減少が見えなかった。10-20 は (a)(b) が 0 になった。Keep 6 対はどれも過去に Keep になった古い source で、claim の 15 件は報告済み（`run.py:936` で除かれる）。残りの 5 件は当日の novelty で全部 reject された。desire は 10-11 から初出の Keep が 0 で、10-14 と 10-17 の claim は 1 本の論文の在庫だった
- **上流の理由**: Jev の較正のずれではない（モデル・bundle は同じ。同じ対の on_topic の差は +0.006）。edge の最大の入口だった S2 recommendation（10-08〜10-14 の初出通過の 57%）が、10-17 と 10-20 に keyless の 429 で 0 件だった。firehose arXiv の 299 件の裾に on_topic ≥ 0.5 が無く（最高 0.46）、keyword は飽和していた（初出 8 件）。火曜 JST（月曜 mailing）は通過率が最も低い 2 run に当たるが、n=2 で断定はできない
- **設計の罠（直していない）**: 掲載上限で落とした claim は、docstring どおり後日また判定される（`run.py:1310-1312`）。しかしその間に同じ source の兄弟が evidence に入るので、novelty の位置が 0.34 を割り、ほぼ必ず落ちる。再判定は実質的な再挑戦になっていない。また `_novel` の除外はライン全体の報告済み claim で引くので、別の問いで報告された claim も除く経路がある（10-20 では 0 件）
- **計測への帰結**: 報告数（O1 の終点）は上限で頭打ちになるので、減少の先行指標にならない。先に動いたのは、初出の Keep 対と新しい accept unit（I・S の主指標）だった。0 claims が DEGRADED にならないこと、S2 の想定内の 429 と本物の障害が同じ「http_status」に見えることも、この朝の無音の原因になった。S2 の API key を入れるかは著者の判断（keyless は今日も 429）

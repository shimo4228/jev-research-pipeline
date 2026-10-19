kind: internal
# 品質計測の実装 plan のための調査: 運用欄の退役と改名・捨てている数・wrapper・週報 `jrp wbr` の土台

as-of 2026-10-20、repo は main（HEAD fa67ed5）。4 人の調査者（A 運用欄の退役と改名 / B 捨てている数を残す / C wrapper と scheduling / D 週報 `jrp wbr` の土台）の報告を、棚卸し（[2026-10-19-quality-metrics-inventory.md](2026-10-19-quality-metrics-inventory.md)）の「決まったこと」「提案」に突き合わせて統合した。この session にシェルが無く、`.claude/verify.sh`・pytest・git・launchctl は走らせていない（読み取りだけ）。行番号は HEAD fa67ed5 のもので、着手時に Grep で引き直す。公開 repo の記録なので vault・store の中身と第三者の名前は書かず、パスは `~/` で書く。

区分の記号: **【決定】** = 棚卸し「決まったこと」（2026-10-20 著者）に書かれたもの。**【提案のみ】** = 提案節にだけあり、決まったことには無い（plan に入れる前に著者へ確認する）。**【発見】** = どちらにも無く、調査で見つかったもの。

## Scope searched

- 調査者の報告にある path:line を、要所で自分で開いて照合した。一致を確認した範囲: `pipeline/meters.py` 全体、`pipeline/run.py` の 186-286・505-530・550-585・660-690・962-985・1140-1290・1336-1470、`model/nodes.py` の 548-584・783-846、`model/jsonld.py` の 98-229、`store/{graph,migrate,schema}.py`、`quality.py` 全体、`reduction/fit.py` の 1-50・125-195、`reduction/used.py` の 1-25・100-220、`jev/core.py` の 400-600、`jev/question_screening.py` 205-301、`jev/question_prefilter.py` 20-101、`jev/source_support.py` の 46-100、`pipeline/costs.py` 全体、`pipeline/nets.py` 375-567、`pipeline/health.py` 全体、`pipeline/runner.py` の 90-220・270-297、`report/vault.py` の 150-255、`report/markdown.py` 155-170、`adapters/collect.py` 全体、`generation/client.py` 258-275 と `generation/prose.py` 285-324、`cli.py` の 88-330、`note_text.py` の 40-160・240-340、`scripts/launchd-jrp.sh` 全体、`launchd/README.md`、`.claude/verify.sh` 45-89、`pyproject.toml` の pytest/pyright 節、tests（`test_quality.py`・`test_nets.py`・`test_note_text.py`・`test_nodes.py`・`test_e2e.py`・`test_parallel.py`・`test_telemetry.py`・`test_migrate.py`・`test_launchd_wrapper.py`・`test_pilot_fixes.py`・`test_ops_tools.py`・`builders.py`・`fakes.py` の該当部）、`docs/design/pipeline-design.md` の 66-115・138-153・296-308・338-349・925-948、README / how-it-works / configuration / samples の該当行。
- 照合でずれていたものは無い。design の行番号（85-93・94-97・200-202・302-304・345・792・934・935・943・947）も一致した。直したのは文言だけ: 調査者 A の「`source_support.check` は `string_match` が常に真」は、正しくは「claim は `source.text` からの逐語の切り出しなので `string_match` が実質つねに真」（`source_support.py:74-79`。偽のときだけ Jev に落ちる）。
- 開かずに調査者の報告をそのまま写したもの: 実機の状態（`launchctl list`、`~/Library/LaunchAgents` の plist が repo の `launchd/*.plist` と同一、`~/.config/jrp/env` のキー名、Obsidian の `workspace*.json` の構造、bash 3.2、`/usr/bin/rsync` が openrsync で `--ignore-missing-args` が無い、shellcheck 0.11.0 の結果）、production の DEGRADED 履歴と claim 0 のノートの集計（B）、store の Label 件数（B）、pydantic-ai 2.47.0 / genai-prices 0.1.7 の記述（D）、docs の細かい行番号の一部。再確認したのは store の Report 件数だけ: `store/lines/*.jsonld` に Report の `"claude_calls"` が 98 件、非 0 は 0 件。
- 以下の項目の節は、変える場所 / 全消費者 / 固定しているテスト / 同じ変更で直す doc / 注意の順に書く。調査者どうしの食い違いは `## Contradictions` に集めた。

## Found

### 0. 横断の前提（どの項目にも効く）

**0.1 store schema と migration の作法**【発見: 全項目の前提】

- 仕組み: `model/jsonld.py:103-105` の `CONTEXT` は `from_document` が完全一致を要求し、変えると store format の変更になる。`store/schema.py:56-92 inspect_document` は、旧 @context に CONTEXT に無い項か値の違う項があれば incompatible（63-73）、全ノードを今の model で validate して 1 件でも落ちたら incompatible（74-90）、それ以外を additive（91-92）と判定する。`store/migrate.py:45-54 prepare_store` は全コマンドの最初に additive を `_rewrite`（39-42）で書き直し、`STORE_MIGRATED` を 1 行出す（`pipeline/runner.py:209-215` が、そのラインのファイル名を含む行だけを note の運用欄に載せる）。incompatible は `StoreSchemaError` で run を止め、`jrp migrate`（`migrate.py:69-89`）は全ラインを `retired/<date>/` に退避する。`Value`（`jsonld.py:207-211`）は `extra="forbid"`。
- 守る規則: (1) 新 field は default 付き。required にすると旧ノードが validate で落ち、全 partition が incompatible になり 05:00 の run が止まる。(2) CONTEXT から項を消さず、値を変えない。`claude_calls` と `gold_agreement` の項は golden `tests/golden/store/old-context-additive.jsonld` が持ち、`tests/test_migrate.py:46-50` が `set(old) < set(CONTEXT)` と値の一致を assert する。(3) model から field を消すときは、旧ノードの key を受け取れる形（default 付きで残す / `exclude=True` / `model_validator(mode="before")` で捨てる）にする。(4) 項をいくつ足しても書き直しは 1 回。commit を分けて deploy すれば、その都度無害な書き直しが 1 回ずつ走り、note の運用欄に「store: lines/x.jsonld を現行 schema に移行 (@context に N 項目を追加)」が出る。(5) `tests/test_jsonld.py:59-64` は model の全 field に CONTEXT の項を要求する（逆向きは見ない）。`tests/test_migrate.py:32` の `ADDED` は `len(CONTEXT) - len(golden の @context)` で計算するので、項を足してもこのテストは赤にならない。
- 既存の golden は RotationCursor 1 件と Judgment 1 件だけで、Report・Operations・Label を固定したものが無い。本番の Report 98 件が新 model で通ることを機械が保証しない。提案（私の判断）: model を変える前に、HEAD の build が書いた Report と Label を builders の合成データから `to_document` で書き出して golden に足し、「旧 Report が新 model で validate し、書き直しても落ちない」を pin する。`tests/golden/store/README.md` の「置き換えは store format の変更を宣言したときだけ」は置き換えの規則で、追加は当たらない。第三者の文は含めない。

**0.2 rollback の不能点**【発見】

- additive な書き直しが 1 度走ると、store の @context が新しい項を持つ。その後に旧 build へ戻すと、旧 CONTEXT から見て新しい項は「削除された項」になり（`schema.py:63-65`）incompatible で全コマンドが止まる。`jrp migrate` は退避（削除でない）で、`retired/` から戻せる。`store/` は git 管理外で履歴が無い（B）。plan に「deploy 前の store の退避」を入れる。退避の実行は store への操作なので、著者に渡すか明示の確認を取る。revert する場合は新しい項を CONTEXT に残す規則にしてもよい。

**0.3 deploy の窓**

- 本番の plist は checkout の `scripts/launchd-jrp.sh` を直接呼ぶ（C）。main に入った版が次の 05:00 から効き、再 install は要らない。bash は script を逐次読むので、run 中（05:00〜約 05:30）に wrapper を in-place で書き換えると走行中の run を壊しうる（C の推測、未検証）。task branch からの ff-only は git が新しいファイルを書くので安全なはずだが、取り込みは 05:00〜06:00 を外す。
- `uv run --frozen` で動くので、依存を足す変更（`anthropic` の直接 import など）は lockfile も同じ commit に入れる。deptry が DEP003 を出す（D）。

**0.4 共有ファイル（順序を決めないと衝突する所）**

- `pipeline/run.py` の `_operations`（1215-1283）と `_discovery_lines`（1152-1187）、`model/nodes.py` の `Operations`（562-578）と `AxisMeter`（553-559）、`note_text.py`、`tests/builders.py:101-109`、`model/jsonld.py` の CONTEXT。A・B・D の項目が全部ここに当たる。
- wrapper は `scripts/launchd-jrp.sh` と `src/jev_research_pipeline/scheduling/launchd-jrp.sh` の 2 本が同文でなければならない（`tests/test_ops_tools.py:238-243`）。`jrp schedule install` は wrapper が無いときしか書かない（`scheduling/__init__.py:50-73`）ので、他環境の写しには届かない。著者の plist は repo の script を指すので問題ない。

**0.5 決定論のテスト**

- `tests/test_parallel.py:79-103` は逐次（limit 1）と並列（limit 12）で note・store のバイト列・運用欄の行が一致することを見る。`_timed`（64-67）が除くのは行頭「段の所要:」と " prose 第" を含む行だけ。新しく store と運用欄に入る値（writer の呼び出し数・Jev token・`first_harvested_at`）はこの一致に入る。時刻は固定の `b.T0` を使い、cassette 再生で値が決定的かを最初のテストで確かめる。
- `tests/test_note_text.py:30-33` は全 `Msg` の placeholder が ja・en・zh で一致することを、36-38 は en 列に CJK が無いことを、87-100 は English run の運用欄に日本語が混ざらないことを見る。運用欄に日本語の接頭辞を足すときは `Msg` にする。今の `"claude_calls: 0"`（`run.py:1241`）と `f"cost: …"`（1242）と `meters.py:135` の `f"openalex credit: …"` は英語のリテラルなので、このテストを通っているだけ。

### 1. 運用欄から外す【決定】

**1.1 rule 候補**

- 変える場所: `pipeline/run.py:1260`（`*rule_candidates(log, RuleConfig(lang=lang), today=…)` を運用欄へ展開）、`run.py:103`（import）、`run.py:1216-1218`（`DecisionLog.from_nodes`。使い道は 1.5 の `agreement` とこの行だけ）、`reduction/rules.py`（1-104）、`reduction/__init__.py:7,10,12,15`（export）、`note_text.py:319`（節コメント）と `331-335`（`RULE_CANDIDATE`）。
- 全消費者: `run.py:1260` が唯一の呼び出し元（src を grep: `rule_candidates` / `RuleConfig` は `reduction/` の中と `run.py` だけ）。tests は `tests/test_reduction.py` の import（23-28）と 193-217・266-272。`docs/samples/agent-memory.{ja,en,zh}.md` の運用欄（ja:91-94 / en:88-90 / zh:90-93）。`reduction/used.py:4-5` の docstring（「rule candidates は UsedMark を読まない」）。
- 固定しているテスト: `test_reduction.py:196-204 test_rule_candidate_found_for_a_code_feature`、`207-213 …_respect_min_n`、`216-217 test_rule_config_defaults`、`266-272 test_rule_needs_to_beat_the_complement`。`test_note_text.py:30-33`（`RULE_CANDIDATE` も対象）。
- 同じ変更で直す doc: `docs/design/pipeline-design.md:85-93`（decision 6 ③ rule promotion = proposal only）に退役の注記、`:934`（build 手順 ③ proposal detector）、`:792`（Msg の列挙）、`:345` と `reduction/used.py:4-5`（「UsedMark を読まないもの」の列挙）、samples 3 本。`docs/plans/research/2026-10-19-used-rate-label.md` と `docs/plans/used-rate-label.html` は経緯の記録なので直さない。
- 注意: 呼び出しを外すと `rules.py` は tests からしか使われない死にコードになる。消すか残すかは plan で決める（消すなら decision 6 ③ の supersede を design に注記する。refactor-clean の範囲）。副作用が 1 つある。12 KB の枠（`run.py:361 NOTE_MAX_BYTES=12_000`、`_fitted` 1448-1467）から rule の行が消えるので、Review が `REVIEW_MAX`（`run.py:368`、10）まで残りやすくなる。A の棚卸しは 70〜100 件が押し出されていたと推定した（私は再計算していない）。

**1.2 収束推定 f（convergence）**

- 変える場所: `pipeline/meters.py:26`（`MIN_POINTS`）・`57-73`（`convergence`、ceiling = 最新累計 × 1.2）・`129`（`CONVERGENCE` / `CONVERGENCE_NONE` の行）・`1-15`（module docstring）。`run.py:1163-1174`（`reports`・`cumulative`・`running` は f だけのために作っている）と `1183`。`note_text.py:304-309`（`CONVERGENCE`・`CONVERGENCE_NONE`）。
- 全消費者: `run.py:1183` だけ。`tests/test_nets.py:574-579` と `582-595`。samples 3 本（ja:88 / en:85 / zh:87）。
- 固定しているテスト: `test_nets.py:574-579 test_convergence_needs_enough_runs_and_rises_with_saturation`、`582-595 test_consecutive_irrelevant_is_not_reported_as_convergence`。後者は「収束推定 f: データ不足」・「連続」の不在・topic の「減少」を同じテストで assert し、design の制約「n 回連続の無関係は収束の信号ではない」（Repke 2026、`pipeline-design.md:303`）を固定する唯一のテスト。f と topic の両方を消すと主題を失う。「連続」の行が無いという assert を `meters.lines` の残りに当てて残すか、消して design 302-304 に注記するかを plan で決める。
- 同じ変更で直す doc: `pipeline-design.md:200-202`（Discovery の meters 6）・`:302-304`（Meters の段落）、samples 3 本。
- 注意: `note_text.py:306` の「データ不足 (3 run 未満)」は claim 0 件の分岐でも出る誤文言（inventory「見つけたが直していないもの」）。f の退役で一緒に消える。

**1.3 topic クラスタ数**

- 変える場所: `meters.py:52-54`（`topic_clusters`）・`116-124`（「前回」「減少」の付記）・`128`・`21`（`openalex` の import は `topic_of` のためだけ）。`run.py:1161-1162`（`today` / `before`。`fetched_at` の日付で分ける）と `1181-1182`。`note_text.py:299-303`（`TOPIC_CLUSTERS`・`CLUSTERS_BEFORE`・`CLUSTERS_FEWER`）。
- 全消費者: `run.py:1181-1182` だけ。`openalex.topic_of`（`adapters/openalex.py:158`）は `run.py:685 _topics`（exploration net の種）と `tests/test_nets.py:224` も使うので消さない。
- 固定しているテスト: `test_nets.py:569-571 test_topic_clusters_count_distinct_topics`、`582-595`（「減少」の assert）。`test_nets.py:541-557` の `NET_TOPICS` と `_claim` helper は `share_per_net` と TTD のテストも使うので helper は残す。
- 同じ変更で直す doc: **README.md:78-80**（「every note counts how many distinct subject areas its kept papers cover, so any drift … shows up as a falling number」）、**README.ja.md:50**（「ノートは毎回、残した論文が何種類の分野にまたがるかを数える…」）、`docs/how-it-works.md:114-116`（「a falling topic count is the convergence alarm」）、`pipeline-design.md:200-202,302`、samples 3 本（ja:87 / en:84 / zh:86）。決定は README・how-it-works も同じ変更で直すとしている。
- 注意: README の「偏りは数が減って分かる」はこの計器を根拠にしていた。代わりの計器（週報の「反復と新規性」）はまだ無いので、README の文は約束を外す形で書き直すことになる（A の推測）。README の人間向けの文は readme-writer の範囲。

**1.4 Time-to-Discovery（TTD）**

- 変える場所: `meters.py:76-98`（`time_to_discovery`。`label.harvested_at − source.fetched_at`で、両端とも上書きされる時刻）・`130-132`。`run.py:1175-1177`（`claims` と `labels` の map は TTD のためだけ）と `1185`。`note_text.py:310-317`。
- 全消費者: `run.py:1185` だけ。`tests/test_nets.py:598-631`。samples 3 本（ja:89 / en:86 / zh:88）。`reduction/used.py:4-5` と `pipeline-design.md:345` の列挙。
- 固定しているテスト: `test_nets.py:598-631 test_time_to_discovery_is_the_median_over_ticked_sources`。
- 同じ変更で直す doc: `pipeline-design.md:302`（Meters: TTD per ⭕ paper）・`:345` と `used.py:4-5`、samples 3 本。
- 注意: `Label.harvested_at` と `SourceItem.fetched_at` は schema に残す（harvest・fill rate・`_discovery_lines` の today/before が読む）。置き換え（初取得から初掲載までの日数）は週報の診断で、この変更には入らない。`Label.first_harvested_at` は 4.1。

**1.5 rubric の gold 一致と `trusted_axes`（`jrp fit` への影響を含む）**

- 変える場所: `quality.py:1-11`（docstring）・`47-49`（`AGREEMENT_FLOOR=0.7`・`MIN_LABELS=10`）・`52-60`（`AxisAgreement`）・`77-92`（`agreement`）・`95-105`（`trusted_axes`）・`108-118`（`axis_meters`。`agreements` を受けて `gold_agreement` を埋める）。`run.py:100`（import）・`1219-1220`・`1251-1253`（gold の表示）。`note_text.py:133-137`（`RUBRIC_AXIS` の `{gold}`）と `138`（`NOT_MEASURED`。使うのは `run.py:1253` だけ）。`cli.py:69` の import と `236-251 _fit`（240 で `trusted_axes(agreement(...))`、242 で `fit_thresholds(trusted=)`）。`model/nodes.py:553-559`（`AxisMeter.gold_agreement`）。`reduction/fit.py:8-10`・`35 SILVER_WEIGHT`・`130-143 _silver`・`152-165`・`177-180`・`204 n_silver`。
- 全消費者: `run.py` と `cli.py` だけ（src を grep）。`tests/builders.py:107`、`tests/test_nodes.py:522-534`（`gold_agreement=None` を含む dict）・`532-534`、samples 3 本（ja:81-84 / en:78-81 / zh:80-83）、store の Report 98 件の `operations.rubric[].gold_agreement`、`used.py:4` と design 345 の列挙。
- 固定しているテスト: `tests/test_quality.py:88-101,103-106`（agreement）、`109-116 test_trusted_axes_need_the_floor_and_enough_labels`、**`119-127 test_axis_meters_feed_operations`（126 で `gold_agreement == 1.0`。正例だけの縮退を期待値にしている。決定が名指しした 119-126 はこれ）**、`258-271`（agreement の review fix 2 本）、`274-276`（`gold_agreement is None`）。`fit` の silver 経路を見るテストは無い（`trusted`・`silver`・`n_silver` の grep で tests に該当なし）。
- 同じ変更で直す doc: `pipeline-design.md:77-84`（decision 5: rubric を gold で検証し、通った軸を silver にする）に supersede の注記、`:97`（decision 7 の rubric-vs-gold agreement）、`:930-933`（build 手順 8・9）、`quality.py` と `fit.py` の docstring、samples 3 本。
- 注意（store）: `AxisMeter.gold_agreement` の field を消すと既存 Report が全件 incompatible になる（0.1）。field は default `None` で残すか `Field(default=None, exclude=True)` にし、CONTEXT の `gold_agreement` の項も残す。`test_nodes.py:522-534` と `AxisMeter(…, gold_agreement=None)` はそのまま通る。
- 注意（fit）: `trusted_axes` をやめて `cli._fit` が `trusted` を渡さなくなると、`fit_thresholds` の `trusted` は既定 `()`、`_silver` は `{}` を返し、`SILVER_WEIGHT` と `n_silver` は死にコードになる（これは decision 5 の silver label の退役でもある）。`jrp fit` は本番で一度も走っておらず、gold が 1 クラスなので全 threshold が skip になる（inventory）ため、今の挙動の差は 0。最小の変更は「`trusted` を渡さない」だけで、`_silver` / `n_silver` の削除は `Proposal` の出力形（`fit.py:125,204`）を変えるので別 commit に分ける（tests に `n_silver` の参照は無い）。`rubric_claim` の Judgment は Jev への問いとして残る（`rubric_claim.decision` と fit の SPECS が読む）。

**1.6 rubric grounded の平均の行**

- 変える場所: `run.py:1246-1258`（`rubric_claim.AXES` の順に 1 軸 1 行。grounded が先頭）。`quality.py:108-118`。`jev/rubric_claim.py:20` の `AXES`。`note_text.py:133-141`。
- 全消費者: `Report.operations.rubric`（`nodes.py:571`）に 4 軸とも保存され、src で読み戻すものは無い。`tests/test_quality.py:119-127`・`274-276`、`builders.py:107`、`test_nodes.py:522-534`、samples（ja:81 / en:78 / zh:80）。
- 固定しているテスト: 上と同じ。
- 同じ変更で直す doc: samples 3 本、`pipeline-design.md:83-84`（「Rubric also drives the daily quality line」）。
- 注意: grounded は `rubric_claim.decision` の門（`rubric_claim.py:126-127`、全軸 ≥ 0.5）と fit の SPECS に残る。外すのは表示の行だけにする。やり方は 2 つ。(a) `run.py:1246-1258` の表示で grounded を飛ばし、store には 4 軸とも残す。(b) `axis_meters` から grounded を外す。どちらも store と互換（rubric の tuple は長さを固定せず、validator は `nodes.py:575-578 _axes_unique` だけ）。gold を外した後の `RUBRIC_AXIS` は「rubric {axis}: 平均 {mean}」になり placeholder が変わるので、3 言語を揃えないと `test_note_text.py:30-33` が落ちる。`NOT_MEASURED` は使う所が無くなる。

**1.7 support の秒（段の所要）**

- 変える場所: `run.py:516-522 _stage`（OTel span `jrp.stage.<name>` と `st.seconds` の両方を作る）、`run.py:1303`（`with self._stage("support", …)`）、`run.py:1277-1279`（`st.seconds` を挿入順に「name Ns」で並べる）、`note_text.py:156 STAGE_TIMES`。stage 名の一覧: `fetch`(732)・`prefilter`(739)・`queries`(1288)・`triage`(1295)・`screen`(1297)・`claims`(1299)・`novelty`(1301)・`support`(1303)・`canary`(1354)・`sections`(1357)・`rubric`(1378)。
- 全消費者: `tests/test_parallel.py:64-67 _timed`（行頭「段の所要:」で除く）、`tests/test_telemetry.py:38-43`（span 名 `jrp.stage.queries / fetch / claims / sections` を assert。support・rubric は見ない）、`docs/observability.md:30`（`jrp.stage.*`）、samples（ja:96 / en:93 / zh:96）。
- 同じ変更で直す doc: samples 3 本。span 名を変える場合だけ `observability.md:30`。
- 注意: 外し方は 2 つ。(a) 1277-1279 の join で `support` を飛ばす（span `jrp.stage.support` は残る）。(b) 1303 の `_stage` の包みを外す（span も消える。テストは無い）。claim は `source.text` からの逐語の切り出しなので `source_support.check` の `string_match` は実質つねに真で Jev を呼ばず（`jev/source_support.py:74-79`）、秒が 0 になる。`_supported`（`run.py:964-984`）自体は残る。`rubric` の秒は本物の短さなので残す（inventory）。

### 2. 運用欄の改名【決定】

`claude_calls → 書き手の呼び出し数` は schema と捨てている数に関わるので 4.2 に書く。

**2.1 cost 行 → 「Jev 推定費用」**

- 変える場所: `run.py:1242`（`f"cost: ${cost:.4f}" + self._cost_caveats()`。接頭辞は英語のリテラル）、`1189-1196 _cost_caveats`（Jev 単価未設定 / サブスク 0 計上 / 生成単価未設定）、`1221`、`1381-1384`（OTel `jrp.cost_usd`）。`pipeline/costs.py:40-57 Budget.cost`（Jev 質問数 × `JRP_JEV_USD_PER_QUESTION` + 従量の書き手の token × `PRICES`、サブスクは 0）。`note_text.py:96-102`。
- 全消費者: `tests/test_e2e.py:146-161`（`cost_usd == jev_questions × 0.001`、caveat「(生成はサブスクリプション定額で 0 計上)」）、`tests/test_telemetry.py:53`、`builders.py:106`、samples（ja:78 / en:75 / zh:77）、費用の cap（`JRP_COST_CAP_USD`、`costs.py:53-57`）は同じ `Budget.cost` を読む。
- 同じ変更で直す doc: `docs/how-it-works.md:153-166`（163「the Jev price set in my env for the cost line」）、`docs/configuration.md:40-41`、`pipeline-design.md:586-588`（Cost: the cost line says so）と `:144-145`（「単価未設定」）、samples。
- 注意: 「生成は含まない」が正しいのは `writer.spec.subscription` のとき（`openai-codex:`・`claude-code:`）だけ。`anthropic:` と `dashscope:` の書き手では `Budget.cost` が生成の token 代を含み（`costs.py:46-51`）、cap もその和にかかる（`configuration.md:40` に明記）。文言は `writer.spec.subscription` で分岐させるか、「推定費用（Jev 仮定単価 + 従量の書き手。サブスクの書き手は 0）」と両方を言う形にする。決定の文面「Jev 推定費用（仮定単価、生成は含まない）」を無条件に固定すると従量の書き手で嘘になる。新しい日本語の接頭辞は `Msg` にする（0.5）。`cost_usd` の field・cap・OTel 属性名は変えないので schema の変更は無い。

**2.2 net 取得数 → 「新規」**【決定の文言と実装が合わない】

- 変える場所: `note_text.py:293-295 NET_SOURCES`（「net 取得数: {counts}」）、`meters.py:113-114,126`、`pipeline/nets.py:556-564 per_net`、`run.py:673,1179`。
- 全消費者: `meters.lines` だけ。samples（ja:85 / en:82 / zh:84）。文言を固定するテストは無い（`test_nets.py:582-595` は f・減少・連続しか見ない）。`300` は firehose の上限 `firehose_max` の飽和。
- 注意（発見）: `nets.py:530` の `seen` は `fetch_nets` の呼び出しごとに新しい run 内の dedupe で、`per_net` は run 内で先に出ていない @id の数（firehose は `_capped`（462-476）の後）。`adapters/collect.py:39-50` は前の日から store にある source も毎回返す（cache hit は `done` の全 id を、miss は `adapter.fetch` の全件を返す）ので、**この数は store に対する新規ではない**。「新規」と書くと新しい誤ラベルになる（inventory は「取得数 → 新規（dedupe・上限の後）」、決まったことは「取得数 → 新規」）。選択肢: 文言を「取得（run 内の重複除去・firehose 上限の後）」のように範囲を言う / store に対する新規数を別に数える（今は無い。`_keep_first_net`（`collect.py:53-65`）が `partition.load()` で既知の source を引いているので、そこで数えられるが値が変わるのでテストを足す）。どちらにするか plan で決める。

**2.3 harvest の label N 件 → 「チェック在庫」**【決定の文言と実装が合わない】

- 変える場所: `note_text.py:244-248 HARVEST`、`pipeline/runner.py:97-132 harvest_line`（131 で `t.HARVEST(lang, labels=labels, withdrawn=withdrawn)`。`labels += len(result.labels)` は毎 tick、そのラインの全ノートを読み直した数）。
- 全消費者: `tests/test_e2e.py:105`（`"harvest: label 1 件 / 取り消し 0 件"`）、`tests/test_report.py:501,505`、samples（ja:97 / en:94 / zh:97）。`runner.py:209-218` は run しないラインも収穫するが、行が載るのは、その日に run したラインのノートだけ。
- 固定しているテスト: `test_e2e.py:99-105`、`test_report.py:470-506`（qday 1 個の `[x]` が「label 3 件」になる）。
- 同じ変更で直す doc: samples 3 本。
- 注意（発見）: 数えているのはチェックボックスでなく `Label` node。qday の `[x]` は、その日に引用した claim と source へ伝播する（`vault.py:185-189`）ので 1 チェックが `1 + claims + sources` 件の Label になる。「チェック在庫」と書くとチェックの数と読まれる。「label 在庫（累計、qday の伝播を含む）」のように書く。「取り消し」の部分と値は変えない。

### 3. 提案節にだけあり、決まったことには無いもの【提案のみ】

plan に入れるなら著者に確認する。調査者が実装箇所まで調べてある。

- **日次の net 採用率を週次の歩留まり表へ移す**（外す側）: A は残す前提で調べた。`meters.py:37-49 share_per_net`・`101-136 lines`、`run.py:1152-1187`、`note_text.py:296-298 NET_SHARES`、`tests/test_nets.py:560-566`、`how-it-works.md:31-32,53,114-115`。f・topic・TTD を外すと `_discovery_lines` で要るのは `per_net` と share のための `units`・`sources`・`accepted` だけで、`reports`・`cumulative`・`running`・`claims`・`labels`・`today`・`before` は消える。`meters.lines` の keyword 引数（`clusters`・`previous_clusters`・`fit`・`ttd`）が変わるので `test_nets.py:585-592` の呼び出しも直す。`meters.py:1-15` の docstring は 3 計器のうち 2 つと f が消えるので書き直す。
- **openalex credit → 「tick 累計の途中値」**: `meters.py:134-135`（英語のリテラル。0 のとき行を出さない分岐あり）、`nets.py:565 outcome.openalex_credits = budget.spent`（`DayBudget` は tick の全ラインで共有、`runner.py:201`）、`run.py:319,674,1184`。ラインは並列に走る（`runner.py:276`）ので、値はそのラインの fetch が終わった時点の tick 累計。値を見るテストは `test_nets.py:271,370`、文言を見るテストは無い。日本語にするなら `Msg` を新設する（0.5）。samples（ja:90 / en:87 / zh:89）。
- **question_movement の「動いた」→「claim があった」、frontmatter の「n 問い」**: `note_text.py:52 TOPIC`（「{line} — {n} 問い」）、`report/markdown.py:159-170 _frontmatter`（160 で `n=len(sections)`）、`note_text.py:70-72 NOTHING_MOVED`。n は open な問いの数でなく、その日に節ができた問い（claim があり `question_movement` が accept した問い、`run.py:1357-1377`）の数。open な問いの数は運用欄の `OPEN_QUESTIONS`（`run.py:1245`）が別に出す。問いが 0 の日も「0 問い」と出る。`test_report.py:144-150` は frontmatter の key の並びだけを見る。`topic` は daily-research の key なので key 名は変えない。Obsidian 側が frontmatter の topic を読むかは不明（A の推測、harness の x-draft・wiki-query は読まない）。samples の 6 行目。
- **queries の秒の名前**: `run.py:552-583 _queries` は 582 の `self.partition.put(authored)` が store ファイル全体を書き直す（`store/graph.py:55-61`）ので、秒は store が大きいほど伸びる。名前を「queries（store 書き込み）」のように測るものを言う形にする案（A）。span 名は `test_telemetry.py:39` が固定しているので、表示だけ変えて span 名は変えない。`test_parallel.py:67 _timed` は行頭「段の所要:」に依存する。

### 4. 捨てている数を残す【決定: 前提の修正 3】

**4.1 `Label.first_harvested_at`（上書きしない初回の収穫時刻）**

- 変える場所: `model/nodes.py:787-843 Label`（field は `subject`・`report`・`verdict`・`provenance`・`harvested_at`。`id_for` は (subject, report) だけ。docstring 794 は「re-harvesting overwrites」）。`model/jsonld.py:166-170`（label の項。`first_harvested_at` の項がここに要る）。`pipeline/runner.py:97-132 harvest_line`（107 で `nodes = part.load()` を既に持つ。125 `part.put(result.labels)` が upsert で Label を丸ごと上書き、129 `part.remove(result.cleared)` が空欄の Label を消す）。`report/vault.py:158-195 _labels`（`Label.new(..., harvested_at=now)`）。`store/graph.py:55-61 Partition.put`（field 単位の merge は無い）。
- 全消費者: `meters.py:76-98`（TTD。1.4 で退役）、`reduction/log.py:103-111 DecisionLog.gold`（`harvested_at` で sort、claim ごとに最後の Label。今は全 Label が同じ時刻で同点）、`run.py:585-600 _positives_and_negatives`（verdict だけ）、`run.py:1590-1606 fill_rate_previous`、`quality.agreement` / `fit` / `cases`（`gold()` 経由）。将来の consumer: 週報の「今週の新しいチェック数」（inventory 203 行）。store の実測（B, 2026-10-20）: Label 171 件で全件 `provenance=question_day`、`harvested_at` は全件が同じ朝の時刻。
- 固定しているテスト: `tests/test_nodes.py:440-483`（`Label.new`）、`tests/builders.py:139-146`・`192-209`、`tests/test_jsonld.py:59-64,81-87`、`tests/test_report.py:285-340,470-506`、`tests/test_e2e.py:90-107`、`tests/test_nets.py:608-627`（`harvested_at` をずらして TTD を作る）ほか `test_question_flow.py:152,180`・`test_used.py:276,322`・`test_reduction.py:76-81,132`・`test_quality.py:76-81`。**初回時刻の意味を固定するテストは無い。足すもの**: 再収穫で値が変わらない / 旧 Label（field 無し）は `None` のまま / 空欄に戻して付け直すと新しい時刻になる。
- 同じ変更で直す doc: `nodes.py:788-795` の docstring、`report/vault.py:1-17`、`runner.py:104-105`、`pipeline-design.md` の Labels（68-80）・152・267-269 のどれかに注記。
- 注意: `first_harvested_at: AwareDatetime | None = None` にして CONTEXT に 1 項（`_typed("firstHarvestedAt", "dateTime")`）を足す。持ち越しの規則が肝: 前の Label があれば、その `first_harvested_at` を**値が `None` でも**引き継ぎ、前が無いときだけ `now` を入れる。`None` を `now` で埋めると、deploy の朝に旧い 29 個のチェックが全部「今週の新規」に化ける。旧 Label の本当の初回は store から出せず、`None`（計測開始より前）が正直な扱い。置き場は `harvest_line` が持つ `nodes` から `model_copy(update=…)` で持ち越すのが局所的（`graph.py` の `put` は汎用の upsert のまま）。決めること: (a) `[x]` を `[-]` に変えたときは @id が変わらず初回の時刻が残る（意味は「何かの tick が最初に見えた時刻」）。(b) 新しいチェック数を数える単位は `question_day` の QuestionLog を subject とする Label だけにする。伝播した分まで数えると 1 チェックが `1 + claims + sources` 倍に膨らむ。収穫は 05:00 の tick にしか走らないので、実際の tick から最大約 24 時間遅れる。`harvested_at` の意味（最後の収穫）は変えない。

**4.2 書き手の呼び出し数（`claude_calls: Literal[0]` を外す）**

- 変える場所: `model/nodes.py:568-569`（`claude_calls: Literal[0]` と docstring「Non-goal: Claude at runtime. The meter exists to prove it stays 0.」）、`563` の docstring。`model/jsonld.py:190`（`claude_calls` → `claudeCalls` xsd:integer）。`run.py:1227`（`claude_calls=0`）と `1241`（リテラル `"claude_calls: 0"`）。値の出所は `generation/client.py:262-274 GenerationMeter.requests`（検証の再試行・書き直し・self-check を含む完了した request）で、`run.py:505` の `self.meters = {writer.spec: GenerationMeter()}`（LineRun ごと）。`generation/prose.py:291-316` は `finally: meter.add(usage)` で失敗した run も足す。値の式は `sum(m.requests for m in self.meters.values())`（`run.py:1225-1226` の token と同じ形）。
- 全消費者: `tests/test_e2e.py:78`（`"claude_calls: 0" in text`）・`83`、`tests/test_nodes.py:515-519 test_claude_calls_must_be_zero`（1 を拒否する。変更と正反対）、`tests/builders.py:105`、`tests/test_report.py:82`（入力データの文字列。直さなくても通る）、`meter.requests` を見る `test_claude_code.py:117`・`test_codex.py:140`・`test_anthropic.py:93`・`test_prose.py:55`、`test_parallel.py:79-103`、samples（ja:77 / en:74 / zh:76。claude-code の書き手の見本なのに 0 と出ている）、store の Report 98 件（全件 0）、golden の context の項。将来の consumer: 毎朝の警報 ⑥「生成 token > 0 なのに writer の呼び出し 0」（inventory 229 行）。
- 固定しているテスト: `test_nodes.py:515-519`、`test_e2e.py:68-83`、`test_note_text.py:87-100`。
- 同じ変更で直す doc: `pipeline-design.md:94-97`（decision 7「Claude calls (must be 0)」）・`:489-492`（「"Claude calls = 0" and the non-goal "Claude at runtime" hold」）・`:941-943`（Verification）・`:598-603`（prose site だけを例外にした節）、`nodes.py:563,569` の docstring、`client.py:262-264` の docstring（完了した request を数え、失敗した試行は入らない）、samples。`pipeline-design.md:532,894` の非目標は監視用 judge（8.10）の別項目。
- 注意: 新 field を足す案が A（案 (b)）と B で一致し、(a) key を残して `NonNegInt` に広げる案は採らない。(a) は 10-03〜10-20 の `claude-code` の run の 0 が「未計測」なのに 0 に見え、`codex` / `dashscope` の書き手でも key が claude のままで嘘になる。(c) CONTEXT の項を消す案は不可（incompatible で golden が赤）。**私の整理**: `writer_calls: NonNegInt | None = None`（`None` = 計測開始より前の旧 Report）+ CONTEXT に `writerCalls` xsd:integer を足し、旧 `claude_calls` は CONTEXT の項を残したうえで、field を default 付き + `exclude=True` にするか before-validator で捨てる（Contradictions）。`test_nodes.py:515-519` は書き換えるか消す。表示は `Msg`（ja・en・zh）にし、`run.py:1241` のリテラルを置き換える。`tests/builders.py:105` の `Operations(claude_calls=0)` は pyright strict（`pyproject.toml:124-127`）に引っかかるので同じ変更で直す。値の意味は「完了した model request」。timeout や usage limit で例外になった試行は `requests` に入らない（D の読みでは pydantic-ai 2.47.0 の `_agent_graph.py:1544-1558` は model が返ってから `record_request` する。推測）。試行の数は `LineHealth.drafts`（`health.py:27`）が別に持つので「呼び出し n（失敗 m）」と併記すると矛盾の検知（⑥）が素直になる。

**4.3 Jev の usage token**

- 変える場所: `jev/core.py:405-421 JevClient`（`questions_asked`（414）と `retries`（415）だけを数える。token の counter は無い）、`550-589 _send_once`（561 で `run = await agent.run(…)`、578 で `response: ModelResponse = run.response`、585-589 で `_Sent(output, model, details)` を返す。usage はここで捨てている）。pydantic-ai 側は `pydantic_ai/models/typesafe.py:633-637 _request_usage`（SDK の `usage.input_tokens / output_tokens` を `None` なら 0 にして `RequestUsage` にする。`response.usage` に入る）。`run.py:1215-1231 _operations` に `Operations(jev_input_tokens=…, jev_output_tokens=…)` を足す。`StoredJev`（`run.py:201`）は `JevClient` の subclass なので counter は自動で見える。cache hit と in-flight の合流は request を送らないので token 0。
- 全消費者: `questions_asked` を読む所: `run.py:525`・`1221`・`1224`・`1383-1385`。`scripts/slot_bleed.py:43` が `JevClient` を直接作る（足すだけなら影響なし）。`tests/fakes.py:96-101` の偽 Jev は毎回 `usage {"input_tokens": 100, "output_tokens": 5}` を返す。
- 固定しているテスト: `tests/test_jev_core.py:182,205`（`questions_asked == 3`）、`tests/test_jev_batch.py:78,134-147`（`retries == 1`）、`tests/test_e2e.py:82,142`（同じ日の再 run は `jev_questions == 0`。token も 0 になることを足すとよい）、`tests/test_jsonld.py:59-64`。
- 同じ変更で直す doc: `pipeline-design.md:449-454`（「Packet discrepancy: Jev is priced per input token … Review-when: the first live batched run's usage.input_tokens is in hand」。usage が残れば Review-when を消化できる）、`costs.py:1-8` の docstring、`how-it-works.md:150-166`、`observability.md:30-31`（span の属性）、`pipeline-design.md:94-97`。
- 注意: `Operations` に `jev_input_tokens: NonNegInt | None = None` と `jev_output_tokens: NonNegInt | None = None`（`None` = 旧 Report）を足し、CONTEXT に 2 項（`generation_input_tokens` の命名に合わせる）。counter は成功した応答ごとに足す。`model_mismatch`（579-584）と `_judged` の `bad_answer` は応答がもう来ていて課金もされている（推測）ので、この 2 つの判定より前に数える。失敗の経路（562-577）には応答が無いので token も無い。SDK の内部再試行（408/429/5xx で 2 回、`core.py:60-61`）は見えない。`JevClient` は LineRun ごとなので、値はラインごとの合計。費用の式（`costs.py` の Jev 単価）を実 token に切り替えるかは別の決定（価格 $42/10 億入力 token は README の as-of 2026-10-07、失効条件は TypeSafe の価格改定。jev-1.14.0 では応答の形が変わりうる）。

**4.4 ログの時刻**

- 変える場所: `scripts/launchd-jrp.sh` の `notify()`（42-52）・`die()`（54-58）・doctor の `cat "$DOCTOR_OUT"`（154）・`echo "vault ← …"`（177）。どの行にも時刻が無く、開始と終了の行も無い。python の出力は `limited()`（64-91）経由でログの fd に直接出る。`cli.py:144-176 _run`（159 で `now=datetime.now().astimezone()` をその場で作り変数に残さない。173-175 で `run_summary` を stdout と `notify` に出す）。`pipeline/runner.py:280-296 run_summary`。`init.py:196` の `try_line` も `run_summary` を使う。
- 全消費者: `~/Library/Logs/jrp-run.log`（人と棚卸しが読む。ログの行を機械で parse する script は repo にも harness 側にも無い — C）。Slack の本文は同じ body（`pipeline/notify.py` → `~/.claude/scripts/notify-slack.sh`）。
- 固定しているテスト: `tests/test_launchd_wrapper.py`（stdout と stderr を別々に部分一致と index で見る: 73-81、161「uv not found」in `out.stderr`、188。notify は `FAKE_NOTIFY` の `title|body`）、`tests/test_run_health.py:120-167`（`run_summary` の title と body を厳密に固定: 123 の `body == "2026-09-22 2026-09-22_jrp_akc: 3 claims"`、133-139 は行の位置）、`tests/test_ops_tools.py:135,177-178,238-243`、`tests/test_init.py:63`。
- 同じ変更で直す doc: `scripts/launchd-jrp.sh:18-25`（ヘッダ）と写し、`launchd/README.md` の wrapper が log に書くものの段落、`docs/scheduling.md:22-27,61-72`、`docs/configuration.md:52`、README.md / README.ja.md の通知の中身の一覧（時刻を足すなら中身が増える）、`.claude/verify.md:28`（shell は gate の外。変えたら手で `shellcheck scripts/launchd-jrp.sh`）。
- 注意: `exec > >(stamp) 2> >(stamp >&2)` は bash 3.2 でも動くが、process substitution の読み手を `wait` できず、launchd は main が終わると同じ process group の残りを kill する（`launchd.plist(5)` の `AbandonProcessGroup`）ので、最後の数行（`vault ← …`・TIMED OUT）が落ちうる（C）。安全な形: wrapper の行は時刻を前置する `say` 関数で出す（このマシンの `date -Iseconds` は `2026-10-20T07:40:00+09:00` の形）。doctor の出力は `cat` のときに前置する。`limited()` の前後に開始と終了（status・所要）の行を出す。python の stdout は pipe やファイルに block buffering なので、外から前置すると python の行には flush した時刻が付く。時刻が要るなら python が自分で書く（Linux の cron / systemd は wrapper を通らず `jrp run` を直に呼ぶので、そちらの log に時刻を残せるのは python 側だけ）。python 側の形は Contradictions に書いた 2 案。stdout と stderr は混ぜない（テストが `out.stderr` を見ている）。2 つの wrapper を同じ変更で揃える。

### 5. DEGRADED の理由を足す【決定: 前提の修正 4】

**5.1 keyless の想定内の 429 を本物の障害と分ける**

- 変える場所: `pipeline/nets.py:381-403 _record_failure`（393-394 で `failure.reason != "missing_key"` なら `outcome.failures.append(f"{_source_key(request)} {failure.reason}")`。この文字列には `http_status` しか入らず status は入らない。395 の `"rate_limit" in failure.detail` で `budget.quiet` に入れ、`outcome.rate_limited` と `RATE_LIMITED` の note に書く）。env を受け取らないので keyless かどうかをここでは判定できない。env を持つ呼び出し元は `_send`（479-503。501 で `_record_failure`）と `_sendable`（407-430。423 で呼ぶ）。`adapters/base.py:47-76 http_status_detail`（429 と、`retry-after` か `x-ratelimit-remaining=0` 付きの 403 を `rate_limit` にする）、`adapters/base.py:162-185 Adapter`（`required_env` と `credit_cost` だけ。任意の key は各 adapter の中: `semantic_scholar.API_KEY_ENV`（29、50 で使う）・`openalex.API_KEY_ENV`（39、65）・`github.TOKEN_ENV`（21、42））。`run.py:670-672`（`outcome.failures` / `rate_limited` を `_State` に写す）と `run.py:1434-1445 _health`。`pipeline/health.py:46-63 reasons()`（59-60 の「fetch failed: …」）。
- 全消費者: `runner.py:290-295 run_summary`（title の DEGRADED と DEGRADED 行）→ `cli.py:173-175` の Slack・`init.py:196`。`run.py:1132-1150 _empty_day`（`rate_limited` を空の日の文に使う）。`run.py:1497-1520 fetch_canary` の rate_limit（health には入らない）。実績（B, `jrp-run.log`）: 直近 18 run の DEGRADED 4 回のうち 3 回が「fetch failed: recommendation/semantic_scholar http_status」（detail は 429 rate_limit）で、env に `SEMANTIC_SCHOLAR_API_KEY` が無い（key 名だけ確認）。残りの 1 回は citation/openalex の 400 / 504（本物の障害）。
- 固定しているテスト: `tests/test_run_health.py:73-107`（`reasons()` の文字列を厳密に固定: `"fetch failed: keyword/arxiv http_status"`）・`170-189`（key 未設定が failure にならない先例）、**`tests/test_pilot_fixes.py:246-277`**（`env={}` の OpenAlex の 429 で `out.failures == ["keyword/arxiv http_status"]` を assert。arXiv の keyword は OpenAlex 経由で `credit_cost` を持つ — `adapters/arxiv.py:133`。keyless の 429 を除く規則を入れると、この期待値は変わりうる）、`tests/test_nets.py:246-257,335,396`、`tests/test_adapters.py:196,373`。
- 同じ変更で直す doc: `docs/configuration.md:52`（DEGRADED の理由の一覧「a failed fetch other than a skip for an unset key」）、`docs/how-it-works.md:184-187`（Alerts）、`docs/scheduling.md:63-64`、`health.py:1-12,37-39` の docstring、`nets.py:16-18` と `adapters/semantic_scholar.py:8-12`（keyless の S2 は 429 で黙る）。
- 注意: 見分ける材料は 3 つ: `failure.reason == "http_status"`、`failure.detail` に `rate_limit`、その adapter の任意 key の env が未設定。`Adapter` に `key_env: str | None` を足すか、kind から env への map を置き、env を持つ `_send` / `_sendable` から keyless の flag を `_record_failure` に渡す。`outcome.failures` には入れず別の list（例 `expected_limits`）に回す（先例は 393 の `missing_key`）。操作欄の行と quiet の挙動はそのまま残す。決めること: key がそもそも無い adapter（`hf_papers`、firehose の arXiv RSS と HF daily）の 429 を想定内とみなすか。rule `debugging.md` は rate limit の連発を policy signal と扱うので、黙らせずに「keyless の 429 が何日続いたか」を週報か運用欄に残す形を B は勧める。適用すると 10-16 と 10-20 の DEGRADED は健全に戻り、10-17 は prose unverified で残る（B の集計）。

**5.2 空のノート（claim 0 かつ Review 0）と、問いを持つラインで引用 0 が 2 run 続くこと**

- 変える場所: `run.py:1340-1432 execute`（`accepted`・`sections`・`logs`・`self.st.bridges` を持つ。1409 で `review = list(self.st.review)` と copy し、`_fitted` は copy の方を pop するので `self.st.review` は削られない。`LineOutcome(health=self._health())` は 1427-1432）、`run.py:1434-1445 _health`（claim 数・Review 数・引用数は渡していない）、`pipeline/health.py:25-63`（新 field は default 付き: `claims`・`review`・`cited`・`previous_cited`（前回の Report が無ければ `None`））。前回は `self.known`（`LineRun.__init__` で `partition.load()`、`run.py:497`）の中の `run_date < today` の最新の Report とその `QuestionLog` から取る。`[n]` の regex は `generation/prose.py:96 _CITATION_RE`。「前の日まで」の先例は `runner.py:161-169 claims_before`。`runner.py:235-239` は open な問いが無いラインに `LineOutcome` を作らないので、「問いを持つライン」は `LineOutcome` のある全ライン。
- 全消費者: `run_summary`・`cli.py:173-175` の Slack・`init.try_line`。rotation: jev は 10-20 から daily でなく rotation に入った（B）ので、「2 run 続く」は日付の連続でなく、そのラインの Report が連続することを意味する。
- 固定しているテスト: `tests/test_run_health.py:73-117`（`reasons()` の厳密なリスト。`_outcome`（110-117）は `LineHealth` を直接作るので新 field に default が要る）、`tests/test_e2e.py:89`（健全な run の `reasons() == []`）。
- 同じ変更で直す doc: `configuration.md:52`、`how-it-works.md:184-187`、`health.py:1-12`。
- 注意: B の実測（store と vault-stage を読むだけ）: 10-05 以降の書式で claim 0 のノートは 7 本。「claim 0 かつ Review 0」で発火するのは 7 本中 1 本。「引用」の定義で結果が変わる: `QuestionLog.text` の重複を除いた `[n]` を run ごとに数え 2 run 続けて 0 なら発火、とすると ans は 10-07〜10-19 の 5 回すべて、edge は 10-20（10-17 は claim 5 件でも template で `[n]` が 0）。`Report.claims`（掲載件数）で数えると発火するのは ans だけ。O1 は「本文で初めて語られた論文」なので `[n]` の定義が O1 と揃う（B の推奨。**著者が確認する**）。「毎朝の警報 ③ は同じ理由が続くとき 1 日目と 7 日ごとにだけ通知する」（inventory 229 行）ので、前回に通知したかの記録が要るが今は無い（`RunRecord` は 8.5 の項目）。

### 6. wrapper（`scripts/launchd-jrp.sh`）

今の構造（全体を読んだ）: 129-132 で `run` 以外は `exec` で素通し（stage しない。`JRP_VAULT_DIR` は実 vault のまま）。134-141 で `TIMEOUT`・`VAULT`・`STAGE`（`${JRP_VAULT_STAGE:-$JRP_STORE_DIR/vault-stage}`）。143-145 の `rsync` が vault→stage（`*_jrp_*.md` のみ）。147-160 が doctor（`limited 120`）。162 で `MARK=mktemp`、163 `STARTED=1`。164-168 が `limited $TIMEOUT env JRP_VAULT_DIR=$STAGE jrp run`。170-182 が stage→vault（`find … -newer $MARK`、`cp -p`、`echo "vault ← …"`）。184-194 が失敗の通知と exit。実行は `/bin/bash` 3.2.57（C）。mapfile・連想配列・`${x,,}`・`wait -n` は使えない。

**6.1 `.obsidian/workspace.json` と `workspace-mobile.json` を stage に写す**【決定: 「開いたか」】

- 変える場所: 143-145 の rsync の直後で、147 の doctor の前（`CMD=run` の分岐の中、`STAGE` が決まった後）。写し先は `$STAGE/.obsidian/workspace.json` と `$STAGE/.obsidian/workspace-mobile.json`（vault と同じ配置）。python からは `vault_dir(env)/.obsidian/…`（`report/vault.py:55-62`。launchd の下では stage を指す）で読める。python の読み手は未実装（jrp ノートの名前と、一覧に初めて現れた日だけを記録し、ほかのファイル名は捨てる）。
- 全消費者: 既存の読み手に影響は無い。`reduction/used.py:180-189 _markdown` は `*.md` だけを `rglob` し、`.` で始まる部分を飛ばす（184-185）。`tests/test_used.py:107-125` が `.obsidian` を飛ばすことを固定する。`report_notes`（`vault.py:250-254`）は `daily-research/*_jrp_<slug>.md` だけ。`pipeline/doctor.py:19-22` は vault を開かない約束なので doctor では読まない。stage→vault の戻し（182）は `$STAGE/daily-research` の `*_jrp_*.md` だけを `find` するので、`.obsidian` の写しが vault へ戻ることは構造上ない。
- 固定しているテスト: 今これを固定するテストは無い。壊さない条件: `tests/test_launchd_wrapper.py:44-65 _setup` の vault には `.obsidian` が無い → 無いときは黙って何もしない（`die` すると全テストが落ちる）。143-147 は wrapper の通知が 0 件であることを見る → 写しの失敗は通知にせずログの 1 行にする。84-90（run 以外は stage に触らない）→ run の分岐の中に置く。足すテスト: vault に `.obsidian/{workspace.json, workspace-mobile.json, 衝突コピー, app.json}` を置いて run し、stage にちょうど 2 つだけがあり、mtime が保たれ、vault の `.obsidian` が変わらないこと。fake uv の中で `$JRP_VAULT_DIR/.obsidian/workspace.json` が読めること。`.obsidian` が無い vault で exit 0・通知 0。
- 同じ変更で直す doc: wrapper のヘッダ 13-16 と写し、`launchd/README.md:23-28`、`docs/scheduling.md:23-24`、`scheduling/__init__.py:5-8`、design に「開いたか」の決定の注記。
- 注意（C が実機で確認）: 2 ファイルとも最上位の key は `active / lastOpenFiles / left / left-ribbon / main / right`。`lastOpenFiles` は list。iCloud の衝突コピー（`workspace 2.json` の形）が同じ dir にあるので名前を指定して外す。dataless の印は無い。Obsidian の形式は公開仕様でない（推測）ので、python 側は壊れた JSON や欠けた key を「読めない」として扱う。`/usr/bin/rsync` は openrsync（protocol 29）で `--ignore-missing-args` が無く、単独ファイルの source が無いと exit 23。`[[ -d $VAULT/.obsidian ]]` で囲むか、`for f in …; do [[ -f … ]] && cp -p …; done` にして、失敗は `|| echo '… not staged' >&2` で終える。古い写しが残る問題: rsync / cp は stage を消さないので、vault 側が消えると前日の写しが残る。写す前に stage の 2 ファイルを `rm` する（stage はローカル）か、python が写しの mtime（`cp -p` で保たれる）を観測時刻に使う。推測: iCloud が evict した（dataless の）ファイルを launchd の bash が読むとダウンロード待ちで止まりうる（既存の notes の rsync にも同じ危険）。05:00 の写しは前夜までの状態を捉え、`workspace.json` の mtime が 05:02 なのは朝のノート到着に Obsidian が反応して書き直したからに見える。「開いたか」の日付は 1 日遅れで記録される前提で設計する。`lastOpenFiles` は件数が限られた最近の一覧なので、写しを始めた日から python が記録しないと古い分が流れて失われる（私の指摘: python の読み手と記録先は写しと同時か直後に入れる。記録先は `<JRP_STORE_DIR>/metrics/` の jsonl なら `store/migrate.py:28-32 partition_files` の対象外で migrate が触らない）。

**6.2 月曜に `jrp wbr` を作り、wbr のノートだけを 2 回目のコピーで送る**【決定: wbr の形】

- 変える場所（推奨）: 187-190（timed_out なら exit 124）の後で、191-194（最後の exit）の前。朝のノートの配達（170-182）と uncopied の通知（184-186）が済んでから走り、run が timeout した朝は走らない。形の案: `touch "$MARK"`（再利用。`on_exit` の 106 が消す）→ `set +e; limited "$WBR_TIMEOUT_S" env JRP_VAULT_DIR="$STAGE" "${JRP[@]}" wbr; …; set -e` → `find "$STAGE/$NOTES" -name '*_jrp_wbr.md' -newer "$MARK" -print0` を `cp -p` で vault へ → 失敗・timeout・写せなかったものを「jrp wbr FAILED」「jrp wbr TIMED OUT」で通知。170-182 のループを `send_back <glob>` に括り出して 2 回呼ぶと重複が無くなる。CLI 側は 8.1。
- 全消費者: `reduction/used.py:105-107 is_jrp_name`（名前に `_jrp_` があれば開く前に読み飛ばす。186・215）。`vault.py:250-254 report_notes` の glob `*_jrp_{slug}.md` は slug が `wbr` のラインがあるときだけ wbr のノートに当たり、`pipeline/config.py:59-64 load_tracks` は slug を予約語として検査しない（8.9）。144 の vault→stage rsync は vault の wbr ノートも毎朝 stage に戻す（害は無い）。182 の 1 回目の戻しは `-newer $MARK` なので run の後に作られる wbr は入らない。wbr を run の前や 1 回目のコピーの前に置くと配達順の約束が崩れる。store 側: `<JRP_STORE_DIR>/metrics/weekly.jsonl` に追記する（`.gitignore:14` の `/store/` に当たる）。
- 固定しているテスト: 今これを固定するテストは無い。**曜日を決定的にする**: `date +%u` だけで分けると既存の 10 本が月曜だけ別の経路を通る。`ENV_FILE` / `UV` と同じテスト用の上書き（例 `WBR_DUE=${JRP_WBR_DUE:-…}`）を用意し、`_setup`（56-64）で既定を 0 にする。fake uv（`test_launchd_wrapper.py:28-41`）は wbr を run として扱いノートを書き直すので、専用の分岐を足す（DOCTOR（17-24）と同じく uv の形 `' jrp wbr'` と `JRP_BIN` の形 `' wbr'` の両方）。足さないと月曜にだけ fake が run の振る舞いをして偶然に通ったり落ちたりする。壊さない条件: 143-147（通知 0 件）、123-140（timeout で通知ちょうど 1 件）、181-192・195-212・241-268（通知の件数と題の列）、215-238（TERM。`limited` を使えば `CHILD` が設定され `on_term` が wbr の group にも届く）。足すテスト: ① `WBR_DUE=1` で fake が `$JRP_VAULT_DIR == $EXPECT_STAGE` を assert し stage に wbr ノートを書く → `vault ← 2026-09-24_jrp_aap.md` が `args: wbr` より前に出て、wbr のノートが vault に届き、通知 0 ② `WBR_DUE=0` では呼ばない ③ wbr が止まると wbr の timeout で殺され、run のノートは既に vault にあり、通知 1 件、exit は run の status のまま ④ 非 0 で「jrp wbr FAILED」 ⑤ run が timeout した朝は呼ばない。`tests/test_ops_tools.py:99-106 test_cli_parses_subcommands` に `parse_args(['wbr'])` を足す。
- 同じ変更で直す doc: wrapper のヘッダ（env 一覧 3-7 に新しい key）と写し、`launchd/README.md:23-42`、`docs/scheduling.md:23-27`、`docs/configuration.md:53` の隣（`JRP_WBR_TIMEOUT_S` を env にする場合）、`docs/how-it-works.md:184-187`、`scheduling/__init__.py:5-8`、`cli.py:1-30` の docstring。
- 注意: 不変条件「python は iCloud に触らない」（wrapper ヘッダ 9-16、2026-09-24 に TCC の見えない同意待ちで 80 分止まった）。wbr の起動にも必ず `env JRP_VAULT_DIR="$STAGE"` を付け（151・165 と同じ）、vault へのコピーは bash の `cp -p` だけで行う。**順序の依存**: wrapper が `jrp wbr` を呼ぶ前に CLI に wbr が要る。wrapper だけが先に入ると月曜に argparse が exit 2 を返して「jrp wbr FAILED」になる。timeout: run の `TIMEOUT`（135-136）は数字でなければ `die` して朝の run ごと止まる。wbr の timeout を env にするなら起動時点で検査し、だめなら通知して飛ばす（wbr の設定ミスで朝のノートを止めない）。定数（`DOCTOR_TIMEOUT_S=120` と同じ形）にするとテスト ③ で 1 秒に縮められないので、上書きできる env が現実的。目安は 600 秒（`store/lines` は約 196 MB、読み込み時間は測っていない — C の推測は数十秒）。exit code: wbr が失敗しても job の exit は run の status のままにする案（朝のノートは届いている）。`launchctl list` に wbr の失敗を出したいなら非 0。通知は env に `JRP_SLACK_NOTIFY` が入った（10-20）ので wrapper の notify はすべて Slack に届き、wbr が失敗した月曜は Slack が 2 通になる。**曜日の判定（C の案 W1 と W2）**: W1 = bash が `date +%u`。月曜に電源が切れていた週は wbr が出ない。`StartCalendarInterval` はスリープ中に逃した時刻を起床時に走らせるが、電源が切れていた日は走らせない（launchd の既知の挙動、この環境では未検証）。W2 = wrapper が毎朝 `jrp wbr --due` を呼び、python が「先週の snapshot が無ければ作る」と決める。取りこぼしを後日に作れるが、毎朝 python を 1 回起動し、すべての fake に wbr の分岐が要る。D は python に置く（「月曜でなければ何もしない」）と pytest で検査しやすいとする（推測）。週の境: 05:00 JST の月曜は新しい ISO 週の初日。既定で振り返るのは前の週にする（python の `datetime.now().astimezone()` と bash の `date +%u` は同じローカル TZ）。

**6.3 wrapper の共通事項**

- 写しの同期: scripts と packaged copy は同じ commit で揃える（`test_ops_tools.py:238-243`）。`jrp schedule install`（`scheduling/__init__.py:35-47` の `plist_bytes`: Label=`local.jrp.run`、ProgramArguments=`[/bin/bash, wrapper, run]`、EnvironmentVariables={`JRP_BIN`, `JRP_ENV_FILE`}、StartCalendarInterval）が書くのは run の job だけで、drift の job は書かない。6.1 と 6.2 は wrapper の中で完結するので `plist_bytes` と `test_ops_tools.py:192-210` は変えない。月曜を別の `StartCalendarInterval` にすると plist の形とそのテストが変わるので、この案は取らない。
- 他環境の更新: `install()` は既存の wrapper を上書きしない（56-60）ので、schedule install で入れた他の環境は古い wrapper のまま 6.1・6.2・4.4 が効かない。`docs/scheduling.md` に「更新するには `~/.config/jrp/launchd/launchd-jrp.sh` を消して install し直す」と書く（`install_lines`:79 は残したファイルがあるときだけ言う）。この Mac には `~/.config/jrp/launchd/` が無い（C）。
- shellcheck は gate に入っていない（`.claude/verify.md:28-29`）。変更後に手で回す（0.11.0 で今の版は exit 0 — C）。
- 通知の件数を見るテストが 4 本ある（`test_launchd_wrapper.py` の 135・177・189・210）。正常系は 0 件（147）、`JRP_BIN` 系は題の列が 1 件（268）。新しい notify は既定の条件（`.obsidian` が無い、`WBR_DUE=0`）では 1 件も増やさない。stdout の順序を比べるのは 74 だけ（doctor の行が run より前）。

### 7. drift【決定: 「月曜 05:30 の drift の launchd job は replay の固定 probe ができるまで止める」】

- 変える場所: `cli.py:264-279 _drift`。265-267 は env の門（`JRP_DRIFT_LIVE=1` と `TYPESAFE_API_KEY`）で exit 2。274-278 が `notify("jrp drift", "N answers compared, …")`。**279 の `return 1 if failed and not rows else 0` は rows 0・failed 0 で exit 0 を返す**。`cli.py:110`（`--cassettes` の既定は `tests/cassettes/live` — repo に無い dir で、`glob` が空を返し `rows=[]` になる）。`pipeline/drift.py:54-78 drift_with_failures`。`launchd/com.shimo4228.jrp.drift.plist`（月曜 05:30）。wrapper は 129-132 で `exec` するだけで exit を通知しない。
- 全消費者: `tests/test_ops_tools.py:48-79,81-82,99-106,109-115`、`tests/test_launchd_wrapper.py:84-90`（drift の pass-through。`jrp drift` の CLI が残る限り通る）、`launchd/README.md:3,6-9,17-21`、`cli.py:1,18` の docstring、`~/Library/LaunchAgents/com.shimo4228.jrp.drift.plist`（load 済み、`launchctl list` の最後の exit は 2 — C の報告）。
- 固定しているテスト: **`_drift` の exit code を固定するテストは無い**。`test_ops_tools.py:109-115`（全 replay 失敗 → `([], 1)`）は `drift_with_failures` の戻り値。plist を固定するテストも無い。
- 同じ変更で直す doc: `launchd/README.md:3,6-9,17-21`（`cp launchd/com.shimo4228.jrp.*.plist` の glob は drift も入れ直すので run だけを名指しに直す）、`docs/design/pipeline-design.md:112-114`（decision 9 weekly drift job）・`:142`・`:150-151`（05:00 daily / Mon 05:30）・`:935`・`:947` に注記（design は経緯の記録なので書き換えず注記）、`docs/configuration.md:54`（`JRP_DRIFT_LIVE` は手動の drift に効き続ける）、`cli.py:1,18`、`scripts/launchd-jrp.sh:2` と `:6` のコメント（変えるなら写しも同時に）。
- 注意: 今の月曜は env に `JRP_DRIFT_LIVE` が無いので門で exit 2 になり、Slack には何も出ない（C は key の有無だけ確認）。`JRP_SLACK_NOTIFY=1` が 10-20 から入ったので、門を開けると「0 answers compared」が Slack に届く。直し方: `rows` が 0 なら `failed` に関係なく非 0 で返す（「比べた数 0」は失敗）。notify の文面も成功の形にしない。cassette の dir が無いか空のときはそう言って止める。job を止める実操作（`launchctl bootout gui/$(id -u)/com.shimo4228.jrp.drift`、または `launchctl unload ~/Library/LaunchAgents/com.shimo4228.jrp.drift.plist`、plist を LaunchAgents から退避。残すと次のログインで再 load される）は repo の外の scheduled task の変更で、boundary.md は無人の変更を人間に渡す側に置く。著者が決めたことでも、実行は著者に渡すか明示の確認を取る。repo 側の選択肢は 2 つ: plist を残して `launchd/README.md` に「停止中（replay の固定 probe ができるまで）」と書く / plist を `git rm` する。「固定 probe ができるまで」は復活を前提にしているので、前者のほうが戻しやすい（私の判断）。job を止めれば `_drift` の exit code は急ぎでない。

### 8. 週報 `jrp wbr` の土台（D）【決定: 方向。wbr の v0 の形は著者が 1 回見る】

棚卸しは「ダッシュボードの前に」registry・期待値の暦・破壊テスト・`RunRecord`・週次 snapshot・adapter と parity test・論文の key の統一・prefilter の q_i の対応・基準線の切れ目台帳・`[n]`–(Sk)・数値の照合を置くとしている（inventory 242 行）。ここでは、その土台が今のコードのどこに当たるかを書く。実装の規模が大きいので、別の plan に切る候補（実装の順序の 8）。

**8.1 CLI のサブコマンドの作り方**

- `cli.py:32` は argparse（typer ではない）。`parser()`（88-137）に `sub.add_parser` で足す（`--week` ISO 週、`--out`）。`main()`（282-303）は `match args.command` で、同期で直接呼ぶのは `run` / `fit|export-cases` / `migrate` / `doctor` だけ。残りは `_async_command`（306-326）へ回り、**`case _:`（324-325）は drift に落ちる**。wbr を足すときは case を明示しないと drift として走る。読むだけの前例は `_doctor`（224-227）と `migrate --dry-run`（230-233）。
- 消費者・テスト: `pyproject.toml` の `jrp = "jev_research_pipeline.cli:main"`、`tests/test_ops_tools.py:99 test_cli_parses_subcommands`、`tests/test_migrate.py:142-163`。doc: `cli.py:1-30` の docstring、README.md:118-125 のコマンド例、AGENTS.md、`docs/scheduling.md`、`launchd/README.md`、`docs/configuration.md` の変数表。
- 注意: 読むだけの約束を守るには `_prepared` / `prepare_store` を呼ばない（`cli.py:290-292,459-461` の `fit` と `export-cases` は呼ぶ = 書き込みが起きる）。ただし store の @context が additive な旧版だと `Partition.load` が `StoreSchemaError` を投げる（`graph.py:46-49`）。wbr は (a) `migrate._rewrite` の読む部分と同じく `from_document({**doc, "@context": CONTEXT})` をメモリ上だけで行う、(b) 1 行出して exit 2、のどちらかを決める。本番では同じ wrapper の `jrp run` が直前に `prepare_store` を済ませるので困るのは手で実行したときだけ。`print` は ruff の T20 で禁止なので出力は既存と同じ `sys.stdout.write`。wbr が失敗しても run 全体の exit を変えない（wrapper 194 行の `exit "$status"`）。

**8.2 store を読むだけで開く入口**

- 書き込みを伴わない入口は `GraphStore(store_dir(env)).line(slug).load()` と `.pipeline().load()` だけ（`store/graph.py:99-110`、`pipeline/runner.py:78-80 store_dir`）。`load` は毎回ファイル全体を parse して検証し（キャッシュ無し）、ファイルが無ければ `{}`。週次では各ラインを 1 回ずつ load して dict を使い回す。`reduction/log.py:39-64 DecisionLog.from_nodes / from_partition` が読むだけの集約。`<JRP_STORE_DIR>/metrics/weekly.jsonl` は `partition_files`（`migrate.py:28-32`）の対象外で、migrate も retire も触らない（`prose_bench/` と同じ置き方）。並行: `os.replace`（`graph.py:93`）でファイル単位には一貫するが、ライン間で同じ時点の snapshot にはならない。
- 既存の読み手: `runner.py:106-107,202-206,226`、`cli.py:237,255`、`prose_bench.py:214-220`、`scripts/slot_bleed.py:32`、`reduction/used.py:226-233`。テスト: `tests/test_store.py`、`tests/test_migrate.py:46-163`。

**8.3 Judgment node から Judged を作り直す adapter**

- `jev/core.py:208-229 Judged(output, judgment)`（frozen dataclass）、`333-342 output_of(output, judgment)`（`judgment.answer(name)` から出力 model を作り直す。field が無いと `KeyError`、`nodes.py:461-466`）。**`pipeline/run.py:205-223 StoredJev.judge`（222 行）が `Judged(output=output_of(ask.output, hit), judgment=hit)` を既に作る**。`judge_batch`（236-268）は単発と batched の両方の bundle で探す（256 行）。`scripts/slot_bleed.py:31-75` は store の Judgment から route を出し直す既存の前例（67-69 行）。
- adapter は `Judged(output=output_of(Answers, j), judgment=j)` の 1 行で足りる。src に関数として置く（`scripts/` は ruff・pyright の対象外 — `verify.sh:81-83` と `pyproject.toml:125 include = ["src", "tests"]`）。**版の取り違え**: store には過去の ask 版の Judgment も残る（`question_screening` の v1/v2、prefilter の n 違い）。`output_of` を当てる前に `bundle_sha256` を `{ASK.sha256, ASK.batched("source").sha256}` で絞る。`Ask.sha256` は instructions・schema・levels を含む（`core.py:90-108`）。`Judgment.model`（jev-1.13.0）で基準線を切れる。`judged_at` は最初に聞いた時刻（cache に当たると古い Judgment を返す）。`Decision` の id は (function, subjects, policy, bundle) で state も model も含まず（`nodes.py:498-500`）、判定し直すと上書きされる。履歴は Judgment 側にある。
- テスト: `tests/test_jev_core.py:185 test_a_stored_judgment_replays_to_the_same_output`、`tests/test_jev_batch.py:89`、`tests/test_e2e.py:131`。

**8.4 `question_screening.route / weighted / gates_pass / rule` の再計算と parity test**

- `jev/question_screening.py`: `gates_pass`（213-218。on_topic .5 / method .3 / evidence .3）、`weighted`（221-228。重み .5/.3/.2）、`no_abstract`（231-234。github は 40 字、他は 200 字）、`route`（237-243）、`_placed`（246-260。score < .5 → drop、≥ .7 → keep、.5〜.6 → review、.6〜.7 は certainty < .5 なら review）、`rule`（279-281。`gates_pass` かつ weighted ≥ .6 で accept = `Decision.outcome`）、`decision`（284-285）、`bridges_decision`（288-300）。`THRESHOLDS` は 150-161、`ASK` は version v3。
- 消費者: `run.py:396,713,790,835,841,862-866,873-874`、`scripts/slot_bleed.py:33,63,67-69`、`tests/test_jev_batch.py:29,88,110`、`tests/test_question_flow.py:84-122`、`tests/test_pilot_fixes.py:321-324`。固定しているテスト: `test_question_flow.py:31-97 test_gates_then_scores_then_code_routes`（7 ケース）・`99-109`・`112-122`、`test_jev_batch.py:88,110`（policy 名 `question_screening@v3_batch / @v3`）、`test_jev_functions.py:68-99`。
- 注意: `route` は引数に `source` を取る（`no_abstract` のため）。`SourceItem.text` は再取得で上書きされるので判定時と今で本文の長さが違うと incomplete かどうかが変わりうる。Judgment があるのは判定時に `_screenable` を通ったものだけ（`run.py:711-713,727`）なので、作り直しでは `no_abstract` を通ったものとみなすのが正確。parity test の形: `Decision(question_screening, policy @v3 / @v3_batch, outcome != unjudged)` ごとに `judgments[0]` → `Judged` → `rule()` を出し、(outcome == "accept"、score == `Decision.score`) と一致するかを見る。`Decision.thresholds` が今の `THRESHOLDS` と違う古い Decision（pilot 中に閾値を変えた分）は除く。route の keep は rule の accept に含まれる（逆は成り立たない: .6〜.7 で certainty < .5 は accept だが review）。canary probe（`run.py:796-845`）の Judgment は store に残るが Decision は作らず source も store に入れない（`fetch_canary` は put しない）。作り直しでは `subjects[0]` の `SourceItem` が partition に無い Judgment を飛ばす。`question_screening` の Decision があること自体が prefilter を通った印になる（`_screen` は cost cap で止まった `None` 以外をすべて decide する、`run.py:855-862`）。

**8.5 `question_prefilter.passing` と q_i ↔ 問い IRI の対応**

- `jev/question_prefilter.py`: `field(i) = f"q{i}_on_topic"`（29-30）、動的な `_answers(n)`（33-50）、`ask(n)`（53-62。version v1。field の数 n が bundle に入る）、`state`（65-70。問いを q0, q1, … の順に入れる）、`passing(result, n)`（79-84）、`decision`（87-95。on_topic の最大が .5 以上で accept）、`ASK = ask(3)`（98）。`run.py:715-756 _fetch_and_prefilter`（n = `len(self.questions)`、`passing[s.id] = hits` は index のまま）、`776-794 _screened`（index i を `self.questions[i]` に対応づけるのは run 中のメモリの中だけ）。
- **q_i と問い IRI の対応は store に残らない**。`Judgment(question_prefilter)` の subjects は `(source,)` だけで、q_i がどの Question かは `state_sha256` の中にしか無い。復元するには、その日の問いの並びで state を作り直して `state_sha256` と照合する（`slot_bleed.py:57-61` と同じ手）。`source.text` の上書き、`questions/` の書き換え（git 履歴は store から見えない）、ctx（`graph.jsonld` の語彙）の変化で照合が外れる。n は judgment.answers の key（`q{i}_on_topic`）の数から取れる。
- `passing()` を直接固定するテストは無い（tests を grep して 0 件）。`tests/test_jev_functions.py:18,45,68-99`、`tests/test_parallel.py:209-233`。実装案（D の推測）: `RunRecord` か新しいノードに `questions: tuple[IRI, ...]`（その run の `self.questions` の順）を持たせ、(日付, line) から q_i を引く。CONTEXT に項を足す additive な変更。`Decision.thresholds`（`Threshold(name, value)`）に詰めるのは型に合わない。対応を残すまでの代わりに、問いごとの p_pre は screening の Decision / Judgment の有無で出す（8.4 の末尾）。prefilter の Judgment だけからは「どれかの問いに通った率」（max）だけが出る。

**8.6 `QuestionLog` と `Report` の field**

- `model/nodes.py:724-784 QuestionLog`（`question`・`report`・`run_date`・`movement`（none / new_evidence_same_answer / answer_changed）・`text`（その日の本文）・`claims`（本文の `[n]` の順）・`sources`（初出の順）・`logged_at`。id = (question, run_date)）、`581-649 Report`（`line`・`run_date`・`rendering`・`prose`・`claims`（ノート全体の読む順）・`unjudged`・`partial`・`operations`。id = (line, run_date)）。`run.py:1078-1088` が `QuestionLog.new` を作る（`text=rendering.prose or ""`、`claims=items` の順）。
- O1 の解決: `QuestionLog.text` の `[n]` は section ごとの番号で `claims[n-1]` に当たる。`Report.claims` は使わない。`text` が `""` の QuestionLog がある（template や prose の失敗）。`Report.rendering` は最後の section の値で決まる（`_joined`）ので section ごとの rendering は残っていない。QuestionLog は `question_movement` が accept した問いにしか作られない（`run.py:1000-1003`）ので、動いていない問いは questions/ の open な問いと突き合わせて出す。`run_date` は local date（`cli.py:159`）。
- 消費者・テスト: `runner.py:108-113,161-169`、`vault.py:158-219`、`prose_bench.py:139-190 cases_from_nodes`、`reduction/used.py`、`jev/question_movement.py`、`quality.py:117`、`tests/builders.py:92-136`、`test_nodes.py:517-557`、`test_e2e.py:82-83,142-143`。`claude_calls` が常に 0 で情報が無い問題は 4.2。

**8.7 `StageRecord`**

- `model/nodes.py:996-1046 StageRecord`（`stage`・`input_sha256`・`outputs`（IRI の tuple）・`completed_at`。id = (stage, input_sha256)）、`store/stage_cache.py:17-47`、`adapters/collect.py:19-50`（stage = `fetch_{net}_{kind}`、key = `input_sha256({adapter, net, query, run_date})`。**失敗は記録しない**: 47-49。outputs はその fetch が返した全 source id で、既知の source を含む）。本番で `.record(` を呼ぶのは `collect.py:49` だけ。
- 注意: query の文字列は残らず hash だけがある。クエリ × 日への帰属は、questions/ のクエリと `run_date` から `input_sha256` を作り直して照合する。`completed_at` は stage の終了時刻でなく collect に渡る run の `now`。初取得の日 = その source id を outputs に含む StageRecord の `completed_at` の最小（`SourceItem.fetched_at` は再取得のたびに上書き — `adapters/base.py:248`）。失敗した fetch が StageRecord を残さないので、「0 件」と「失敗による欠落」は StageRecord の有無で分かれる一方、「予定されたが送られなかった」は見えない（`RunRecord` の要求台帳が要る）。firehose の outputs が BM25 cap の前か後かは `nets.py` 側で確かめる必要がある（`per_net` は `_capped` の後、`seen` は run 内。2.2）。テスト: `tests/test_nodes.py:560-592`、`tests/test_adapters.py:264` 付近。

**8.8 `questions.py`**

- `questions.py:68-70`（`QUESTIONS_ENV`、既定 `~/.config/jrp/questions`）、`92-98 questions_dir / questions_path`、`140-167 parse_questions(text, *, line, opened_at)`（status を問わず全問をファイル順に）、`170-184 _opened`（`opened:` が無ければ fallback = now）、`187-219 open_questions(env, slug, *, line, now, stored=None, evidence_scope=None)`（open な問いだけ。0 件なら `NoQuestions`）。読むだけ（docstring「never written by a run」）。
- 注意: wbr は `open_questions(env, slug, line=line_context(track).line.id, now=…, stored=nodes)` で今の open な問いを取り、`NoQuestions` を「問い未設定」として数える。`line` 引数は Line の @id（`pipeline/config.py:114-143 line_context`）で、Question の id は (line, slug, version) なので取り違えると store の Question と一致しない。本番の `JRP_QUESTIONS_DIR` は main の checkout の `questions/` を指し（AGENTS.md）、wrapper は `~/.config/jrp/env` を source するので `CMD=run` の中の wbr も同じ dir を読む。store の Question node は accept が出た日に `_with_evidence` で put されるだけ（`run.py:1405`）なので、動いていない問いは store に無い。Q の分母は questions/ から取る。過去の問いの文言は store に残らない（version を上げると新しいノード）。`opened:` が無い問いは毎回「今日開いた」扱い（`_opened`）なので、14 日の判定で `opened` を使うと誤る。テスト: `tests/test_questions.py:43-130`、`tests/test_authored_queries.py:9-38`。

**8.9 wbr のノート名と `report_notes`・`is_jrp_name`**

- `report/vault.py:65-68 note_path` は `daily-research/{date}_jrp_{slug}.md`。`report_notes`（250-254）の glob `*_jrp_{slug}.md` は slug が `wbr` のときだけ `YYYY-MM-DD_jrp_wbr.md` に当たる。`load_tracks`（`pipeline/config.py:55-72`）は slug を予約語として検査しない。**`wbr` を予約する検査（`load_tracks` か doctor）とそのテストを足すのが安全**（コード上の穴）。仮に当たっても frontmatter に `jrp_report` が無ければ `harvest_note` は `harvest skip … no_report_id` の 1 行を出すだけで（`vault.py:238-242`）、本文に `<!-- jrp:` を置かなければ tick も拾わない。
- `reduction/used.py:105-107 is_jrp_name`: `YYYY-MM-DD_jrp_wbr.md` は名前に `_jrp_` を含むので、vault の走査で開かれる前に外れる（186）。名前から `_jrp_` を外すと used に混入する。ADR の走査（211-214）は `skip_jrp` も `is_jrp_output` も通さないが、wbr の出力先は store と vault だけなので問題ない。本文に key と `jrp:` の印を置かない方針（inventory 214 行）は、後で走査先を足したときの二重の防御になる。本番の vault 経路は stage（`*_jrp_*.md` だけ）を読むので、常に空になる。著者の決定どおり「graph と ADR のみ」の宣言済みの縮退として wbr の M 欄と registry に書く（警報にしない）。週 1 ファイルなら名前の日付は月曜の `run_date`。`write_note` の carry over は印の行だけを引き継ぐ（`vault.py:105-133`）ので、印の無い wbr は同じ日に作り直すと単に上書きされる。テスト: `tests/test_used.py:92,118,370`、`tests/test_launchd_wrapper.py:68,84`。

**8.10 監視用 judge の API 経路（`anthropic:` backend）**

- `generation/client.py`: `ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"`（60）、`parse_model`（86）、`prose_auth`（119。key の env が無ければ `MissingCredentials`）、`_credit_exhausted`（151。400 + "credit balance is too low"）、`auth_failure`（158）、`Writer`（210-259。`AnthropicProvider(api_key=…, http_client=http)` を 233 で作る）、`GenerationMeter`（262-274。`cache_*` は捨てる）。`generation/prose.py:291-316` は `usage = RunUsage()` を `agent.run(usage=usage)` に渡し `finally` で足す（失敗した呼び出しも計上される）。`pipeline/costs.py:15-23 PRICES`（`anthropic:claude-opus-5-5` = (4.0, 20.0) USD/Mtok。as-of 2026-10-19、cache なしの基本単価）、`40-57 Budget`（line-run ごとの `JRP_COST_CAP_USD`）。`generation/claude_code.py:79-83 child_env` は `claude -p` の子から `ANTHROPIC_API_KEY` を外す。`pipeline/doctor.py:156-175 _writer` が key を検査するのは `JRP_PROSE_MODEL` が `anthropic:` のときだけ。
- 判定の部品: `pipeline/prose_bench.py`: `cases_from_nodes`（139。store の QuestionLog から BenchCase を作る。書き込みなし）、`export`（208。`cases/` に書くので使わない）、`gates`（262）、`materials`（427）、`gate_files`（476。`bench/gate/` に書くので、本文を組み立てる部分だけを関数に切り出す）、`Check` / `GateVerdict`（508-520。`Value`: frozen・extra=forbid）。`pipeline/prose_eval.py`: `JUDGE_MODEL = "opus"`（53）、`Ask`（model, instructions, prompt, output_type → BaseModel）と `claude_ask`（295）、`_burst`（308。`ClaudeUsageLimit` で止める）、`judge`（340）。rubric は `docs/prose-rubric.md`（と `.en.md`・`.zh.md`）の Q1〜Q6、`cli.py:78-85` の `DOCS`・`RUBRICS`。`.claude/agents/prose-judge.md` は session から dispatch する版。
- テスト: `tests/test_anthropic.py:61`（価格）・`67`・`74`・`83`（Messages API への送信と meter、usage 120/40）・`104`・`122-157`（401 とクレジット切れを auth failure として扱う）、`tests/test_doctor.py:124-169`、`tests/test_claude_code.py:182`（子の env から key が消える）、`tests/test_prose_bench.py:50,90,100,130,149`、`tests/test_prose_eval.py:61,99,143,171`。
- 注意: 監視 judge の model は `Writer(prose_auth(env, parse_model("anthropic:claude-opus-5-5")), http).model(thinking=…)` で作れる。`prose_auth(env)` を引数なしで呼ぶと本番の writer（`claude-code:`）の spec になる（`client.py:121`）ので spec を明示する。key が無いときの `MissingCredentials` は「未測定（key なし）」として扱う。`ANTHROPIC_API_KEY` を env に足しても `claude -p` の writer は `child_env` で key を受け取らないので、サブスクから API 課金に切り替わる事故は起きない（テストで固定済み）。**費用の食い違い**: 費用は jrp 自前の `costs.PRICES` で数える。pydantic-ai の `RunUsage.cost` と `UsageLimits(cost_limit)` は genai-prices 0.1.7 の表を使い、`claude-opus-5-5` を `claude-opus-5` の前方一致で $5/$25 と引く（D、`.venv` の `genai_prices/data.py:405-425`）。jrp の $4/$20 と食い違い、どちらが今正しいかは確かめていない。`filterwarnings = ["error"]`（`pyproject.toml:152`）なので、価格が引けないと `CostNotFoundWarning` でテストが落ちる（`pydantic_ai/usage.py:557-565`）。週 $5 の予算は run をまたぐので永続の台帳が要る（`costs.Budget` は line-run 単位なので流用しない）。再試行しない: `AnthropicProvider(api_key, http_client)` は SDK 既定の `max_retries` で内部の client を作る（D の推測で既定 2）。再試行させないには `AnthropicProvider(anthropic_client=AsyncAnthropic(…, max_retries=0))` にし、`anthropic` を直接 import するので `pyproject.toml` に依存を足す（deptry）。429・クレジット切れ・401 では止めて「未測定」にする（`prose_eval._burst` の形を 429 と 400(credit) に当てる。rate limit の連発は policy signal — rule `debugging.md`）。構造化出力は `NativeOutput(GateVerdict)` を明示し、`httpx2.MockTransport`（`test_anthropic.py:40-42` の形）で request body を固定するのが確実（D の推測）。本番の本文を判定するときの抜粋は `materials` が今の `SourceItem.text[:1500]` から作るので、再取得で text が上書きされた source の分だけ writer が受け取った抜粋と違い、Q5（出どころ）が偽の No を出しうる（claims は Unit を通した逐語なので保存されている）。rubric の置き場 `DOCS` は checkout の `docs/` を指し、wheel には入らない（推測）ので、`uv tool install` の環境では wbr が rubric を読めない。判定の系列は judge・rubric・Jev の版が変わったら切り、rubric の sha（`prose_eval.sha` と同じ 16 桁）とモデル名を `weekly.jsonl` に残す。OUT の精度標本（O1 の論文から週 12 件）は既存の rubric に無い新しい判定なので、prompt と出力型を新しく作る。doc: `docs/configuration.md:38`（ANTHROPIC_API_KEY の行を「監視 judge でも使う」に）、README.md:103、`pipeline-design.md:532` と `:894-895` に監視に限った例外の注記。

**8.11 `.claude/verify.sh` と破壊テストの置き場**

- `--staged`（51-76）は staged の `.py` を tmp に展開して `ruff format --check`・`ruff check`・`bandit`（src のみ）。full（79-88）は `ruff format --check src tests`・`ruff check src tests`・`pyright`・`bandit src`・`deptry src`・`pytest -q`。`pyproject.toml`: `--cov-fail-under=80`（branch）、`filterwarnings = ["error"]`、`testpaths = ["tests"]`、pyright `include = ["src", "tests"]`、ruff に C901 10・PLR0912 12・PLR0911 6・PLR0915 50・PLR0917 5・ANN（src のみ）・T20。`scripts/` は ruff・pyright の対象外。
- 注意: 破壊テストは `verify.sh` を変えずに `tests/` へ pytest として足せば full の `pytest -q` で走る（例: `tests/test_wbr_registry.py` で「registry の全計器に故障を注入して検出するテストがある」を assert する）。`verify.sh` 自体は承認済みの内容 hash で pin されていて、変えるには著者の承認が要る（harness の security.md / boundary.md）。外部 API は `httpx2.MockTransport` か cassette で書く（offline が前提）。coverage 80% のため、wbr は純関数（nodes → 数）と I/O（読む・書く）を分ける。

## Contradictions

- **`claude_calls` の旧 key の処理**（A と B）: 両者とも新 field（`writer_calls`）を足す案を推す点は一致し、`NonNegInt` に広げて key 名を残す案は採らない。違いは旧 key で、A は「`Literal[0]` で default 0、または exclude」、B は「field を消して before-validator で捨てる」。どちらも golden と store と互換で、plan で 1 つ選ぶ（私は default 付き + `exclude=True` のほうが `test_nodes.py:515-519` を残せて小さいと見るが、未検証）。
- **ログの時刻の python 側**（B と私）: B は `run_summary` に `started`/`finished` を keyword-only・default None で渡して body に足す案、私は `cli._run`（`run_summary` の外）が stdout にだけ開始・終了・所要の 1 行を書く案。前者は Slack の本文が変わり `test_run_health.py:123` の厳密一致に触れる（default のままなら通る）。後者は Slack と `run_summary` が変わらない。
- **5.1 のテスト影響**（B の記述と私の読み）: B は「keyless の 429 を外すと `test_pilot_fixes.py:246-277` の期待値が変わる」と書いた。arXiv の keyword は OpenAlex 経由（`credit_cost`）で、OpenAlex に任意の key があるので、`Adapter.key_env` を OpenAlex に付けるかどうかで変わる（arXiv 自体に key は無い）。付け方で決まるので「変わりうる」と書いた。
- **決定の文言と実装**（A）: 2.1（生成は含まない）、2.2（取得数 → 新規）、2.3（label → チェック在庫）は、決定の文言のままでは新しい誤ラベルになる。決定を覆す提案でなく、文言の精密化の提案。
- **調査者 A の `string_match`**: 「常に真」でなく「実質つねに真」（Scope searched に書いた）。

## 実装の順序の提案（依存の順）

前提: 各 commit は `.claude/verify.sh` を通し、単独で deploy できる（additive な migration は毎回 1 回の書き直し）。plan の commit（`docs(plan): <slug>`）を最初に単独で入れる。wrapper と launchd に触れる変更は 05:00〜06:00 を避けて main に入れる（0.3）。`tests/test_parallel.py` と `tests/test_note_text.py` は 2〜4 のすべてが通る関所。

0. **著者の手番（実装前）**: store の退避（0.2）。`## Still unknown` の 1〜5 の確認。
1. **golden を足す**（テストのみ。0.1 の提案）。HEAD の build で Report・Label を書いた golden を置き、新 model で旧 Report が通ることを pin してから model を変える。
2. **捨てている数を残す（schema と capture を同じ deploy に）**: 4.1（`Label.first_harvested_at` + 持ち越しの規則 + 3 つのテスト）、4.2（`writer_calls` + `Operations` の `claude_calls` の扱い + `Msg` + `builders.py`）、4.3（`JevClient` の token counter + `Operations` の 2 field）。CONTEXT に 4 項（`first_harvested_at`・`writer_calls`・`jev_input_tokens`・`jev_output_tokens`）を足し、`test_parallel` の一致を最初に確かめる。1 日遅れるごとに失われる数なので、退役より先に置く。capture は `Operations` と `_operations` を触るので、先に入れると 3 以降の編集が一度で済む。
3. **運用欄から外す（決定済みの退役）**: 3a = 1.2・1.3・1.4（`meters.py` の f・topic・TTD と `_discovery_lines`、README.md:78-80・README.ja.md:50・how-it-works の書き直し、`test_nets.py` の 3 本）。3b = 1.1・1.5・1.6（rule 候補・gold 一致・`trusted_axes`・grounded の行。`DecisionLog.from_nodes` が不要になる。`AxisMeter.gold_agreement` は default `None` で残す。`cli._fit` は `trusted` を渡さない。`test_quality.py:119-126` を同じ変更で直す）。3c = 1.7（support の秒）。各 commit に design への注記（decision 5・6 ③・7 の supersede）と samples の扱いを含める。3a〜3c は互いに独立で順序は自由だが、同じ `_operations` / `Msg` を触るので逐次に入れる。
4. **改名**: 2.1（cost）、2.2（net 取得数: 文言を 2.2 の選択肢で決めてから）、2.3（harvest）。新しい日本語の接頭辞は `Msg`（ja・en・zh）にする。【提案のみ】の項（3 の節）は著者の確認後にここへ足す。
5. **DEGRADED の理由**: 5.1（`Adapter` の `key_env` と `_record_failure`、`test_pilot_fixes.py:246-277` の期待値の見直し）→ 5.2（`LineHealth` の新 field と「引用」の定義。著者の確認後）。5.1 と 5.2 は互いに独立。
6. **wrapper**: 4.4（ログの時刻: `say` と開始・終了の行 + python の 1 行）と 6.1（`.obsidian` の写し）を 1 回の deploy にまとめ、scripts と packaged copy を同時に変える。6.1 の python 側の読み手と記録先（`metrics/` の jsonl）は同じ commit か直後に入れる。shellcheck を手で回す。
7. **drift**: repo 側（`_drift` の exit と cassette 0 本のときの停止、README・design の注記、plist の扱い）を入れ、`launchctl unload` と LaunchAgents の plist の退避は著者に渡す（boundary.md）。順序は自由で、job を止めれば急がない。
8. **週報の土台（別の plan に切る候補）**: 8.3 の adapter（`Judgment → Judged`）と 8.4 の parity test → 8.5 の `RunRecord`（q_i の対応を含む。CONTEXT に項を足す）→ registry と期待値の暦と破壊テスト（8.11）→ `jrp wbr` の CLI（8.1・8.2、`_async_command` の `case _:` に注意）と wbr のノート名の予約（8.9）→ **その後に** wrapper の月曜の hook（6.2。CLI が先、wrapper が後）→ 監視 judge（8.10。著者が `ANTHROPIC_API_KEY` を env に足してから）。基準線の切れ目台帳と jev-1.14.0 は計測の土台ができてから単独の週に入れる（決定）。
9. **ついでの doc 修正**（別 commit、軽微）: inventory「見つけたが直していないもの」のうち、AGENTS.md の「claude-code:claude-opus-5-5（2026-10-02 から）」（10-02 の run はまだ codex で claude-code の最初の run は 10-03）と「ja = v16 + check10（2026-10-19 から）」（本番に効くのは 10-20 の run から）、design の v16 節の「Production fails the cutoff 5-6 of 10」。`note_text.py:306` の誤文言は 3a で消える。

依存の要点: 1 は 2 の前。2 は 3・4 より先（`Operations` の形が一度で済む）。6.2 は 8 の CLI の後。5・6・7 は他と独立。

## Still unknown

1. **著者に確認する文言と範囲**: 2.2（「新規」を store に対する新規にするか、文言を「取得（run 内の重複除去・上限の後）」にするか）、2.3（「チェック在庫」を「label 在庫（累計、qday の伝播を含む）」にするか）、2.1（従量の書き手で嘘にならない文言）、3 の節の【提案のみ】4 項（net 採用率を外すか、openalex credit の改名、「動いた」/「n 問い」、queries の秒）。
2. **5.2 の「引用」の定義**: `QuestionLog.text` の `[n]` を数えるか `Report.claims` を数えるか（B の推奨は `[n]`）。
3. **5.1 の「想定内」の範囲**: key がそもそも無い adapter（`hf_papers`、firehose の arXiv RSS と HF daily）の 429 を想定内とみなすか。
4. **rule 候補の module を消すか残すか**、`_silver` / `n_silver` を消すか（1.1・1.5）。消すなら decision 6 ③ と decision 5 の supersede 注記が要る。
5. **docs/samples の扱い**: 本物の出力の見本なので、退役した運用欄の行を手で消すのは「本文は jrp 自身の出力」（README.ja.md:34）という言明と食い違いうる。作り直す（`jrp try` は live の Jev と writer を呼ぶ）か、日付つきの出力として残すか。
6. **4.2 の旧 key の処理形**（default + `exclude=True` か before-validator か）と、`requests` が失敗した試行を数えるか（推測のまま）。
7. **この session で走らせていないもの**: `.claude/verify.sh`、pytest、git、launchctl、shellcheck。実機の状態（plist の同一性、env のキー名、Obsidian の `workspace*.json` の構造、bash 3.2、openrsync）は C の確認に依る。4.3 の `response.usage` の field 名は pydantic-ai 2.47.0 / SDK 0.7.1 の読みで、版が上がれば変わりうる。
8. **cassette 再生での `writer_calls` の決定性**（`test_parallel.py:79-103` の逐次・並列の一致）。最初のテストで確かめる。
9. **bash が走行中の script を書き換えで壊す条件**（0.3）と、`StartCalendarInterval` の電源断の挙動（6.2）は未検証。
10. **pydantic-ai の `RunUsage.cost`（genai-prices 0.1.7）と jrp の `costs.PRICES`** のどちらが今の Claude API 単価に合うか（8.10）。
11. **wbr の実行時間**（`store/lines` 約 196 MB の load）は測っていない。
12. **jev-1.14.0 で応答の `usage` の形と確率の格子が変わるか**（決定により土台の後で単独で入れる）。

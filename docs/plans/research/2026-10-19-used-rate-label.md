kind: internal
# used rate 遅延ラベル: 著者の tick の代わりになるか（内部実測 + 外部の先行知見）

as-of 2026-10-19。内部は repo の main（HEAD eec9758）と著者環境の実体を Read / Grep / Glob で調べた。シェルが無かったため mtime・行数の集計・git 履歴は取っていない（`## Still unknown`）。vault と対象 repo は名前・path を伏せ、「vault」「対象 repo」と書く。

## Scope searched

- 内部: `pipeline/runner.py`、`pipeline/run.py`、`report/vault.py`、`report/markdown.py`、`model/nodes.py`、`store/graph.py`、`reduction/{fit,log,rules,cases}.py`、`quality.py`、`pipeline/{meters,nets,config}.py`、`adapters/*`、`docs/design/pipeline-design.md`、`docs/plans/daily-tool-hardening.md`、`docs/plans/productize-en-zh.md`。実体は store（`<repo>/store/lines/*.jsonld`）、vault（Obsidian、`JRP_VAULT_DIR`）、`~/MyAI_Lab/daily-research/config.toml`（旧 pipeline と共有、gitignore）、各対象 repo の `graph.jsonld` と `docs/adr/`。
- 外部: Kiryo 2017（nnPU）、Elkan & Noto 2008、Bekker & Davis 2020、Chapelle 2014、Hu/Koren/Volinsky 2008、Chaney 2018、Scholar Inbox 2025。読んだ深さは各項に書く。

## 1. ラベルの流れ（今日）

### 1.1 収穫と保存

- 収穫は `jrp run` の最初の段。`run_pipeline` が各 line（`only or (*rotation.order, *daily)`、つまり毎日全 line）に `harvest_line` を呼ぶ（`pipeline/runner.py:176-182`）。
- `harvest_line`（`runner.py:90-125`）: line の partition を `load()` し、`report_notes(vault, slug)`（`report/vault.py:250-254`、`*_jrp_<slug>.md` の glob）の各 note を `harvest_note`（`vault.py:220-247`）に通す。`part.put(result.labels)`（`runner.py:117`）で Label を upsert、`part.remove(result.cleared)`（`runner.py:122`）で空欄の box の Label を削除する。
- 読む行は `- [x|-| ] … <!-- jrp:<kind>:<payload> -->` だけ（`vault.py:36` の `_MARK_LINE_RE`）。kind は `qday` / `source` / `claim`（`report/markdown.py:15-21,64-66`）。`[x]`=correct、`[-]`=incorrect、`[ ]`=無ラベル（`vault.py:81-84`）。
- qday の tick は、その日の `QuestionLog` が引く claims と sources に伝播する（`vault.py:185-189`、provenance `question_day`）。claim 自身の tick は伝播分に勝つ（`vault.py:182-183`）。
- `Label` ノード（`model/nodes.py:787-843`）: `subject`（QuestionLog / SourceItem / Claim の IRI）、`report`、`verdict ∈ {correct, incorrect}`、`provenance ∈ {question_day, source, claim}`（`nodes.py:54`）、`harvested_at`。**@id は (subject, report) だけから決まる**（`nodes.py:809-811`）。
- 実体（store、2026-10-19 時点）: Label 163 件、`verdict: incorrect` は **0 件**（全 line で `"verdict":"incorrect"` が 0 match）。QuestionLog 160 件、SourceItem 58,905 件（8 line 合計）。既存ゴールドはすでに正例だけ。
- `harvested_at` は tick の時刻ではなく**最後に収穫した run の時刻**。収穫のたびに `Label.new(... harvested_at=now)` で同じ @id を上書きする（`vault.py:173-179`）。store の Label も `2026-10-19T05:00` の値を持つ。

### 1.2 Label の消費者

| 消費者 | file:line | 負例が要るか | 正例だけだと |
|---|---|---|---|
| `jrp fit`（閾値提案） | `reduction/fit.py:152-209`、`cli.py:236-242` | 要る。`classes` が 2 種に満たないと提案しない（`fit.py:185-191`）。さらに claim 単位で `MIN_GOLD=10`（`fit.py:36,182-184`） | 全閾値が `skipped`（「すべて correct — 両方の判定が揃うまで提案しない」）。現状の store がこの状態 |
| gold 一致 meter / `trusted_axes` | `quality.py:77-105`、`run.py:1194-1198` | 形式上は不要だが、正例だけの一致率は「正と予測した割合」にしかならない（`quality.py:85-91`）。floor 0.7・n≥10 で axis を信頼（`quality.py:47-49,95-105`）し、信頼された axis は silver label になる（`fit.py:130-143`） | 全部を正と予測する axis が floor を通る。subject は claim のみ（`quality.py:82`） |
| 「rule 候補」行 | `reduction/rules.py:47-54,97-104`、`run.py:1237` | **Label を読まない**。Decision の outcome と source の特徴（adapter・age・text 長）だけで作る | 影響なし。used rate の消費者ではない |
| Semantic Scholar の推薦 | `run.py:580-608`、`pipeline/nets.py:16-18,84-86` | 負例が無ければ seeded random negatives 5 件で補う（`run.py:595-607`、`nets.py:84`） | 今の運用がすでに正例のみ + 乱数負例。used を足すと正例が増える。positive の id は arXiv / DOI の URL からしか作れない（`nets.py:192-199`） |
| 記入率 | `run.py:1562-1583`、`run.py:1200-1221` | 不要。直前 report の qday のうち `provenance=="question_day"` の Label がある割合。verdict は見ない（`[-]` も記入） | 別の meter。provenance を分ければ混ざらない |
| Time-to-Discovery | `pipeline/meters.py:76-98`、`run.py:1180` | `correct` のみ使う | `harvested_at - fetched_at` を使うので、used の Label を足すと日数の意味が変わる（上記 `harvested_at` の上書きで、古い tick ほど日数が毎日伸びる既存の癖もある） |
| `jrp export-cases` | `reduction/cases.py:29` | `log.gold()` の全件 | 同じ gold を取り込む |

`DecisionLog.gold()`（`reduction/log.py:103-111`）は `kind_of(subject)=="claim"` の Label を **provenance に関係なく**全部取る。つまり verdict `correct` の Label を claim subject で足すと、fit・agreement・cases・Time-to-Discovery・推薦の全部が「著者の gold」として読む。別ノード型にすれば、配線するまでどの消費者にも届かない。

### 1.3 既存 Label との衝突

used の Label を同じ `Label`（@id = (subject, report)）で作ると、`[ ]` の box が空の note を収穫するたびに `cleared`（`vault.py:198-217`）がその @id を `part.remove`（`runner.py:122`、`store/graph.py:63-71`）で削除する。記入率 0.00 の今、毎日全部消える。別ノード型か別の @id 空間が要る。

## 2. 出た source の同一性（identity）

- `SourceItem` の @id は `(line, url)`（`nodes.py:186-188`）。同じ URL を 2 line が拾えば 2 ノード。再取得は同じノードを更新し `fetched_at` も更新される（`nodes.py:167-168`）。**「出た日」は `fetched_at` でなく `QuestionLog.run_date` / `Report.run_date`**（`nodes.py:724-756`、`QuestionLog.sources` は `run.py:1072,1082` で note に載った source）。
- 「出た」の定義が 3 通りある: (a) note に載った = `QuestionLog.sources`（160 question-day）、(b) Review の `jrp:source` 行（境界の資料、`markdown.py:17-18`）、(c) 取得した全部 = SourceItem 58,905 件（`passing` を経て claim になるのは一部、`run.py:1262-1277`）。分母がこれで 2〜3 桁変わる。
- adapter ごとの URL 形（`adapters/`）:
  - arXiv firehose / arxiv adapter: `https://arxiv.org/abs/<id>`（版なし。`adapters/arxiv.py:57,72-75`、firehose は RSS の `link`）。
  - HF papers: `https://huggingface.co/papers/<arXiv id>`（`hf_papers.py:44`、`firehose.py:99`）。
  - OpenAlex: `work.doi or work.id`（`openalex.py:169`）。DOI URL か `openalex.org/W…`。
  - Semantic Scholar: `paper.url`、無ければ arXiv abs（`semantic_scholar.py:86`）。`paper.url` の中身は未確認。
  - GitHub: `html_url` = `github.com/<owner>/<repo>`（`github.py:59`）。
  - web_search: 任意の URL（`web_search.py:44`）。
  - canary: arXiv abs / GitHub（`canary.py:35,52,67`）。
- 既存の抽出器: `nets.arxiv_id_of`（`nets.py:183-189`、abs / pdf、版を落とす）、`nets.paper_id`（`ARXIV:`/`DOI:`、`nets.py:192-199`）、`nets.openalex_work`（`nets.py:202-213`）。注意: `arxiv_id_of` は `tail.split("v")[0]` で版を落とすので、旧形式の id（`solv-int/…` のように id 中に `v` を含むもの）は壊れる（`nets.py:189`）。
- note に出る ID: frontmatter の `jrp_report: "<IRI>"`（`vault.py:37,136-147`）と、コメント内の `jrp:source:<IRI>`。IRI は `https://…/jrp/source/<md5>`（`STORE_NS`）で、jrp の note の外には現れない。**外の文書との照合には使えず、自己参照の印としてだけ使える**。
- 自由文で照合できるもの: arXiv id（`\d{4}\.\d{4,5}`）、DOI（`10.\d+/…`、arXiv は `10.48550/arXiv.<id>`）、`github.com/<owner>/<repo>`、正規化した URL（scheme・`www`・末尾 `/`・クエリ・fragment・版を落とす）。照合しにくいもの: OpenAlex W id、web_search の任意 URL、タイトルだけの引用。

## 3. 見る 3 か所

### 3a. graph.jsonld

- jrp が今 graph.jsonld を読むのは語彙のためだけ: `config.py:106-111` の `_read_graph`、`config.py:132-135` で `Concept` / `DefinedTerm` の `name` と `alternateName`、`config.py:120-129` で `ResearchLine` の `url` が repo 名で終わるノードの `@id`（line の @id に再利用）。`@type` は最後の segment で照合（`config.py:84-91`）。`@graph` の各ノードの `url` / `sameAs` / `identifier` は読んでいない。ほかの読み手は grep で見つからなかった。
- 場所: `[[tracks.<slug>.repos]] target_repo` の先頭だけ（`config.py:55-72`、`repos[0]`）。**著者の config.toml は 7 line、うち target_repo を持つのが 6、graph.jsonld を持つのが 4**（残り 2 は資料中心 repo で graph 無し、1 は repo 無しの ecosystem line。設計も「desire, edge は graph 無し」と書く: `pipeline-design.md:148`）。「any line's graph.jsonld」は、今の `line_context` が line ごとに自分の repo だけ読む作りから、全 track の repo を読む作りに変える必要がある（`runner.py:165` の `tracks` が入口）。
- 中身（形だけ）: ノードは `ScholarlyArticle` / `SoftwareSourceCode` / `TechArticle` / `Concept` 等（対象 repo の 1 つで確認）。MyAI_Lab 配下の 10 個の graph.jsonld 合計で、arXiv abs / DOI / GitHub の URL に当たる箇所が 1,818 件。ただし GitHub の多くは著者自身の repo で（自己参照）、外部論文の数ではない。
- 注意: 設計は「graph.jsonld への昇格は pipeline が diff を提案し、著者が適用する」（`pipeline-design.md:35-36`）。この経路が動くと、jrp の出力が graph.jsonld に入り、その後に used と数えられる（§5 自己参照）。

### 3b. ADR

- 対象は line の `target_repo` の `docs/adr/` だけ（他の repo の ADR は line と結びつかない）。確認できたのは 4 repo に ADR あり（資料中心の 2 repo と ecosystem line は未確認）。MyAI_Lab 配下の `*/docs/adr/*.md` は 517 ファイル（`.ja.md` の重複を含み、line と無関係な repo も含む）。
- **ADR に arXiv / DOI の URL が出る頻度は非常に低い**: 517 ファイル全体で 8 ファイル・10 箇所（うち 2 ファイルは旧 pipeline の repo）。URL / id 照合では ADR 経路はほぼ発火しない。タイトル・著者年での引用は検出できない。
- line→ADR の対応は `config.py` の `TrackSpec.repo` から導ける（`repo / "docs/adr"`）。この規約は config に書かれていない。

### 3c. vault

- 構造: `daily-research/`（旧 pipeline の note `YYYY-MM-DD_<track>_<slug>.md` と jrp の note `YYYY-MM-DD_jrp_<slug>.md` が同居）、`archive/`（`01_Inbox`、`00_Home` の MOC、`80_Templates`）、`scripts/`、`.obsidian/`。.md は約 930 本。jrp の note は **99 本**（2026-09-22〜10-19、1 日 3〜4 本）。それ以外が約 830 本。
- 旧 pipeline の note は 2026-09-22 の日付が最後（10 月の非 jrp note が `daily-research/` に無い）。`archive/` と合わせ、**10 月以降に著者が書き足した note は daily-research の外にあるか、無い**。週あたりの更新数は mtime が取れず未測定。
- arXiv / DOI を含む非 jrp note は **17 本・33 箇所**で、全部 `daily-research/` の旧 pipeline 形式の名前。つまり著者が自分で書いた note に arXiv / DOI が出る頻度は、この vault では測れる範囲でほぼ 0。vault 経路も照合の主役にならない（GitHub URL・タイトルは未集計）。
- 自己参照を避ける材料:
  - ファイル名 `*_jrp_*.md`（`vault.py:68,254`）、frontmatter `category: jrp` と `jrp_report:`（`markdown.py:3-6`、`vault.py:136-147`）、コメントの `jrp:` 印（`vault.py:36`）。
  - 旧 pipeline の note は `daily-research/` で日付形式が別。旧 config には「自己汚染ガード」`self_signals`（`~/MyAI_Lab/daily-research/config.toml:6-13`）があり、「自分の成果物は外部シグナルに数えない」という先例がある。
  - jrp の note は source の URL を `[title](url)` で本文に持つ（`markdown.py:18,21`）ので、除外しないと全 source が即 used になる。
- note から jrp 由来のリンクを写す手段: skill `x-draft` は daily-research の report から X の下書きを作る（`~/.claude/skills/x-draft/SKILL.md:10,26`）。書き出し先は読んでいない。vault に落ちるなら機械生成の自己ヒット。

### 3d. line と 3 か所の対応（概数）

7 line のうち: graph.jsonld あり 4、ADR あり 4（確認分）、repo なし 1（ecosystem、graph も ADR も無い）、graph も確認済み ADR も無い 2。つまり graph / ADR の経路は **7 line 中 4 line でしか原理的に効かない**。vault は line と無関係に全 note 共通。

## 4. 時期・再計算・保存・backfill

- 成熟日: 最古の jrp note は 2026-09-22 なので、30 日の窓が閉じる最初の日は **2026-10-22**。2026-10-19 時点で成熟した source は 0 件。
- 「appears」の日付: graph.jsonld のノードに日付は無い（形の確認のみ。`datePublished` 等の有無は未集計）。ADR は日付を frontmatter かファイル名に持つか未確認。vault の daily-research 外の note は mtime のみ。**窓内に出たかを後から判定するには出現日が要る**。取れる手段は (i) 毎 run で索引を作り「初出日」を記録する（前向きのみ）、(ii) 対象 repo の git 履歴（graph・ADR のみ。vault は iCloud で git 管理なし。git 履歴の有無は未確認）、(iii) day 30 の 1 回きりの snapshot 判定（出現日は問わない）。
- 毎日の再計算コスト: 索引は 1 run 1 回で足りる（graph.jsonld 最大 4 本、ADR 4 repo、非 jrp の .md 約 830 本から id 集合を抜く）。照合は集合の所属判定。`Partition.load()` は呼ぶたびに全ファイルを parse する（`store/graph.py:42-50`、最大の line で SourceItem 15,630 件）ので、候補 source を `QuestionLog` から引き、line ごとに 1 回だけ load する。`harvest_line` が毎日全 line で load 済み（`runner.py:99-100`）。
- 保存先の選択肢: (A) line の partition に新ノード型（`UsedMark` など）を足す。`GraphNodeType` の union（`nodes.py:925-939`）、`jsonld.py` の context（`IRI_FIELDS` と `_typed` の並び、`jsonld.py:187-188` に同種の例）、migration は additive（`store/schema.py:6`、`prepare_store` が書き換える）。`put` は全体を書き直す（`store/graph.py:16-17,55-61`）ので run あたり 1 回にまとめる。(B) 保存せず毎回 vault から再計算。vault・graph・ADR は可変（削除・改名で値が変わる）ので過去の値が再現しない。(C) store 外の別ファイル（proposal と同じ `<store>/proposals/`）。
- backfill: 窓を過ぎた過去の source に対し、現在の vault / graph / ADR の状態で判定すると「30 日以内」という定義にならない（出現日が無い）。成熟前の source は前向きの snapshot でしか取れない。9/22〜10/21 の source は 10/22 以降に順次成熟するので、機能が入る前の分は「判定不能」か「入った日から」の扱いを著者が決める。

## 5. コードから見えるリスクと設計文書との衝突

### 5.1 偽陽性

1. **jrp 自身の note**: 全 source の URL が本文にある（`markdown.py:18,21`）。除外キーは §3c。
2. **canary 論文**: `Question.canary_papers`（`nodes.py:679`、`pipeline/run.py:1268`）は著者がもう知っていて graph / ADR に載っていそう。surfaced に数えると自明な正例になる。
3. **著者自身の repo / 論文**: graph.jsonld の GitHub URL の多くは著者自身（`JRP_GITHUB_OWNER` の line では GitHub adapter が同 owner を拾う: `config.py:34,118-119`）。旧 config に `self_signals` の先例。
4. **graph.jsonld への昇格 diff**（`pipeline-design.md:35-36`）、**x-draft など machine 経路**: jrp の出力を経由して入る。
5. **surfacing より前から graph / ADR にあった source**: novelty は claim 同士の重複判定（`jev/novelty.py`）で、graph.jsonld の参照とは突き合わせていない。既知の文献が出て、day 30 の判定で即 used になる。baseline（出た時点で既に存在したか）が要る。
6. **S2 推薦のフィードバックループ**: used を `_positives_and_negatives`（`run.py:580-608`）の正例に戻すと、jrp が出した source が用いられ、それに似た source を jrp が更に出す。
7. 同一 URL の別 line 重複（`nodes.py:186-188`）と、同一論文の別 URL（arXiv abs・DOI・HF papers・OpenAlex）。正規化を決めないと二重計上か取りこぼし。

### 5.2 偽陰性

- タイトルだけの引用、翻訳、`[[wikilink]]`、著者年。URL / id 照合は検出しない。
- 読んで行動が変わったが文字に残らない。
- ADR / 非 jrp の vault note から arXiv / DOI が出る頻度が低い（§3b・3c）。**used rate の分子が 0 近傍で、tick の記入率 0.00 と同じ「測れない」になる可能性**が、実測の分布からは見える。見積もりは立てていない。
- 窓 30 日の外（遅く使われる）も落ちる。

### 5.3 設計文書との衝突・前提

- `pipeline-design.md:324-331`: 「Pilot first … label/fit design … is NOT extended further … used rate は後で … Decide after the pilot has run for a few weeks」。「canary と cross-net agreement を弱教師に、⭕❌ は optional gold に下げる」と一緒に書かれている。
- `daily-tool-hardening.md:70-71`: used rate は「記入率 0 を受けて設計提案までにとどめる（実装しない）」。`productize-en-zh.md:78`: 「設計判断なので提案まで」。実装は著者の判断が先。
- 設計 decision 5-7（`pipeline-design.md:70-97`）: gold は著者の ⭕❌、dense は rubric、一次指標は記入率。used rate は gold ではなく別の弱ラベルで、`Label` の意味（「著者が正しいと言った」）と違う（`nodes.py:787-795`）。
- `config.py:15`: graph.jsonld は読むだけ（書き戻さない）。used rate は読み取りなので衝突しない。
- 運用: fit が提案を書くだけで適用しない（`fit.py:212-226`）。used 由来の提案も同じ扱いにできる。
- `public-records`: 非公開 repo の ADR / graph を読んでよいか、結果（used かどうか）を公開記録に出すか。store は `.gitignore`（`/store/`）。

## 6. 外部の先行知見（as-of 2026-10-19）

読んだ深さを各項に書く。

- **Kiryo, Niu, du Plessis, Sugiyama 2017, "Positive-Unlabeled Learning with Non-Negative Risk Estimator"（arXiv:1703.00593、NIPS 2017）** — abstract のみ読了。正例と unlabeled だけで 2 値分類器を学ぶ設定で、unbiased な PU risk は柔軟なモデルだと経験 risk が負になり過学習する。non-negative 推定量で抑える。abstract には class prior の扱いが無い。こちらへの移し方: `fit.py` は 1 次元の grid search なので過学習の問題は小さいが、PU は unlabeled に含まれる正例の割合（class prior）が前提になる。used の「unused」は「負」でなく unlabeled。
- **Elkan & Noto 2008, "Learning classifiers from only positive and unlabeled data"（KDD 2008, pp. 213–220）** — PDF は本文を取れず、検索結果の要約のみ。ラベル付き正例が全正例からの無作為抽出（SCAR）という仮定が中心。SCAR の下で「ラベル付き vs unlabeled」の分類器から正負の分類器を得る、という要約まで。定数 c の推定式は本セッションで確認していない。used は SCAR にならない（使われる確率が topic・読みやすさ・露出に依存する）ので、そのまま当てはめられない。
- **Bekker & Davis 2020, "Learning from positive and unlabeled data: a survey"（Machine Learning, arXiv:1811.04820）** — abstract のみ。PU の設定と 7 つの研究課題を整理する。SCAR や選択バイアスの扱いは abstract に無く、本文は未読。
- **Chapelle 2014, "Modeling delayed feedback in display advertising"（KDD 2014, pp. 1097–1105, doi:10.1145/2623330.2623634）** — 検索結果の要約のみ（本文・abstract 原文は未読）。conversion はクリックの後最大 1 か月遅れ、まだ変換していないクリックが負例に見えて推定が下に偏る。遅延分布のモデル（混合モデル）で補正する。後続 (arXiv:2202.06472) の要約は取れず。**window 内の「まだ used でない」を負にしない根拠**になる。代案は成熟した（30 日経った）ラベルだけを使うこと。
- **Hu, Koren, Volinsky 2008, "Collaborative Filtering for Implicit Feedback Datasets"（ICDM 2008, pp. 263–272）** — 原論文は取れず、解説・学位論文の二次情報のみ。行動の不在は嫌いを意味せず、二値の選好 + 信頼度（confidence）の重みで扱う（`c = 1 + βx`）。「30 日使われなかった = 負」とせず、重みを下げた弱い負として扱う設計の先例。
- **Chaney, Stewart, Engelhardt 2018, "How Algorithmic Confounding in Recommendation Systems Increases Homogeneity and Decreases Utility"（RecSys 2018, arXiv:1710.11214）** — abstract のみ読了。推薦の影響を受けた利用者データで訓練すると、シミュレーションで挙動が均質化し、utility は上がらない。**system 自身の出力が正例を作るループ**の指摘。jrp では S2 推薦（`run.py:580-608`）と、出した source が使われたことを正例に戻す経路が当たる。
- 補足（確認できなかった）: コードのコメントは Scholar Inbox を random negatives の出典とする（`nets.py:17-18,84-86`）。Scholar Inbox（arXiv:2504.08385、ACL 2025 demo）は検索 snippet で「80 万件のユーザー評価」「active learning で評価を促す」までは確認したが、random negatives の記述は確認できていない。この論文が使うラベルは明示評価で、暗黙の「後で引用した」ではない。「後で保存した / 引用した」を論文推薦のラベルにした先例は、今回の検索では一次資料まで届かなかった。

## 7. 著者が決める未決事項と、効く証拠

1. **「出た」の分母**: note に載った source（QuestionLog.sources、160 question-day）／ Review の境界 source ／取得した全部（58,905）。証拠: §2。分母が違うと used rate の意味が別物になる。claim や qday に落とすなら `DecisionLog.claims_of`（`log.py:72-77`）で source→claim にできる。
2. **「appears」の定義**: URL 一致 / arXiv id・DOI・GitHub slug / タイトル一致。証拠: ADR で URL が出るのは 517 ファイル中 8、非 jrp の vault note で arXiv / DOI を含むのは約 830 本中 17（全て旧 pipeline の note）。URL・id 照合だと分子が 0 近傍の恐れ（§5.2）。タイトル照合は偽陽性が増える（未測定）。
3. **窓**: 30 日か、別の長さか。出現日の取り方（前向きの初出日記録 / git 履歴 / day 30 の snapshot）。証拠: graph.jsonld ノードに日付が無く、vault は git 管理外（§4）。最初の成熟日は 2026-10-22。Chapelle は遅延が最大 1 か月の広告での値で、論文推薦の遅延分布は未測定。
4. **30 日使われなかったことを負にするか**: (a) 負にしない（正例のみ。fit は 2 クラス揃わず提案しない: `fit.py:185-191`）、(b) 弱い負（重み付き: Hu et al.）、(c) 負（偏りが入る: unused は「正しくない」でなく「未使用」）。証拠: 既存の gold も正例だけ（incorrect 0 件）。fit の意味は「correct なら accept」（`fit.py:3-5`）で、used は別の量。PU の前提（class prior・SCAR）が used では成り立たない可能性（§6）。
5. **tick を置き換えるか、併走させるか**: 記入率は読まれている証拠（一次指標、`pipeline-design.md:94-97`）で、used rate とは別の量。置き換えると記入率の meter が消える（`run.py:1562-1583`）。併走なら provenance か別ノード型で分ける必要がある（§1.3）。設計は ⭕❌ を「optional gold に下げる」と書く（`pipeline-design.md:329-331`）が、置き換えるとは書いていない。
6. **どの消費者に届けるか**: fit・gold 一致・S2 推薦・Time-to-Discovery・cases のどれに used を入れるか。証拠: §1.2 の表。`gold()` に混ぜると全部に届く（§1.2 末尾）。別ノード型なら配線を選べる。S2 推薦に戻すとループ（Chaney）。
7. **除外集合**: jrp の note、canary、著者自身の repo、旧 pipeline の note、graph への昇格 diff、surfacing 以前から graph / ADR にあった source。証拠: §3c・§5.1。旧 config の `self_signals` が先例。
8. **保存**: 新ノード型 / 毎回再計算 / store 外ファイル。証拠: §4（可変性、`put` が全書き直し、additive migration）。
9. **backfill**: 機能導入前に出た source を「判定不能」にするか、「導入日から」にするか。証拠: 最初の成熟日 2026-10-22、出現日が後から取れない（§4）。
10. **実装の許可**: 設計文書と計画は used rate を「提案まで」としている（§5.3）。著者の判断が先。

## Still unknown

- vault の週あたり更新数（mtime が取れなかった）、jrp 以外で著者が書いた note の数、GitHub URL・タイトルでの照合の頻度。
- graph.jsonld ノードの日付 field の有無、ADR の日付の持ち方、対象 repo の git 履歴の有無。
- 資料中心の 2 repo と ecosystem line に `docs/adr/` があるか。
- `QuestionLog.sources` の 1 日あたりの件数（note に載る source の分母）と、旧形式 arXiv id が store に何件あるか。
- Semantic Scholar の `paper.url` の中身（arXiv 照合ができるか）。
- `x-draft` の書き出し先、および vault に jrp 由来の機械生成物が他にあるか。
- Elkan & Noto の c の推定式の確認、Chapelle の本文、Hu et al. の原論文、後続の delayed feedback 論文 (2202.06472) の本文は読めていない。論文推薦で「後で保存 / 引用」をラベルにした先例の一次資料も未確認。
- 外部の主張はすべて 2026-10-19 時点の取得。いずれも古典的な結果で、新しい手法に置き換わっていないかは調べていない。

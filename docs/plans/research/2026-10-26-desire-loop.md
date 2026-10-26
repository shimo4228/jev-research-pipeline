kind: external
# desire ラインの一人称の問いは、なぜ 5 週間動かず、何を変えれば一周回るか

as-of 2026-10-26。plan の根拠にする調査 report。判断（採る / 採らない、plan の形、問いの案）は plan 側が持つ。この report は見つけたもの・確かめたこと・こちらの状況との違いを書く。

## Scope searched

- 外部 notes（researcher、as-of 2026-10-26）を全文読んだ: `~/.cache/claude-research-notes/2026-10-26-desire-loop/first-person-sources.md`。notes の調べ方は WebSearch 約 19 回・WebFetch 約 48 回・PDF 1 本（目安 20 を超えた。経路の実測に回数を使ったので、偽物のリスクと日本語の検出精度は薄い）。notes の WebFetch 由来の引用は小モデルの要約で、**原文未確認**。この report でも引き継ぐ。
- 著者の研究記録（公開 repo `https://github.com/shimo4228/desire-frontier`）の `concepts.md` と `testimonies.md` を、節の見出しと行番号つきで読んだ。
- 現行の問い `questions/desire.md` と、`file:line` を確かめたコード（src/jev_research_pipeline/ 以下 21 ファイル。下の「確認」に一覧）を実物で読んだ。
- この report のための web 調査は WebFetch 2 回だけ（notes の主張の再確認）: HN Algolia の items API（id 46960408）と Gizmodo の記事。どちらも小モデルの要約が返り、原文は読めていない。WebSearch は 0 回。
- 調べていない範囲: Reddit、note の検索 API の実動作、はてなブログ単体の検索、日本語の一人称記事での AI 検出精度、trust の床を下げたときの他ラインへの波及（lead の実測に無い。offline で測れる道は「Still unknown」に書いた）。

## Found

### 1. 一人称の証言の 3 型（notes A、as-of 2026-10-26）

「作りたいものが尽きた」とはっきり書いた一人称の記事は、notes の調べでは WebSearch から 0 件（日英 14 本の検索）。見つかったのは近い型の 3 つで、HN の Algolia API と note / Zenn の feed を直接叩いて当たった。各型 1 件の読みで、検定にならない（notes の注意）。

| 型 | 例（日付・出典） | 読んだ深さ | 在庫 / フローのどちらに効くか（notes の読み） |
|---|---|---|---|
| (a) 発想の在庫が小さい | Gizmodo Japan「『AIを使えばアプリが作れる』ってホント？文系が10ヶ月やってみた」、かみやまたくみ、2026-04-18。`https://www.gizmodo.jp/article/ai_coding_10_month`。一人称、追記・訂正なし。「アイデアの枯渇はわかりやすいと思います。素人が思いつけるものなどたかが知れている。」「新しいアイデアを得ようとしてAIとブレストをしても、同じようなアイデアに収束してしまう。」 | notes と本 report の再取得の 2 回、WebFetch の要約。引用は両回で一致。原文未確認 | 在庫モデルに最も素直。ただし「欲望」でなく「発想の源」の話で、続報は無い |
| (b) 苦労と結びついた欲望が、苦労の消失で消えた | HN「Ask HN: How to find joy in writing/learning about tech in this AI world?」 sriram_malhar、2026-02-10、`https://news.ycombinator.com/item?id=46960408`。40 年ほぼ毎日書いてきた人。同じ人の 7 か月後のコメント（2026-09-16、`https://news.ycombinator.com/item?id=49721680`）は「楽しみのプログラミングへの興味をなくした。数年かけて一般相対論の前提を学ぶことにした」「紙の本に戻れて気持ちがいい」 | notes は Algolia の items API の要約。本 report の再取得も要約のみ（引用の字句は再現できなかった）。原文未確認 | 在庫の枯渇とも、Imas / Girard 型のフローとも読みにくい「過程に結びついた欲望」（notes の読み）。**続報つきの 1 人分** — `author_<user>` タグで同じ人の後の発言を引けた唯一の経路 |
| (c) 満たされても圧力で続く | Nikhil's Blog「ai-makes-us-feel-unproductive」、2026-03-09、`https://nikhil.bearblog.dev/ai-makes-us-feel-unproductive/`。「作りたいものはもう作った」のに「十分にやっていない」という nagging feeling。意欲も好奇心も保つ | WebFetch の要約。原文未確認 | 「尽きた」の証言ではなく対照。在庫は満たされたのに欲望が続く点で、フロー（比較・圧力で湧き続ける）側の材料 |

周辺（notes A の 3〜10、snippet か題だけ）: HN dokdev（2026-03-03、学ぶ動機の話で欲望の枯渇ではない）、HN dimonb19a（2026-07-20、仕事の動機）、note きお / Keogh「『作りたい気持ち』だけはあるのに『作りたいもの』はない時の自分の対処法」（2026-09-30、題と日付のみ、AI の話かは不明）。決める量が増えて疲れる系（Stack Overflow blog 2026-05-21、Axios 2026-04-04 ほか）は取材・論説で一人称の証言ではなく、「欲しいものの枯渇」と逆向き。lead の現行クエリ（`web: AI coding agents lost motivation what to build next`）が拾った decision fatigue の記事はここに当たり、問いに合わない。

語彙（本文または題に実際に出た語、notes）: 日本語はアイデアの枯渇、停滞、収束、作りたいものがない、作りたい気持ち、欲望、やりたいことがわからない。英語は impulse … vanished、lost interest in programming for pleasure、lost my ability to learn、nagging feeling、decision fatigue。「作りたいものが尽きた」と書く人は少ない。「nothing left to build」は HN で AI と無関係の慣用か、AI 賛美への反発が多い。

本 report の再取得で出た差（WebFetch の要約、原文未確認）: sriram_malhar の投稿は、書く動機の消失に加えて「小さな kata を作って人に教える実践が恋しい。会う人は過程より最終成果物を気にする」とも要約された。notes の (b) の読みは「過程に結びついた欲望」だけだが、後半は**過程を受け取る相手の不在**にも読める（concepts.md 32〜35 行の受け手の消失に近い）。どちらの強調で型を付けるかで、この 1 件の行き先が変わる。判別質問 3（下の §5）が要る。

### 2. 届かせる経路（notes B、as-of 2026-10-26、実際に fetch）と jrp への入り方

notes の実測に、jrp の adapter の実物（`src/jev_research_pipeline/adapters/`）を重ねた。コード読みで、実行はしていない。

adapter の一覧は `hf_papers` `arxiv` `openalex` `semantic_scholar` `github` `web_search` `feed` `sitemap` `firehose` `canary`。**HN Algolia 用の adapter は無い**。`feed:` は RSS / Atom 以外を `ValueError("not an RSS or Atom feed")` で落とす（`feed.py:100-101`）ので、Algolia の JSON は入らない。

| 経路 | notes の実測 | `feed:` で入るときの挙動（コード） | 状態 |
|---|---|---|---|
| Zenn topic feed `https://zenn.dev/topics/ポエム/feed` | RSS 2.0・20 件。2026-10-03→10-25（約 23 日 = 3 日窓で 2〜3 件）。description は途中で切れた抜粋。一人称の随筆が多い。大きい topic（`ai` 約 4 時間、`claudecode` 約 5 時間）は 20 件が数時間で入れ替わる | 窓は run の日の 3 日前から（`feed.py:47`）。抜粋だけの item は本文が空になり、ページを取りに行く（`Follow`、1 feed 1 run 10 件まで: `feed.py:51`、`base.py:383-385`）。item が feed と同じ host なら feed の値を使う（`feed.py:116-117`） | 入る。日次の poll に量が合う |
| note ハッシュタグ RSS `https://note.com/hashtag/<タグ>/rss` | RSS 2.0・25 件。`#ClaudeCode` は 25 件で約 42 分、`#生成AI` は 5 件で約 1 分（人気タグは 3 日窓の 99% 以上が流れる）。`#作りたいもの` は 25 件で 2024-09→2026-10（月 1 件ほど。全投稿でなく選別の可能性があるが未確認）。description は未確認 | 同上。note の本文を `Follow` が読めるかは未確認（`page.py` は regex で `<main>` か `<article>` を抜く。script だけの shell は短い本文になる。YouTube の watch ページが 139〜163 字の footer だったと `feed.py:82` が記す） | 入るが、大きさが合うタグを探す必要がある |
| note ユーザー RSS `https://note.com/<urlname>/rss` | 25 件。description は冒頭 40〜160 字 + 「続きをみる」 | 同上 | 既知の書き手を追う用。時系列に使える |
| Substack `https://<名>.substack.com/feed` | `content:encoded` に本文全部 | feed の中身をそのまま本文に使う（`feed.py:69-75`）。`Follow` 不要 | 書き手を指名する用 |
| はてなブックマーク検索 RSS `https://b.hatena.ne.jp/search/text?q=<語>&mode=rss&sort=recent` | RSS 1.0・40 件、1 回 29 万字。先頭 14 件に語が見えず、関連性は未検証 | item は外部 host に張るので feed の値を使わず、ページを取りに行く（`feed.py:116-117`）。1 run 10 件まで | 関連性が分からない。note・Zenn・はてなブログ・anond を一括で拾えるのが利点 |
| hnrss.org（HN の RSS） | doc は読めた。item の取得は **2 回とも HTTP 502**（2026-10-26）。`q` は既定で題だけ。本文は `search_attrs=default` | item の link は `news.ycombinator.com` で feed の host と違うので、feed の本文は捨ててページを取りに行く（`feed.py:116-117`） | 第三者のホストで 502 を観測。Algolia が使えるときの代わりにはなる |
| HN Algolia `https://hn.algolia.com/api/v1/search_by_date?query=<語>&tags=ask_hn&numericFilters=created_at_i>EPOCH` | JSON。本文は `/api/v1/items/<id>`。`tags=author_<user>` で同じ人の後の発言が取れる。全語 AND ＋ typo 許容で、5 語以上の自然文は 0 件か雑音、短い語 1〜2 個 ＋ `ask_hn` ＋ 日付が効く。公式のレート上限は未確認 | **adapter が無い** | 一番当たるが、入れるには adapter を足す |
| note 検索 API（非公式）`https://note.com/api/v3/searches?context=note&q=<語>&sort=new` | WebFetch は 403。Zenn の二次資料（`zenn.dev/zeroyen_dev/articles/note-search-api-count`）は「ログイン不要・UA が無いと 403・0.35〜0.45 秒空けないと 429・非公式で予告なく変わる」と書く | adapter が無い | 動作未確認 |
| Reddit | この環境の WebFetch が reddit.com を拒否したので未確認 | adapter が無い | 未確認 |
| 既存の `web:`（lead の試し打ち F） | 上位は X の話題、note の kota の記事、アベプラ、DEV の tips、HN の dokdev、SO blog の decision fatigue。notes の WebSearch も同じで、一人称の「尽きた」は出なかった | — | 現行の供給源。一人称に当たらない |

経路から言えること（notes）: 同じ人の数か月後を取れたのは、HN の `author_<user>` と、ユーザー RSS（note・Substack・Zenn・はてなブログ）の「書き手を指名して追う」形だけ。キーワードで新規の証言を探せるのは HN Algolia、note の非公式検索 API、はてな検索 RSS の 3 つで、癖か未確認が付く。

### 3. 個人の記述を証拠として扱う作法（notes C）

jrp の `source_trust`（単一軸の hard gate）との違いを先に書く。以下 4 件はいずれも jrp の対象（日次の資料 1 本の受け入れ判定）とは別の枠で、移せるのは考え方だけ。

1. **Garousi, Felderer, Mäntylä「Guidelines for including grey literature and conducting multivocal literature reviews in software engineering」**（arXiv 1707.02553、IST 2019 の pre-print）。PDF を本文で読んだ（notes）。含めるかの 7 問（Table 4。1 つでも yes なら含める。3 番目「文脈が結果に効くか」、7 番目「実践者の資料が大量にあり関心が高いか」が jrp の問いに近い）。品質 checklist（Table 7、Guideline 11）は producer の権威・方法・客観性・日付・関連資料との位置・新規性・影響・outlet の種類の 8 基準を各 0 / 0.5 / 1 で採点し、合計（例では 20 点満点）に閾値（例 10）を置く。outlet の項は「ブログ・メール・tweet = 0」だが、5 件の例の合計は 13・19・16・15.5・12 点で、ブログ 1 件が 13 点で通る。「全ての grey literature に合う 1 つの品質モデルは無い。対象に合わせて調整する」。違い: 対象はソフトウェア工学の実践知で、証言ではない。「参照があるか」「方法が書かれているか」は一人称の経験談が構造的に低く出る基準。移せるのは、単一軸の hard gate でなく複数基準の合計と閾値、という形。
2. **GRADE-CERQual**（Lewin ほか 2015, PLoS Med 12(10): e1001895 を本文、2018 の Implementation Science シリーズは snippet）。4 成分は方法論上の限界・関連性・一貫性・データの十分さ。確信は high から始め、懸念ごとに下げる。方法論上の限界のある研究は**除外せず、確信を下げる**。違い: 質的研究の統合から出た知見の確信を評価する枠で、日次の記事 1 本の判定ではない。移せるのは (1) 落とさず重みを下げて通す、(2) 判定の単位が資料 1 件でなく「知見を支える証言の集まり」、(3) 関連性（問いの文脈に合うか）を資料の質と別軸にする。
3. **Verification Handbook**（European Journalism Centre、要約記事と snippet のみ）。出所・書き手・日付・場所を確かめ、目撃証言は「どうしてそれを知っているのか」を問い、転載でない最初の版かを見る。移せるのは、確かめる対象が主張の真偽でなく「書き手本人の記述か」「いつ書かれたか」になる点。
4. **Admiralty code**（NATO、AJP-2.1 / STANAG 2511。公開 doctrine は無く Wikipedia と MISP の snippet のみ）。情報源の信頼度（A〜F）と情報の確からしさ（1〜6）を別軸にして互いに影響させない。個人ブログ 1 本は実績が測れないので信頼度の軸は「判定できない」になり、一人称を求める問いでは確からしさの軸（他の証言との整合・具体さ）で見るほうが合う、という移し方（notes の読み）。深くは読んでいない。

jrp 側の実物との対応（コード読み）: `Trust` は 4 段（anonymous / personal / report / established）で、personal は「named author の個人ブログ・newsletter・forum 投稿で、証拠への参照が少ないか無い」（`source_trust.py:18-29`）。`min_trust` は 0.5（`source_trust.py:50`）、判定は各段の確率で重み付けした位置（`source_trust.py:53-55`、`expected_position` は `nodes.py:361-364`）なので、personal に確信が高い資料は 1/3 ≈ 0.33 で、report か established に確率が乗らない限り通らない（`source_trust.py:68-72`）。しかも outcome が accept でなければ次の段に進まない（`run.py:845-852`）。つまり Garousi の「outlet は 8 基準の 1 つ」でなく、CERQual の「落とさず確信を下げる」でもない、**1 段の hard gate**。

### 4. 偽物のリスクと、受け入れ・落とす条件の材料（notes D）

- AI 文章の検出は当てにならない: Liang ほか（arXiv 2304.02819、2023、abstract のみ）は非ネイティブの英文を AI と誤判定し、単純なプロンプトで回避できると報告。Sadasivan ほか（arXiv 2303.11156、TMLR、v4 2025-01-17、abstract のみ）は言い換えで検出率が落ち、モデルが良くなるほど原理的に難しくなると論じる。日本語での測定は見つからなかった。文体は jrp の gate の単独の根拠にしにくい。
- 振る舞い・出所（アカウント履歴・投稿時間の偏り）は文体より長持ちするという主張は、偽レビュー対策の販売業者の snippet で、測定精度は無く、割り引く。
- FTC の偽レビュー・証言の最終規則（press release 2024-08-14）は、実在しない人物を装う AI 生成のレビューを禁じる。使えるのは検出法でなく「存在しない人の証言」が既知の類型だという定義。米国向けで、日本のステマ規制は調べていない。
- 観測した実例（notes）: `#生成AI` の note feed に「AI 社員 6 人の副業日報」（運営者が人間であることは本文で明示）があった。透明だが「一人の作り手の証言」ではない。note の書き手自身が「AI 丸コピ記事だらけ」で読まなくなったと書く記事が複数ある（snippet のみ。割合の測定ではない）。
- 一人称でも通らないもの（notes）: Nikhil は一人称でも「尽きた」でない。Gizmodo は一人称だが媒体の編集者の仕事の記事。HN の「nothing left to build」は AI 前や AI 賛美への反発の慣用が多い。一人称は受け入れの条件の 1 つにすぎず、問いに合うかは別の判定が要る。

受け入れる側の手がかり（notes の材料）: 書き手本人の経験として書かれている（Verification Handbook）／日付がある（Garousi の日付）／いつ・何を作り・何が起きたかの具体さ（CERQual の十分さ）／問いの文脈に合う、AI を使い込んだ作り手（CERQual の関連性）／講座・ツール・サービスの宣伝の利害が無い（Garousi の客観性）／同じ人の続きがある（ユーザー RSS・HN の author タグ）。落とす側: 転載・まとめ・まとめサイトの再掲／日付なし／宣伝の利害が見える／組織・運営者名の日報／AI 文体の検出を単独の根拠にする。外れる条件: 一人称の「具体さ」は AI が生成しても出せる（Sadasivan）。宣伝は個人ブログの形で現れる。

### 5. concepts.md の節と台帳への問い — 一人称の証言で決着できる項目（問いの書き直しの材料）

行番号は 2026-10-26 に Read した版。案は書かず、節・判別に使う観測・一人称で決着する条件を並べる。

**5.1 在庫とフローの対抗モデルに結ぶ軸**（concepts.md 124〜145 行）

- 124〜126 行「対抗モデル — 欲望は在庫か、フローか」: 在庫モデルは `desire exhaustion` の定義文（消化速度 > 補充速度、7〜8 行）、フローモデルは Imas / Girard（欲望は他者の欲望から生まれ飽和しない）。**同じ観測（AI に頼みたいことがない）から出る次の問いが変わる**: 在庫なら「なぜ補充が遅いのか」、フローなら「誰との回路が切れたのか」。一人称の本文でどちらの語りかは、補充（アイデア・題材）に触れるか、誰か（読者・使う人・比べる相手）に触れるかで読める。
- 133〜139 行「統合仮説」: 受け手の消失・生計依存・mimetic 断絶を「欲望の社会的供給源が断たれる」一つの機構の三断面と読む。138 行の実行条件は「**社会的回路が太いのに枯渇した証言が一本も出ないことを確認してから**」。
- 141〜145 行「反対材料」: ① 消費側の実証で制作側は空白（142 行）、② Trammell は飽和回避を財の種類の拡大で説明（143 行。多様性説の含意は「新しい種類のものを見つける」、模倣説は「他者との回路を繋ぐ」）、③ 自己決定理論は観衆ゼロでも動機が成立すると言う（144 行）。一人称では「誰も見ていなくても作るか」の記述が③に、「同じ発想に収束する」の記述が②に触れる（本 report の読み。Gizmodo の「収束」は種類の広がりの話に近い）。

**5.2 隣接機構と判別質問**（32〜48 行、50〜67 行）

| concepts.md の節（行） | 何が隣接機構か | 判別に使う観測（本文から抜けるもの） |
|---|---|---|
| 判別質問 1（64 行） | 空洞化（56 行）対 枯渇 | AI との作業自体は楽しいか。楽しくない・虚しい → 空洞化の可能性。楽しいのに頼むことがない → 枯渇に接近 |
| 判別質問 2（65 行） | 剥奪（57 行）対 枯渇 | 望みの対象は「取られた」か「湧かなくなった」か |
| 判別質問 3（66 行）と「受け手の消失」（32〜35 行） | 受け手の消失（59 行）対 枯渇 | もし誰か一人が確実に使ってくれると分かっていたら作るか。作る → 在庫は残り、止めているのは受け手の不在。作らない → 在庫が尽きている。質問 1「楽しい」・質問 2「湧かなくなった」の証言は**既存 2 問だけでは構造上すべて枯渇に誤分類される**（66 行）。mimetic 断絶（37〜38 行）は「使う人はいるが欲しがられない」で、第 3 問では分けきれない |
| 判別質問 4（67 行）と「公開の停止」（40〜48 行） | 作るが出さない | 作ったものを人に見せるか。型の確定でなく**情報の捕捉**用（46 行）。1〜3 問をすべてすり抜けるので、採録時に答えを残し続報を追う。読み方 A（新しい停止点）と B（枯渇の上流イベント）は続報で分ける（44 行） |
| 「境界」の表（52〜61 行） | 枯渇は**未測定**（58 行。既存実験は望みの対象が外から供給されるため原理的に測れない）。受け手の消失は 1 venue で測定、中身は消失でなく希釈（59 行） | — |
| 「受け手の消失」の下位（35 行） | 消失か希釈か | **証言だけでは分けられない — 集計が要る**（35 行）。一人称では決着しない項目 |

**5.3 台帳への問い**（testimonies.md 41〜54 行。見出しは「証言 1 本で決着する項目」。起票は 2026-08-17 時点、53〜54 行は 08-19 の追記）

| 問い（行） | 決着させる証言・観測 | 一人称の記述で足りるか |
|---|---|---|
| 気質は枯渇の必要条件か（45 行。concepts 88 行） | 見切りの遅い人が枯渇に到達した証言 | 足りる。経歴の早い撤退・転身の有無をプロファイルで確かめる（concepts 78 行の予測 1、testimonies 39 行） |
| 枯渇は生計から切り離された欲望に固有か（46 行。concepts 119 行） | 生計に依存した欲望の枯渇証言 1 本 | 足りる。プロファイル欄の生計依存（testimonies 39 行） |
| 三断面は一つの機構か（47 行。concepts 138 行） | 社会的回路が太いのに枯渇した証言（未探索） | 足りる。読者・使用者・同業者・クライアントの有無（testimonies 39 行） |
| 「完成した瞬間に興味が消える」は気質か構造か（48 行。concepts 14・89 行） | AI 関与を伏せて公開した自作への他者反応が、明示した場合と違うか | 本人がその比較を書いた記述が要る。書かれる頻度は未確認 |
| 制作欲望に mimetic 機構は効くか（49 行。concepts 142 行） | 既存文献に答えなし（消費側の転写） | 「AI 製と知られて欲しがられなくなった」型の記述（台帳 31 行の dzervas）が材料 |
| 次に裏切られる定型句は（50 行） | 「何を作るかは人間に残る」（muu3 / yminabe / tsuyuki、台帳 23・29 行）か「作れば誰かが使う」（yun_bow、27 行）か。続報が枯渇型へ転じた方 | **同じ人の時系列**。現行の問いの `method: 同一人物の時系列` と同じ形 |
| 公開の停止は新機構か上流イベントか（51 行） | Castillo / dzervas（台帳 30〜31 行）の 1〜3 年後の続報（2027〜2029 再訪） | 同じ人の時系列。今は待つ項目 |
| 日本語圏ゼロは時間説か構造説か（52 行。concepts 154〜158 行） | 「作りたいものがない」型より先に「作ってはいるが出さない」型が出るか | **両方の型を拾い、発表日の順を残す**必要がある（testimonies 37 行の発見日と発表日の分離）。「尽きた」だけを求める検索では判別できない |
| Show HN の加速と撤退（53 行）、消失か希釈か（54 行） | 到達率の集計 | 一人称では決着しない（集計） |

予測 1（concepts 78 行）は「初期の枯渇証言は AI 協働を嫌う人でなく好む人から出る（判別質問 1 が『楽しい』側）」、予測 2（79 行）は「剥奪型・dread 型の続報が防衛線の崩壊とともに枯渇型へ転じる」。どちらも一人称の時系列で検証する形。

**5.4 測定器の限界**（concepts 150〜166 行。testimonies 13〜15 行）: 公開をやめた人は公開をやめたことも書かないので、一人称の収集は対象に近づくほど感度を失う（152 行）。testimonies 13 行は「非生計依存層の証言は検索語で釣れる場所には無い」、15 行は「釣れる語彙は『枯渇』でなく『公開・共有・見せる』の側だった」と記す。

台帳の型（testimonies 34 行）: 枯渇の告白 / 剥奪 / 空洞化・手応え喪失 / 無用化 dread / 受け手の消失（**告白**と**分析**を区別）/ 公開の停止 / 対照例（在庫あり側）。採録規律（36〜39 行）は、判別質問に答えられる引用を残し、答えられない証言は型を確定せず「未判別」で置く。

## Contradictions

1. **現行の問いは「尽きた」型だけを求めるが、concepts.md は隣接機構の判別を前提にしている。** `questions/desire.md` 3〜18 行の題・brief・`evidence`・クエリは「AI に頼みたいことが尽きた」型の収集と追跡だけを求める。concepts.md は枯渇を中心対象（58 行）としつつ、受け手の消失・公開の停止・剥奪・空洞化を判別すべき隣接機構にし（50〜67 行）、現行の判別質問 3 問は「作っているが見せていない人」を「枯渇ではない」に分類して情報を捨てる、と書く（46 行）。台帳の採録規律も質問 1〜4 の答えを残すよう求める（testimonies 38 行）。どちらが正かは「著者が問いを持つ」ので plan 側の判断だが、食い違いは実在する。
2. **現行のクエリの語彙と、台帳が見つけた「釣れる語彙」が逆。** desire.md のクエリは「作りたいものがなくなった」「lost motivation what to build next」の枯渇語彙だけ（15〜18 行）。testimonies 13・15 行は、非生計依存層は検索語で釣れず、釣れたのは「公開・共有・見せる」の側と記す。lead の試し打ち F と notes の WebSearch も、枯渇語彙では一人称に当たらなかった。
3. **notes の推す経路と、lead の probe B の組み合わせ。** notes は Zenn `ポエム` topic と note の小さいタグを日次の poll に合う経路として推す。だが lead の probe では、エッセイ類は screening で drop（evidence_strength = asserted）。probe 版の 1 文は「日付か具体的な出来事つきで、本人が起きたことを一人称で書いた資料」だけを `measured` に上げる。**随筆の量を増やしても、具体的な経緯の無い随筆は通らない**。経路の追加と screening の言い回しは組で効く。
4. **notes の「`feed:` で入る」は、条件つきで正しい。** 窓は 3 日（`feed.py:47`）、`Follow` は 1 feed 1 run 10 件（`feed.py:51`）、feed と別 host の item は feed の本文を捨ててページを読む（`feed.py:116-117`、hnrss 経由の HN と、はてブ検索がこれに当たる）、note のページを regex の `article_parse` が読めるかは未確認（`page.py:3-5, 13-15`）。さらに feed の item は本文が短くても「未完」にならず screening に進む（`question_screening.py:236-237`）。ページを読めなかった item は、本文が空のまま判定に行く可能性がある（コード読みで、実行は未）。
5. **notes の sriram_malhar の読みが、再取得の要約と食い違う。** §1 に書いた。notes は過程に結びついた欲望（在庫でもフローでもない第 3 の型）、再取得の要約は「教える相手・過程を気にする相手の不在」も含む。どちらも小モデルの要約で、原文未確認。スレッドの規模も notes は「4 コメント」、再取得は「top-level 1」（ネストの数え方の差かもしれない）。
6. **CERQual の「落とさず確信を下げる」と jrp の trust は別物。** trust は accept でなければ次の段に進めない hard gate（`run.py:845-852`）で、重みづけで通す形ではない。一方 screening の 3 つの gate（`on_topic` `method_transferable` `evidence_compatible`）も落とすだけだが、位置づけは重みの合計（`question_screening.py:216-231`）。**一人称の資料を重み付きで通す仕組みは、現状 screening の中にあり、trust にはない。**
7. **週報の「I 入口」は原因の段とずれる（記述と実物の食い違い）。** `note_text.py:590-591` は「I 入口 (screening に届いた対が 0)」、`AGENTS.md:154` は「止まった問いの段が I 入口ならクエリを skill `jrp-question` で差し替え（agent だけで進む）」と書く。実物は、`wbr.py:1095-1110` が screening の Judgment を持つ資料の数を数え、0 なら `wbr.py:824-839` の `stopped` が最初に 0 になった段として「screening」を返す。triage と trust で落ちた対は screening の Judgment を持たないので、取得と prefilter を通っても「I 入口」と出る（lead の E）。desire のように落ちたのが trust のときも、手順はクエリの差し替えに向かう。
8. **台帳側の記述が古い。** testimonies.md 14 行は「この日から desire line は 6 日周期（次回 2026-08-25）」と書くが、lead の G では今のラインの毎日実行は `[tracks.desire]` の `daily = true`（旧 pipeline と共有の config.toml、gitignore）で、`pipeline/config.py:97, 111` が daily の track を rotation から外す。また testimonies.md 41 行の見出しは「2026-08-17 時点」だが、53〜54 行は 08-19 の追記を含む。

## Local evidence

出典: lead の実行（2026-10-26）。すべて本番 store の写し（APFS の複製、2026-10-26 21:09）と `jrp eval gate freeze` で凍結した評価集合 `sx`（S 対 51,903、X line-day 67）の上。本番の store は読むだけ。**数値 A〜G は lead の実測で、この report では再計算していない**。`file:line` は Read で確かめた。

### 再現（lead が実行した結果、手順は AGENTS.md「選別と根拠化の候補を比べる（gate eval）」と同じ形）

1. store の写しを作る → `JRP_STORE_DIR=<写し> jrp eval gate freeze` で集合 `sx` を凍結。
2. A: 凍結集合の、一次ふるい prefilter を通った対のうち、triage か trust で落ちた数。
   - desire/after-exhaustion-firsthand: 3 → 3（3 件とも source_trust）。aap/accountability-locus 45 → 32、edge/collapse-postmortems 27 → 15、edge/self-written-rule-bypass 41 → 26、ans/attention-not-self 53 → 33。動いている問いの損失は約 3%。
   - ライン横断で keep になった対は 1,583 中 14。ans・authorship・desire を含むものは 0。novelty の changes_answer はどの問いでも 0〜10%。claim の根拠になった資料の本文の長さの中央値は 1,500〜1,670 字（要旨の水準）。
3. B: desire の probe（凍結 state を Jev に聞き直した。費用はほぼ 0）。
   - trust ゲートだけを外す: Gizmodo（prefilter の関連性 0.73、trust 0.29、personal の確率 0.87）は screening で review（重み付き点 0.55、evidence_strength = anecdote）。「きしだのHatena」の記事は drop（0.41）。エッセイ類は drop（asserted）。
   - screening の ASK.instructions に次の 1 文（probe 版 v4probe）を足す: Gizmodo は keep（0.66、evidence_strength = measured）。他は変わらず。
     > When `question.evidence` asks for a first-person account, a source in which its author describes in the first person, with dates or concrete events, what happened to them is the primary record of that account: its evidence_strength counts as `measured`.
   - probe の 1 回ごとに Jev の失敗が約 1/16。screening の重み付き点 = 0.5·overlap + 0.3·evidence_strength + 0.2·novelty、keep 0.6、review の幅 0.1。
4. C: unjudged（Decision の outcome = unjudged）の残り。「10-12 以降」は subjects の先頭の資料の fetched_at が 2026-10-12 以降のもの。
   - aap 38（question_screening 30、claim_detection 6、rubric_claim 2）、10-12 以降 22 件・資料 9。akc 158（screening 138 ほか）、8・5。authorship 54（screening 42、source_trust 4 ほか）、29・14。desire 7（screening 4、source_trust 2、rubric_claim 1）、5・3。edge 21、12・5。jev 65、24・11。contemplative 102（すべて screening、10-12 以降 0）。ans 1、claude-code 5。
   - aap では hearsay を扱う論文が 2 回 unjudged になり、その後一度も判定されていない。aap で unjudged を持つ対 13、うち 6 は一度も判定なし。
5. D: 判定役の質（silver label、Claude API の Opus が 240 件、$1.56）。Jev の keep の precision 88〜100%。review 帯の下側 9/30 が「yes」、上側 6/30。claim の足切りで切られた 9/40 と掲載された 8/30 が同程度。
6. E: 週報 W43 で問い 25 本中 9 本が止まった。「I 入口 (screening に届いた対が 0)」と出るが、desire などは取得と prefilter を通っていて、落ちたのは triage / trust。
7. F: 現行のクエリの `jrp queries check`。`web: AIで作りたいものがなくなった` の上位は X の話題・note の kota の記事・アベプラ。`web: AI coding agents lost motivation what to build next` の上位は DEV の tips・HN dokdev・SO blog の decision fatigue。`arxiv:` / `hf:` は論文で一人称はほぼ入らない。
8. G: launchd の job は `com.shimo4228.jrp.run` だけ。ラインの毎日実行は `[tracks.desire]` の `daily = true`。

### 原因（`file:line` と、その行が原因だと言える根拠）

desire の問い `after-exhaustion-firsthand` が 5 週間動かなかった連鎖。

1. **供給が薄い。** prefilter は問いの title・brief・not だけを見て（`question_prefilter.py:64-69`）、`on_topic` 0.5 で通す（`question_prefilter.py:24`）。通った対は凍結集合で 3 件。うち lead の probe B で問いに合うと読めたのは Gizmodo の 1 件で、きしだの記事とエッセイ類は trust を外しても drop。つまり trust の損失は「5 週間に 1 件」の規模で、同じ期間に prefilter を通る資料自体が 3 件しかない。クエリ（F）が一人称に当たらないことが、供給の細さの側の原因。
2. **trust が personal を落とす。** `Trust.personal`（named author の個人ブログ、参照が少ない）は 4 段の下から 2 番目（`source_trust.py:18-29`）、位置は 1/3（`nodes.py:361-364`）、`min_trust` 0.5（`source_trust.py:50`）、rule は位置 ≥ 0.5（`source_trust.py:68-72`）。一人称の個人ブログは構造的に落ちる。trust の state は資料だけで問いを含まない（`source_trust.py:58-59`）。`_safe_sources` も「問いに依らない pass」（`run.py:833-835`）で、triage の state は line と資料（`run.py:838`）。trust で accept でない資料は screening に行かない（`run.py:845-852`）。Gizmodo は trust 0.29（lead B）。
3. **通っても evidence_strength が一人称を `anecdote` に置く。** `EvidenceStrength` の 4 段は asserted / anecdote（「One example, demo or story」）/ measured（「measures something … or is the primary record of what it describes」）/ compared（`question_screening.py:73-84`）。フィールドの説明は「`question.evidence` が primary source を名指していて資料がそれなら `measured`」とだけ言い（`question_screening.py:119-126`）、一人称の記録は含まない。現行の `evidence: 一人称の記述。二次的な評論は弱い`（desire.md 12 行）は、この段を持ち上げない。
4. **重みの算術（`question_screening.py:150-161, 224-231, 264-278` から本 report が計算。実行ではなく、実際の点は確率重みで連続）。** overlap と evidence_strength は 4 段で位置 0・1/3・2/3・1、novelty は 3 段で 0・1/2・1。keep 0.6、帯 0.1 なので、0.5 未満が drop、0.7 以上が keep、0.6〜0.7 は certainty ≥ 0.5 なら keep、0.5〜0.6 は review。
   | evidence_strength | overlap | novelty | 点 | 行き先 |
   |---|---|---|---|---|
   | anecdote（0.10 点） | same_question（0.50） | same_as_known / adds_detail / changes_answer | 0.60 / 0.70 / 0.80 | keep（0.60 は certainty しだい） |
   | anecdote | same_problem（0.33） | same_as_known / adds_detail / changes_answer | 0.43 / 0.53 / 0.63 | drop / review / keep |
   | anecdote | same_field（0.17） | 最大 | 0.47 | drop |
   | measured（0.20 点） | same_problem | same_as_known / adds_detail / changes_answer | 0.53 / 0.63 / 0.73 | review / keep / keep |
   | measured | same_field | 最大 | 0.57 | review |
   `anecdote` のままだと、keep に届くのは overlap が same_question の資料か、same_problem で novelty が changes_answer の資料だけ。novelty の changes_answer は lead の A でどの問いも 0〜10%。lead の probe の 1 文が `measured` に上げると、same_problem で adds_detail の資料が review から keep に移る。Gizmodo の実測（0.55 → 0.66）と向きが合う。
5. **週報が段を取り違える。** §Contradictions の 7。`wbr.py:1095-1110`、`wbr.py:824-839`、`note_text.py:590-594`、`AGENTS.md:154`。desire では「クエリを直す」に向かう。
6. **書き手と screening が見る問いの欄は違う。** screening は title・brief・method・evidence・not（`question_screening.py:176-182`）、prefilter は title・brief・not（`question_prefilter.py:66`）、書き手は title と brief だけ（`generation/prose.py:312-318`）。問いの判別軸（在庫 / フロー、受け手）を method や evidence にだけ書くと、書き手には届かない。

### 確認（Read した箇所と、lead の結果との突き合わせ）

- Read して行番号を確かめたファイル: `jev/source_trust.py`（全体）、`jev/question_screening.py`（全体）、`jev/question_prefilter.py`（grep）、`jev/core.py`（52-67、100-170、255-285、605-680、740-851）、`pipeline/run.py`（1-40、205-300、595-625、663-790、785-860、935-960、1315-1360。`same_title_merged` は 502-530）、`pipeline/nets.py`（575-630）、`model/nodes.py`（166-198、361-364、465-525、667-706）、`store/graph.py`（35-85）、`evals/gate_policy.py`（49-59、195-240）、`evals/gate_score.py`（1-80）、`generation/prose.py`（295-335）、`note_text.py`（580-605）、`pipeline/wbr.py`（815-850、1070-1120）、`pipeline/config.py`（56-112）、`questions.py`（1-190）、`adapters/feed.py`（全体）、`adapters/base.py`（366-402）、`adapters/page.py`（1-53）、`cli.py`（grep）、`report/markdown.py:120-126`。
- lead の指定した行から実物でずれたもの: `wbr.py` の `stopped` は 824-839（指定は 825-840）、`gate_policy.py` の `s_outcome` は 210-231 で trust の再生は 219-227（指定は 209-227）、`nodes.py` の `Decision` は 476-506（指定は 476-503）、`run.py` の `_gather` は 1328-1348。ほかの指定（`source_trust.py` 18-29・50・53-55・68-72、`run.py` 13・217-294・608-612・793-831・833-853、`nets.py` 593-626、`graph.py` 55、`prose.py` 312-318、`note_text.py` 590-594、`questions.py` 1-47・65-87・147-174）は一致した。
- 重複除去は 1 回の run の中だけ: `nets.py:593`（`seen`）、`619`（`fresh` の絞り込み）、`623`（更新）。`same_title_merged` も「Within a run only」（`run.py:517`）。store にある資料を除く処理は `nets.py` に無い（`known` / `store` の語での grep は 0 件）。
- Decision の id は function・subjects・policy・bundle_sha256 で outcome と thresholds を含まず（`nodes.py:500-506`）、`put` は同じ @id を置き換える upsert（`graph.py:55-61`）。再判定で同じ id の Decision が置き換わるという lead の C の仕組みは、コードで確かめた。

### 動かせる箇所と効く範囲（コード読み。実行は未）

(2) 情報源ゲートと (3) unjudged の再試行に効く、各ノブの所在と波及。

- **`min_trust`**（`source_trust.py:50`）: 全ラインに効く。offline で測れる — gate eval の候補 TOML は `[thresholds.<function>]` で `DEFAULTS` のどの関数のどの名前も差し替えられ（`gate_score.py:7`）、`source_trust` は `DEFAULTS` に入っている（`gate_policy.py:53`）。閾値は保存済みの Judgment から再計算するので 0 円（`gate_score.py:14`）。ただし trust で落ちた対は screening の Judgment を持たず、`s_outcome` は「unasked」を返す（`gate_policy.py:228-230`）ので、offline で分かるのは「新しく screening に届く対の数」まで。その後の keep / review は Jev に聞き直す必要がある（lead の probe B がやったこと）。
- **trust の ASK の言い回し・`Trust` の段の説明**: `Ask.sha256` は function・version・instructions・schema・levels・wire のハッシュで（`core.py:109-128`）、Judgment の id（`run.py:235`）と Decision の id（`nodes.py:500-506`、`core.py:834-839`）に入る。言い回しを変えると**全ラインの trust の Judgment と Decision が新しい id になり**、再取得された資料は聞き直しになる。古い id の Decision は残る。
- **問いごとの trust の床**: 現行のコードに無い。trust の state は資料だけ（`source_trust.py:58-59`）、閾値は module 定数（`source_trust.py:50`）。
- **screening の ASK / `evidence_strength` の言い回し**（probe 版の 1 文の置き場）: 同じく全ラインの screening の id が変わる。stored の screening が replay されなくなり、unjudged の古い Decision は旧 id のまま取り残される（再取得の聞き直しは新 id に書く）。**(3) の unjudged を先に再試行してから言い回しを変える順なら、取り残しは出ない**（コード読みの帰結。順序は plan 側の判断）。
- **問いの書き換え**: 問いの文面を変えると `version` を上げる運用で、`version` は @id の一部なので、古い文面は古い node と古い Judgment を持ったまま残る（`nodes.py:667-676, 703-705`）。`evidence`（採った claim の @id）は同じ @id の中で伸びる。screening の subjects は (資料, 問い) なので、書き換えた問いは screening が新規になるが、trust と triage の Judgment は問いに依らないので **store から replay される**（`run.py:235-238`）。prefilter は line の全問いを 1 回の ask で聞く（`run.py:801-802`、`question_prefilter.py:53-69`）ので、desire の 3 問のどれかの title・brief・not を変えると 3 問分の prefilter の入力が変わる。
- **unjudged の再試行**:
  - 失敗の扱い: transient（408・429・5xx・timeout・connection）は 1 回だけ 2 秒待って再送し（`core.py:59-60, 618-630, 650, 664`）、それでも失敗するか、`bad_answer`（`core.py:657-658`）なら JevFailure（`core.py:259-266`）になり、`_decide` が unjudged の Decision を記録する（`run.py:608-612`）。triage か trust が unjudged だと、その資料は screening に進まない（`run.py:843, 851`。`nodes.py:479-481` の「never fails open」）。
  - 再試行の入口: 再取得された資料だけが聞き直される（`StoredJev.judge` は同じ Judgment id の hit だけ返す: `run.py:235-238`。失敗は Judgment を残さない）。feed の資料は 3 日窓の間は毎日再取得される（`feed.py:47-50`）。arXiv・OpenAlex の論文は検索結果に再び出るまで残る（lead C の aap の hearsay 論文）。
  - store だけで再試行する道: `SourceItem` は text・fetched_at・published_at を持つ node（`nodes.py:166-197`）で、trust と triage の state は資料だけから作れる（`source_trust.py:58-59`）。聞き直して upsert すれば Decision が置き換わる（`nodes.py:500-506`、`graph.py:55-61`）。screening の state は `evidence_set` と line の語彙を含む（`question_screening.py:171-185`）ので、再構成した state は当時と一致しない（新しい Judgment になる）。**この再試行を行う CLI は無い**（サブコマンドは `cli.py:126-211`。run・doctor・init・schedule・notify・questions・try・fit・export-cases・drift・migrate・wbr・queries・prose・codex・eval）。
  - 失敗の理由は store に残らない: `Decision` に reason の欄が無く（`nodes.py:484-498`）、`UnjudgedEntry` は function と text だけ（`report/markdown.py:120-126`）。timeout か bad_answer かは、再試行を実行して初めて分かる。
  - 「probe 1 回ごとに約 1/16 が FAIL」（lead B）は、失敗が入力によらず一定なら再試行の成功率が高い目安になる。aap の hearsay 論文が 2 回失敗して以後判定されていない（C）のは、入力に固有の失敗の可能性がある。どちらかは未確認。

## Still unknown

notes から:
- Reddit の search / subreddit RSS の形と制限（この環境の WebFetch が reddit.com を拒否）。r/ClaudeAI・r/ChatGPT に一人称の証言が多いかも未確認。手元の `curl` で確かめられる。
- note の非公式検索 API が jrp の httpx（UA と間隔つき）で通るか。note のハッシュタグ feed が全投稿か選別の一部か（`#作りたいもの` の 25 件が 25 か月に渡る）。日次の poll に合う大きさのタグはどれか。note の description の中身。
- hnrss.org の 502 が一時的か。HN Algolia の公式レート上限（doc が JS 描画で読めず）。
- はてなブックマーク検索 RSS が語に合う item を返すか（先頭 14 件に語が見えなかった）。
- 「AI に頼みたいことが尽きた」と明確に書いた一人称の記事は 1 件も見つかっていない。日本語の長い尾が空なのか、WebSearch の限界なのか分からない。
- 一人称の記事の AI 生成の割合、日本語の一人称記事での AI 検出の精度。日本のステマ規制。
- Verification Handbook・Admiralty code は snippet のみ。CERQual の 2018 シリーズ（方法論上の限界・十分さ・関連性）の本文は未読。
- sriram_malhar の 2 時点は 1 人分。ほかの人で「尽きた → 数か月後の欲望」を追える経路は、HN の `author_<user>` 以外では未確認。引用はすべて小モデルの要約で、原文未確認。

lead の実測で答えが出ていないこと:
- **trust の床を下げたとき、他ラインの問いで何が通るか**。offline で「新しく screening に届く対の数」までは 0 円で測れる（gate eval の候補 TOML。`[thresholds.source_trust] min_trust = …`）。その先の keep / review は Jev への聞き直しが要る。desire だけの probe（B）は、他ラインに波及する値の根拠にならない。
- 一人称の資料が trust を通るようになったとき、トレードオフの反対側 — anonymous / promotional ページ（trust の最下段）が通るか。probe B は desire の 3 件だけ。
- desire の 3 件のうち問いに合う 1 件（Gizmodo）の他に、`jrp queries check` で一人称に当たるクエリがあるか。F は現行のクエリだけで、`feed:`（Zenn `ポエム`、note のタグ）の試し打ちは未実施。note の本文を `Follow` が読めるか（`page.py` の regex）も未確認。
- unjudged の失敗の理由の内訳（timeout / connection / api_error / bad_answer）。store に残っていない。再試行を 1 回実行すると分かる。
- 台帳の項目が実際に一人称 1 本で決着するか（特に「社会的回路が太いのに枯渇した」「AI 関与を伏せた自作への反応」）。本文にその記述が出る頻度は未確認。
- desire の問いを書き換えたあと、`version` を上げたときの prefilter の再判定の費用（desire は 3 問で、費用は小さいと見込まれるが、測っていない）。

"""Every fixed text the note writes, in each note language (plan productize-en-zh P1).

JRP_NOTE_LANG = ja | en | zh picks the language of the note's headings, its operations
section and the empty-day sentence (default ja, the author's notes). The machine-read parts
of a note do not change with it: the three `<!-- jrp:… -->` marks are the same in every
language (report.vault reads only the marks), so a tick is harvested the same way from a
note in any language.

One Msg per text, the three languages side by side: a text added in one language and not
the others does not type-check, and tests/test_note_text.py checks that the three carry the
same `{placeholders}`. Third-party text (claims, titles, prose) never goes through here.
"""

from collections.abc import Mapping
from typing import Final, Literal, NamedTuple, get_args

type Lang = Literal["ja", "en", "zh"]
LANGS: Final[tuple[Lang, ...]] = get_args(Lang.__value__)
NOTE_LANG_ENV: Final = "JRP_NOTE_LANG"
DEFAULT_LANG: Final[Lang] = "ja"


class BadNoteLang(ValueError):
    pass


def note_lang(env: Mapping[str, str]) -> Lang:
    """The note language. A value other than ja / en / zh stops the run at the start (a
    note in a language nobody asked for is worse than no note)."""
    raw = env.get(NOTE_LANG_ENV) or DEFAULT_LANG
    for lang in LANGS:
        if raw == lang:
            return lang
    raise BadNoteLang(f"{NOTE_LANG_ENV} must be one of {', '.join(LANGS)}: {raw!r}")


class Msg(NamedTuple):
    ja: str
    en: str
    zh: str

    def __call__(self, lang: Lang, /, **values: object) -> str:
        return self.raw(lang).format(**values)

    def raw(self, lang: Lang) -> str:
        """The text as written, braces and all (prompts that are not templates)."""
        return {"ja": self.ja, "en": self.en, "zh": self.zh}[lang]


# --- note structure (report.markdown) -------------------------------------------------------

TOPIC: Final = Msg("{line} — {n} 問い", "{line} — {n} questions", "{line} — {n} 个问题")
CHANGES: Final = Msg("今日の変化", "What changed today", "今日变化")
EVIDENCE: Final = Msg("証拠", "Evidence", "证据")
COUNTER_EVIDENCE: Final = Msg("反証", "Counter-evidence", "反证")
WORTH_READING: Final = Msg("読む価値があった", "Worth reading", "值得一读")
TEMPLATE_BODY: Final = Msg(
    "本文生成なし (template)。証拠だけを挙げる。",
    "No prose generated (template). Evidence only.",
    "未生成正文 (template)。仅列出证据。",
)
# Titles of the folded callouts after the reading surface (one per non-empty list).
REVIEW: Final = Msg(
    "Review — 境界の資料 {n} 件", "Review — {n} borderline sources", "Review — 边界资料 {n} 条"
)
BRIDGES: Final = Msg("橋渡し — {n} 件", "Bridges — {n}", "桥接 — {n} 条")
CLAIMS: Final = Msg("Claims — {n} 件", "Claims — {n}", "Claims — {n} 条")
UNJUDGED: Final = Msg("未判定 — {n} 件", "Unjudged — {n}", "未判定 — {n} 条")
OPERATIONS: Final = Msg("運用", "Operations", "运行")
NOTHING_MOVED: Final = Msg(
    "今日動いた問いはない。{why}", "No question moved today. {why}", "今天没有问题出现变化。{why}"
)
EMPTY_DAY: Final = Msg(
    "取得 {fetched} 件のうち、問いに関係しそうな (source, 問い) 対が {pairs}{routes}、"
    "採用された claim が {claims} 件。{tail}",
    "Of {fetched} sources fetched, {pairs} (source, question) pairs looked relevant{routes}; "
    "{claims} claims were accepted.{tail}",
    "共获取 {fetched} 条，可能与问题相关的 (source, 问题) 对 {pairs} 个{routes}，"
    "采纳的 claim {claims} 条。{tail}",
)
RATE_LIMITED_TAIL: Final = Msg(
    " {nets} は rate limit で打ち切り。",
    " {nets} stopped at a rate limit.",
    " {nets} 因 rate limit 中止。",
)
REVIEW_REASON: Final = Msg("「{question}」: {why}", '"{question}": {why}', "「{question}」: {why}")

# --- operations section: the run (pipeline.run, pipeline.runner) ----------------------------

JEV_QUESTIONS: Final = Msg(
    "Jev 質問数: {n} (token: in {tokens_in} / out {tokens_out})",
    "Jev questions: {n} (tokens: in {tokens_in} / out {tokens_out})",
    "Jev 问题数: {n} (token: in {tokens_in} / out {tokens_out})",
)
GENERATION_TOKENS: Final = Msg(
    "生成 token ({spec}): in {tokens_in} / out {tokens_out}",
    "Generation tokens ({spec}): in {tokens_in} / out {tokens_out}",
    "生成 token ({spec}): in {tokens_in} / out {tokens_out}",
)
WRITER_CALLS: Final = Msg(
    "書き手の呼び出し: {n} ({spec})", "Writer calls: {n} ({spec})", "写作模型调用: {n} ({spec})"
)
# The cost line names what Budget.cost adds up for the writer at hand: Jev alone when the
# writer is on a subscription (its tokens price 0), Jev plus the writer's tokens otherwise.
COST_JEV_ONLY: Final = Msg(
    "Jev 推定費用: ${cost} (仮定単価。書き手はサブスクで 0)",
    "Jev estimated cost: ${cost} (assumed price; the writer is on a subscription, 0)",
    "Jev 估算费用: ${cost} (假定单价。写作模型为订阅，计 0)",
)
COST_WITH_WRITER: Final = Msg(
    "推定費用: ${cost} (Jev の仮定単価 + 書き手の token 代)",
    "Estimated cost: ${cost} (Jev at its assumed price + the writer's tokens)",
    "估算费用: ${cost} (Jev 假定单价 + 写作模型的 token 费)",
)
JEV_PRICE_UNSET: Final = Msg("Jev 単価未設定", "Jev price not set", "未设置 Jev 单价")
GENERATION_PRICE_UNSET: Final = Msg("生成単価未設定", "generation price not set", "未设置生成单价")
FILL_RATE: Final = Msg(
    "記入率 (前回・問い日): {rate}",
    "Fill rate (previous run, question-days): {rate}",
    "填写率 (上次・问题日): {rate}",
)
FILL_RATE_NONE: Final = Msg(
    "記入率 (前回): なし", "Fill rate (previous run): none", "填写率 (上次): 无"
)
USED_RATE: Final = Msg(
    "used rate ({days} 日): {used} / {decided} = {rate} · 判定不能 {unknown}",
    "Used rate ({days} days): {used} / {decided} = {rate} · undetermined {unknown}",
    "used rate ({days} 天): {used} / {decided} = {rate} · 无法判定 {unknown}",
)
USED_RATE_NONE: Final = Msg(
    "used rate ({days} 日): 測定中 (窓が閉じたソース 0 件 · 待機 {pending} · 判定不能 {unknown})",
    "Used rate ({days} days): measuring (no source past its window yet"
    " · waiting {pending} · undetermined {unknown})",
    "used rate ({days} 天): 测量中 (尚无窗口已关闭的来源 · 等待 {pending} · 无法判定 {unknown})",
)
USED_UNREAD: Final = Msg(
    " · 未読 {n} 件 (iCloud 未取得など。見つからなかった結果は暫定)",
    " · unread {n} files (iCloud not downloaded etc.; absences are provisional)",
    " · 未读 {n} 个文件 (iCloud 未下载等；未找到的结果为暂定)",
)
USED_CAPPED: Final = Msg(
    " · scan は上限 {seconds} 秒で打ち切り",
    " · scan stopped at its {seconds} s cap",
    " · 扫描在 {seconds} 秒上限处中止",
)
OPEN_QUESTIONS: Final = Msg("open な問い: {n} 件", "Open questions: {n}", "开放问题: {n} 个")
RUBRIC_AXIS: Final = Msg(
    "rubric {axis}: 平均 {mean}", "rubric {axis}: mean {mean}", "rubric {axis}: 平均 {mean}"
)
RUBRIC_NO_DATA: Final = Msg(
    "rubric {axis}: データなし", "rubric {axis}: no data", "rubric {axis}: 无数据"
)
JEV_RETRIES: Final = Msg(
    "Jev 再試行: {n} 回 (一時的な失敗を 2 秒後に 1 回)",
    "Jev retries: {n} (one retry 2 s after a transient failure)",
    "Jev 重试: {n} 次 (临时失败后 2 秒重试 1 次)",
)
PAIR_FAILURES: Final = Msg(
    "(source, 問い) 対の Jev 失敗: {failed} / {pairs} ({share}); full screen {screened} 対",
    "Jev failures on (source, question) pairs: {failed} / {pairs} ({share}); "
    "full screen {screened} pairs",
    "(source, 问题) 对的 Jev 失败: {failed} / {pairs} ({share}); full screen {screened} 对",
)
NO_TEXT: Final = Msg(
    "本文なし: {n} 件 (screening 対象外)", "No text: {n} (not screened)", "无正文: {n} 条 (未筛选)"
)
STAGE_TIMES: Final = Msg("段の所要: {times}", "Stage times: {times}", "各阶段耗时: {times}")
PARTIAL: Final = Msg(
    "partial: 費用上限に達したため以降の判定を省略",
    "partial: the cost cap was reached, later judgments skipped",
    "partial: 已达费用上限，后续判定省略",
)
TITLE_DUPLICATES: Final = Msg(
    "同じタイトルの重複 {n} 件を 1 件にまとめて判定",
    "{n} same-title duplicates judged as one",
    "{n} 条同标题重复合并为 1 条判定",
)
CLAIMS_SHOWN: Final = Msg(
    "{question}: claim {total} 件のうち {shown} 件を掲載",
    "{question}: {shown} of {total} claims shown",
    "{question}: {total} 条 claim 中刊载 {shown} 条",
)
NOTE_CAP: Final = Msg(
    "note 12 KB (本文を除く) のため省略: Review {n} 件",
    "Note over 12 KB (prose excluded): {n} Review items left out",
    "笔记超过 12 KB (不含正文): 省略 Review {n} 条",
)
KEY_UNSET: Final = Msg(
    "{kind}: key 未設定のため skip", "{kind}: skipped, key not set", "{kind}: 未设置 key，跳过"
)
QUERIES_UNSET: Final = Msg(
    "query 未設定: {question} (questions/{line}.md に query 行が無い)",
    "No queries: {question} (questions/{line}.md has no query lines)",
    "未设置 query: {question} (questions/{line}.md 中没有 query 行)",
)
QUERIES_USED: Final = Msg(
    "query: 問いファイルの {n} 件を使用",
    "query: {n} from the question file",
    "query: 使用问题文件中的 {n} 条",
)
QUERY_UNUSABLE: Final = Msg(
    "query: 検索語にならない行を skip ({text})",
    "query: skipped a line that is not a search query ({text})",
    "query: 跳过无法作为检索词的行 ({text})",
)
REVIEW_CAP: Final = Msg(
    "Review: {total} 件のうち境界に近い {shown} 件を表示",
    "Review: the {shown} nearest the cut of {total}",
    "Review: {total} 条中显示最接近阈值的 {shown} 条",
)
BRIDGES_CAP: Final = Msg(
    "橋渡し: {pairs} 対が閾値を超え、確率上位 {shown} 件を表示",
    "Bridges: {pairs} pairs over the bar, the {shown} likeliest shown",
    "桥接: {pairs} 对超过阈值，显示概率最高的 {shown} 条",
)
DRAFT_WRITTEN: Final = Msg("生成", "written", "已生成")
DRAFT_FAILED: Final = Msg("失敗 ({why})", "failed ({why})", "失败 ({why})")
DRAFT: Final = Msg(
    "{question} prose 第{i}稿: {state} {seconds}s",
    "{question} prose draft {i}: {state} {seconds}s",
    "{question} prose 第{i}稿: {state} {seconds}s",
)
BAD_CITATIONS: Final = Msg(
    "{question}: 存在しない引用 [{cited}] を削除",
    "{question}: removed citations of no claim [{cited}]",
    "{question}: 删除不存在的引用 [{cited}]",
)
CANARY_UNJUDGED: Final = Msg(
    "canary 未判定 (費用上限): {question} / {url}",
    "canary unjudged (cost cap): {question} / {url}",
    "canary 未判定 (费用上限): {question} / {url}",
)
CANARY_QUIET: Final = Msg(
    "canary 未取得: {label} ({kind} は本日 rate limit)",
    "canary not fetched: {label} ({kind} is rate-limited today)",
    "canary 未获取: {label} ({kind} 今日已触发 rate limit)",
)
CANARY_FAILED: Final = Msg(
    "canary 取得失敗: {label} ({why})",
    "canary fetch failed: {label} ({why})",
    "canary 获取失败: {label} ({why})",
)
CANARY_NOT_HTTPS: Final = Msg("https でない URL", "not an https URL", "非 https URL")
CANARY_NOT_INDEXED: Final = Msg(
    "OpenAlex 未収録 (索引待ち)",
    "not in OpenAlex yet (awaiting indexing)",
    "OpenAlex 尚未收录 (等待索引)",
)
CANARY_EMPTY: Final = Msg("取得結果なし", "nothing came back", "无获取结果")
CANARY_DROPPED: Final = Msg(
    "canary 落下: {question} / {url}",
    "canary dropped: {question} / {url}",
    "canary 落选: {question} / {url}",
)
# {labels} counts Label nodes, not checkboxes: a ticked question-day also labels the claims
# and sources it cites (report.vault), and every tick re-reads all the line's notes.
HARVEST: Final = Msg(
    "label 在庫 (累計、qday の伝播を含む): {labels} 件 / 取り消し {withdrawn} 件",
    "Label stock (cumulative, question-day ticks spread to what they cite): "
    "{labels} / {withdrawn} withdrawn",
    "label 库存 (累计，含 qday 的传播): {labels} 条 / 撤销 {withdrawn} 条",
)
STORE_MIGRATED: Final = Msg(
    "store: {path} を現行 schema に移行 ({detail})",
    "store: {path} migrated to the current schema ({detail})",
    "store: {path} 已迁移到当前 schema ({detail})",
)

# --- operations section: discovery (pipeline.nets, pipeline.meters) -------------------------

VALIDATION_SKIPPED: Final = Msg(
    "{source}: 検証落ちで {n} 件 skip",
    "{source}: {n} skipped (failed validation)",
    "{source}: {n} 条未通过校验，跳过",
)
OPENALEX_CAP: Final = Msg(
    "openalex: 1 日の credit 上限に達したため以降を省略",
    "openalex: the daily credit cap was reached, the rest skipped",
    "openalex: 已达每日 credit 上限，其余省略",
)
FETCH_FAILED: Final = Msg(
    "{source}: fetch 失敗 ({reason} {detail})",
    "{source}: fetch failed ({reason} {detail})",
    "{source}: fetch 失败 ({reason} {detail})",
)
RATE_LIMITED: Final = Msg(
    "{source}: rate limit のため本日は打ち切り",
    "{source}: stopped for today at a rate limit",
    "{source}: 因 rate limit 今日中止",
)
NOT_IN_OPENALEX: Final = Msg(
    "{source}: {work} は OpenAlex 未収録のため省略",
    "{source}: {work} skipped, not in OpenAlex",
    "{source}: {work} 未被 OpenAlex 收录，省略",
)
FIREHOSE_RANKED: Final = Msg(
    "firehose: 関連度順に上位 {room} 件 ({dropped} 件を省略)",
    "firehose: the {room} most relevant ({dropped} left out)",
    "firehose: 按相关度取前 {room} 条 (省略 {dropped} 条)",
)
FIREHOSE_CAP: Final = Msg(
    "firehose: 上限 {cap} 件のため {dropped} 件を省略",
    "firehose: {dropped} left out at the cap of {cap}",
    "firehose: 上限 {cap} 条，省略 {dropped} 条",
)
NONE_WORD: Final = Msg("なし", "none", "无")
# Per net, the sources that came back this run after the run's own dedupe and the firehose
# cap; a source already in the store from an earlier day counts again (not "new").
NET_SOURCES: Final = Msg(
    "取得 (run 内の重複除去・上限の後): {counts}",
    "Fetched (after the run's dedupe and the cap): {counts}",
    "获取 (run 内去重・上限之后): {counts}",
)
NET_SHARES: Final = Msg(
    "net 採用率: {shares}", "Accept share per net: {shares}", "各 net 采纳率: {shares}"
)
# The tick's DayBudget is shared by every line and the lines fetch side by side, so the
# value is the tick's running total when this line's fetch ended, not this line's spend.
OPENALEX_CREDITS: Final = Msg(
    "openalex credit (tick 累計の途中値): {n}",
    "openalex credit (the tick's running total so far): {n}",
    "openalex credit (tick 累计的中间值): {n}",
)

# --- Review reasons (jev.question_screening) ------------------------------------------------

BORDERLINE: Final = Msg(
    "境界: 重み付き {score} (採用線 {keep})",
    "borderline: weighted {score} (cut {keep})",
    "临界: 加权 {score} (采纳线 {keep})",
)
LOW_CERTAINTY: Final = Msg(
    "確信度不足: {sure} (< {floor})",
    "low certainty: {sure} (< {floor})",
    "置信度不足: {sure} (< {floor})",
)

# --- Instrument registry (pipeline.registry): the weekly review's status words --------------
# A number that is not live is shown as its status word instead of its value.

STATUS_LIVE: Final = Msg("live", "live", "live")
STATUS_EXPECTED_ZERO: Final = Msg("暦どおりの 0", "expected zero", "按日历的 0")
STATUS_DECLARED_DEGENERATE: Final = Msg("宣言済みの縮退", "declared degenerate", "已声明的退化")
STATUS_INSUFFICIENT_N: Final = Msg("データ不足", "too few readings", "数据不足")
STATUS_UNEXPLAINED_ZERO: Final = Msg("未説明の 0", "unexplained zero", "未解释的 0")
STATUS_STUCK: Final = Msg("値が動かない", "stuck", "数值不变")
STATUS_MISSING: Final = Msg("欠落", "missing", "缺失")
STATUS_CONTRADICTION: Final = Msg("矛盾", "contradiction", "矛盾")
DECLARED_CITATION_SEEDS: Final = Msg(
    "引用の種が新しすぎる (公開から数日の preprint は、まだ誰にも引用されていない)",
    "the citation seeds are too new (a preprint a few days old is cited by nobody yet)",
    "引用的种子太新 (发布才几天的 preprint 还没有被任何人引用)",
)
DECLARED_USED_VAULT: Final = Msg(
    "used の走査先は graph と ADR のみ (著者の決定 2026-10-20。本番の vault 経路は jrp の"
    "ノートだけの stage を読む)",
    "the used scan reads graph.jsonld and ADRs only (author decision 2026-10-20; in "
    "production its vault path is the stage, which holds only jrp notes)",
    "used 的扫描只读 graph 和 ADR (作者决定 2026-10-20。正式运行时 vault 路径读的是只有 "
    "jrp 笔记的 stage)",
)

# --- Weekly review (pipeline.wbr): the note `<date>_jrp_wbr.md` ------------------------------
# A number whose instrument is not live is shown as its STATUS_* word instead.

WBR_TITLE: Final = Msg(
    "jrp 週次レビュー {week} ({start}〜{end})",
    "jrp weekly review {week} ({start} to {end})",
    "jrp 周报 {week} ({start}〜{end})",
)
WBR_CONCLUSION: Final = Msg("0. 結論", "0. Summary", "0. 结论")
WBR_WORST: Final = Msg(
    "分解: 雑音を超えて最も下がった因子は {part} の {factor} (Δln {delta} ± {se})",
    "Breakdown: the factor that fell most beyond noise is {factor} of {part} (Δln {delta} ± {se})",
    "分解: 超出噪声、下降最多的因子是 {part} 的 {factor} (Δln {delta} ± {se})",
)
WBR_NO_WORST: Final = Msg(
    "分解: 雑音を超えて下がった因子は無い",
    "Breakdown: no factor fell beyond noise",
    "分解: 没有超出噪声而下降的因子",
)
WBR_NO_BREAKDOWN: Final = Msg(
    "分解: 比べられる成熟 cohort が 2 つそろわない",
    "Breakdown: there are not two mature cohorts to compare",
    "分解: 还没有两个可比较的成熟 cohort",
)
WBR_EXCEPTION_COUNT: Final = Msg(
    "例外: {n} 件 (2. 例外)", "Exceptions: {n} (section 2)", "例外: {n} 条 (2. 例外)"
)
WBR_INSTRUMENT_SUMMARY: Final = Msg("計器: {counts}", "Instruments: {counts}", "仪表: {counts}")
WBR_V0: Final = Msg(
    "v0 は分解までを出す。来週の 1 手は自動では選ばない (4. と 8. も v0 では出さない)",
    "v0 stops at the breakdown and does not pick next week's one change (sections 4 and 8 "
    "are not in v0)",
    "v0 只给出到分解为止，不自动选择下周的一手 (4. 与 8. 在 v0 中也不给出)",
)
WBR_OUTPUT: Final = Msg("1. 出力", "1. Output", "1. 产出")
WBR_O1_ROW: Final = Msg(
    "O1 本文で初めて引用された論文",
    "O1 papers first cited in the prose",
    "O1 正文中首次引用的论文",
)
WBR_O1_NOTE: Final = Msg(
    "論文は key (arXiv id・DOI・GitHub slug・正規化 URL)で数え、2 ラインが引用しても 1 本。"
    "ライン別は、その論文を初めての日に引用したライン。区間は Poisson 95% (Garwood)",
    "Papers are counted by key (arXiv id, DOI, GitHub slug, normalized URL), once however "
    "many lines cite them; a line's row counts the papers it cited on their first day. "
    "Intervals: Poisson 95% (Garwood)",
    "论文按 key (arXiv id・DOI・GitHub slug・规范化 URL)计数，两条线都引用也只算 1 篇。"
    "各线一行计的是在首次引用当天引用该论文的线。区间为 Poisson 95% (Garwood)",
)
WBR_O2: Final = Msg(
    "O2 著者の新出 key の先回り (graph と ADR のみ・上限寄り、直近 30 日): {value}",
    "O2 the author's new keys jrp cited first (graph.jsonld and ADRs only, an upper bound, "
    "last 30 days): {value}",
    "O2 作者新出现的 key 中 jrp 先引用的 (仅 graph 与 ADR・偏上限，最近 30 天): {value}",
)
WBR_MEASURING: Final = Msg("測定中", "being measured", "测量中")
WBR_O2_KN: Final = Msg(
    "{k}/{n} (n < 20 なので率は出さない)",
    "{k}/{n} (n < 20, so no rate)",
    "{k}/{n} (n < 20，不给出比率)",
)
WBR_O2_RATE: Final = Msg(
    "{rate} (Wilson {low}-{high}、{k}/{n})",
    "{rate} (Wilson {low}-{high}, {k}/{n})",
    "{rate} (Wilson {low}-{high}，{k}/{n})",
)
WBR_EXCEPTIONS: Final = Msg("2. 例外", "2. Exceptions", "2. 例外")
WBR_EX_INSTRUMENT: Final = Msg(
    "計器 {id}: {status} ({where})",
    "Instrument {id}: {status} ({where})",
    "仪表 {id}: {status} ({where})",
)
WBR_EX_QUESTION: Final = Msg(
    "動かない問い {line} / {question}: 止まった段 {stage}",
    "Question not moving {line} / {question}: stopped at {stage}",
    "未推进的问题 {line} / {question}: 停在 {stage}",
)
WBR_EX_LINE: Final = Msg(
    "O1 が 0 のライン: {line} (line-run {runs} 回)",
    "Line with O1 at 0: {line} ({runs} line-runs)",
    "O1 为 0 的线: {line} (line-run {runs} 次)",
)
WBR_BREAKDOWN: Final = Msg(
    "3. 分解 (成熟 cohort {old} → {new}、初取得から 7 日)",
    "3. Breakdown (mature cohorts {old} → {new}, 7 days from the first fetch)",
    "3. 分解 (成熟 cohort {old} → {new}，自首次获取起 7 天)",
)
WBR_GROUP_ALL: Final = Msg("全ライン", "All lines", "全部线")
WBR_GROUP_SLOT: Final = Msg(
    "枠律速 (空き枠 ≤ 30%): {lines}",
    "Slot-bound (free slots ≤ 30%): {lines}",
    "受版面限制 (空余 ≤ 30%): {lines}",
)
WBR_GROUP_SUPPLY: Final = Msg("供給律速: {lines}", "Supply-bound: {lines}", "受供给限制: {lines}")
WBR_GROUP_EMPTY: Final = Msg("該当するラインなし", "no line", "没有对应的线")
WBR_HEAD_BREAKDOWN: Final = Msg(
    "| パーツ | 因子 | {old} | {new} | Δln | ±SE |",
    "| Part | Factor | {old} | {new} | Δln | ±SE |",
    "| 部分 | 因子 | {old} | {new} | Δln | ±SE |",
)
WBR_SLOTS: Final = Msg(
    "空き枠 / 枠 ({week}): {slots}",
    "Free slots / slots ({week}): {slots}",
    "空余版面 / 版面 ({week}): {slots}",
)
WBR_SE_NOTE: Final = Msg(
    "SE は Poisson と二項の delta 法による暫定値 (同じ run・同じ問いの論文を独立とみなすので"
    "小さめに出る)。太字は |Δln| > 2SE。N_ot x p_sel x p_ext x p_wri = O1_c",
    "SE is a provisional delta-method value on Poisson counts and binomial shares (it treats "
    "papers of one run and one question as independent, so it reads small). Bold is "
    "|Δln| > 2SE. N_ot x p_sel x p_ext x p_wri = O1_c",
    "SE 为基于 Poisson 与二项分布 delta 法的暂定值 (把同一 run・同一问题的论文视为独立，"
    "因此偏小)。粗体为 |Δln| > 2SE。N_ot x p_sel x p_ext x p_wri = O1_c",
)
WBR_COHORT_NOTE: Final = Msg(
    "cohort の単位はライン x 論文、初取得は StageRecord(fetch_*) に初めて現れた日。各段は前の段の"
    "うち初取得から 7 日以内に届いたもの",
    "A cohort counts (line, paper) pairs by the day a StageRecord(fetch_*) first returned "
    "them; each stage counts the pairs of the stage before that reached it within 7 days "
    "of that day",
    "cohort 的单位是线 x 论文，首次获取为首次出现在 StageRecord(fetch_*) 中的日期。"
    "每一段计的是前一段中自首次获取起 7 天内到达的",
)
PART_M: Final = Msg("M 計器", "M instruments", "M 仪表")
PART_Q: Final = Msg("Q 問い", "Q questions", "Q 问题")
PART_I: Final = Msg("I 入口", "I intake", "I 入口")
PART_S: Final = Msg("S 選別", "S screening", "S 筛选")
PART_X: Final = Msg("X 根拠化", "X evidence", "X 依据化")
PART_W: Final = Msg("W 執筆", "W writing", "W 写作")
PART_D: Final = Msg("D 配達と資源", "D delivery", "D 送达与资源")
PART_OUT: Final = Msg("OUT 出力", "OUT output", "OUT 产出")
FACTOR_N_NEW: Final = Msg("└ N_new 新規の論文", "└ N_new new papers", "└ N_new 新论文")
FACTOR_N_OT: Final = Msg(
    "N_ot 問いに合う新規の論文", "N_ot new papers on a question", "N_ot 切题的新论文"
)
FACTOR_P_SEL: Final = Msg("p_sel keep に届いた", "p_sel reached keep", "p_sel 到达 keep")
FACTOR_P_EXT: Final = Msg("p_ext claim が載った", "p_ext a claim was posted", "p_ext 刊登了 claim")
FACTOR_P_WRI: Final = Msg("p_wri [n] で引用された", "p_wri cited as [n]", "p_wri 以 [n] 引用")
FACTOR_O1_C: Final = Msg(
    "O1_c 7 日以内に初めて引用", "O1_c first cited within 7 days", "O1_c 7 天内首次引用"
)
WBR_FIX: Final = Msg("4. どこを直すか", "4. Where to fix", "4. 改哪里")
WBR_NOT_IN_V0: Final = Msg("v0 では出さない", "Not in v0", "v0 不给出")
WBR_QUESTIONS: Final = Msg(
    "5. 問い (直近 14 日に動いた問い {k}/{n})",
    "5. Questions ({k}/{n} moved in the last 14 days)",
    "5. 问题 (最近 14 天推进的问题 {k}/{n})",
)
WBR_HEAD_QUESTIONS: Final = Msg(
    "| ライン | 問い | 止まった段 | screening → keep → claim → 引用 (14 日) |",
    "| Line | Question | Stopped at | screening → keep → claim → cited (14 days) |",
    "| 线 | 问题 | 停在 | screening → keep → claim → 引用 (14 天) |",
)
WBR_ALL_MOVING: Final = Msg("動かない問いは無い", "Every open question moved", "所有问题都有推进")
WBR_NO_QUESTIONS: Final = Msg(
    "問い未設定: {lines}", "No open question: {lines}", "未设置问题: {lines}"
)
STAGE_SCREENING: Final = Msg(
    "I 入口 (screening に届いた対が 0)",
    "I intake (no pair reached screening)",
    "I 入口 (没有进入 screening 的对)",
)
STAGE_KEEP: Final = Msg("S 選別 (keep 0)", "S screening (no keep)", "S 筛选 (keep 0)")
STAGE_CLAIM: Final = Msg("X 根拠化 (claim 0)", "X evidence (no claim)", "X 依据化 (claim 0)")
STAGE_CITE: Final = Msg("W 執筆 (引用 0)", "W writing (nothing cited)", "W 写作 (引用 0)")
STAGE_DELIVERED: Final = Msg(
    "既出のみ (引用したのは届けた論文だけ)",
    "delivered before (it cited only papers delivered earlier)",
    "仅已出现 (引用的只是已送达的论文)",
)
WBR_REPEATS: Final = Msg("6. 反復と新規性", "6. Repetition and novelty", "6. 重复与新颖性")
WBR_REPEAT_SLOTS: Final = Msg(
    "掲載枠のうち以前に掲載された論文: {value}",
    "Note slots taken by a paper posted before: {value}",
    "版面中以前刊登过的论文: {value}",
)
WBR_REPEAT_REVIEW: Final = Msg(
    "Review のうち以前のノートに出ていた論文: {value}",
    "Review entries an earlier note showed: {value}",
    "Review 中以前的笔记出现过的论文: {value}",
)
WBR_REVIEW_UNMEASURED: Final = Msg(
    "未計測 (この週の RunRecord に Review が無い)",
    "not measured (no RunRecord of the week holds a Review)",
    "未测量 (本周的 RunRecord 没有 Review)",
)
WBR_KEYWORD_NEW: Final = Msg(
    "keyword の取得のうち以前に見ていないもの: {value}",
    "Keyword fetch results not seen on an earlier day: {value}",
    "keyword 获取中以前未见过的: {value}",
)
WBR_NOT_MEASURED: Final = Msg("未計測", "not measured", "未测量")
WBR_DELIVERY: Final = Msg("7. 配達と資源", "7. Delivery and resources", "7. 送达与资源")
WBR_LINE_RUNS: Final = Msg(
    "line-run {n} (Report {reports} · RunRecord {records})",
    "Line-runs {n} (Report {reports} · RunRecord {records})",
    "line-run {n} (Report {reports} · RunRecord {records})",
)
WBR_DEGRADED: Final = Msg("DEGRADED の理由:", "DEGRADED reasons:", "DEGRADED 的原因:")
WBR_MORE: Final = Msg("ほか {n} 件", "{n} more", "另有 {n} 条")
WBR_PER_O1: Final = Msg(
    "O1 1 本あたり: Jev 回答 {answers} · 書き手の呼び出し {writer} · Jev token 入力 {tokens_in}"
    " / 出力 {tokens_out}",
    "Per O1 paper: Jev answers {answers} · writer calls {writer} · Jev tokens in {tokens_in} "
    "/ out {tokens_out}",
    "每篇 O1: Jev 回答 {answers} · 写作模型调用 {writer} · Jev token 输入 {tokens_in}"
    " / 输出 {tokens_out}",
)
WBR_LAST: Final = Msg("8. 前回の 1 手", "8. Last week's change", "8. 上次的一手")
WBR_INSTRUMENTS: Final = Msg("9. 計器", "9. Instruments", "9. 仪表")
WBR_INSTRUMENT_LINE: Final = Msg(
    "{id} ({part}): {status}{why}", "{id} ({part}): {status}{why}", "{id} ({part}): {status}{why}"
)
WBR_TICK: Final = Msg("tick 全体", "the tick", "整个 tick")
WBR_AUTHOR: Final = Msg(
    "著者の信号: 今週の新しいチェック {ticks} · 今週初めて開かれた jrp ノート {opened} · "
    "recommendation の正例 {positives}",
    "The author's signal: new question-day ticks {ticks} · jrp notes first opened this week "
    "{opened} · recommendation positives {positives}",
    "作者的信号: 本周新的勾选 {ticks} · 本周首次打开的 jrp 笔记 {opened} · "
    "recommendation 的正例 {positives}",
)
WBR_POSITIVES_FROZEN: Final = Msg(
    "{n} 件 (14 日変化なし)", "{n} (unchanged for 14 days)", "{n} 条 (14 天未变)"
)
WBR_POSITIVES_ADDED: Final = Msg(
    "{n} 件 (14 日で +{added})", "{n} (+{added} in 14 days)", "{n} 条 (14 天内 +{added})"
)
WBR_POSITIVES_UNKNOWN: Final = Msg(
    "{n} 件 (初回のチェックの日が記録より前)",
    "{n} (first ticked before that day was recorded)",
    "{n} 条 (首次勾选早于开始记录)",
)

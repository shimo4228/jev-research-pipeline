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

JEV_QUESTIONS: Final = Msg("Jev 質問数: {n}", "Jev questions: {n}", "Jev 问题数: {n}")
GENERATION_TOKENS: Final = Msg(
    "生成 token ({spec}): in {tokens_in} / out {tokens_out}",
    "Generation tokens ({spec}): in {tokens_in} / out {tokens_out}",
    "生成 token ({spec}): in {tokens_in} / out {tokens_out}",
)
JEV_PRICE_UNSET: Final = Msg("Jev 単価未設定", "Jev price not set", "未设置 Jev 单价")
SUBSCRIPTION_ZERO: Final = Msg(
    "生成はサブスクリプション定額で 0 計上",
    "generation is on a flat subscription, counted as 0",
    "生成按订阅定额计为 0",
)
GENERATION_PRICE_UNSET: Final = Msg("生成単価未設定", "generation price not set", "未设置生成单价")
FILL_RATE: Final = Msg(
    "記入率 (前回・問い日): {rate}",
    "Fill rate (previous run, question-days): {rate}",
    "填写率 (上次・问题日): {rate}",
)
FILL_RATE_NONE: Final = Msg(
    "記入率 (前回): なし", "Fill rate (previous run): none", "填写率 (上次): 无"
)
OPEN_QUESTIONS: Final = Msg("open な問い: {n} 件", "Open questions: {n}", "开放问题: {n} 个")
RUBRIC_AXIS: Final = Msg(
    "rubric {axis}: 平均 {mean} / gold 一致 {gold}",
    "rubric {axis}: mean {mean} / gold agreement {gold}",
    "rubric {axis}: 平均 {mean} / gold 一致率 {gold}",
)
NOT_MEASURED: Final = Msg("未計測", "not measured", "未测量")
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
HARVEST: Final = Msg(
    "harvest: label {labels} 件 / 取り消し {withdrawn} 件",
    "harvest: {labels} labels / {withdrawn} withdrawn",
    "harvest: label {labels} 条 / 撤销 {withdrawn} 条",
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
NET_SOURCES: Final = Msg(
    "net 取得数: {counts}", "Sources per net: {counts}", "各 net 获取数: {counts}"
)
NET_SHARES: Final = Msg(
    "net 採用率: {shares}", "Accept share per net: {shares}", "各 net 采纳率: {shares}"
)
TOPIC_CLUSTERS: Final = Msg("topic クラスタ数: {n}", "Topic clusters: {n}", "topic 聚类数: {n}")
CLUSTERS_BEFORE: Final = Msg(
    " (前回 {n}{fewer})", " (previous run {n}{fewer})", " (上次 {n}{fewer})"
)
CLUSTERS_FEWER: Final = Msg("・減少", ", fewer", "・减少")
CONVERGENCE: Final = Msg("収束推定 f: {f}", "Convergence estimate f: {f}", "收敛估计 f: {f}")
CONVERGENCE_NONE: Final = Msg(
    "収束推定 f: データ不足 (3 run 未満)",
    "Convergence estimate f: not enough data (under 3 runs)",
    "收敛估计 f: 数据不足 (少于 3 次 run)",
)
TIME_TO_DISCOVERY: Final = Msg(
    "Time-to-Discovery 中央値: {days} 日",
    "Time-to-Discovery median: {days} days",
    "Time-to-Discovery 中位数: {days} 天",
)
TIME_TO_DISCOVERY_NONE: Final = Msg(
    "Time-to-Discovery: 未計測", "Time-to-Discovery: not measured", "Time-to-Discovery: 未测量"
)

# --- Review reasons and rule candidates (jev.question_screening, reduction.rules) -----------

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
RULE_CANDIDATE: Final = Msg(
    "rule 候補: {function} は {condition} のとき {outcome} (n={n}, 一致率 {rate})",
    "rule candidate: {function} is {outcome} when {condition} (n={n}, agreement {rate})",
    "rule 候选: {function} 在 {condition} 时为 {outcome} (n={n}, 一致率 {rate})",
)

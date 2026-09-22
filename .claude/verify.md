# 機械ゲートの選定記録

入口は [`verify.sh`](verify.sh)（`--staged` = commit 境界 / 引数なし = 全体）。
ツールの版は `pyproject.toml` の `[dependency-groups] dev` が正本（`==` で pin）。
棚卸しは `~/.claude` の skill `verify-bootstrap` を audit モードで呼ぶ。

選定日: **2026-09-22**（全 category 共通）。ツール集合は著者指定（build session 指示:
ruff / pyright strict / pytest / bandit / deptry）。版は同日 PyPI で最新を確認。

| category | tool | 版 (release) | mode | 判定 |
|---|---|---|---|---|
| format | ruff format | 0.16.8 (2026-09-16) | staged + full | block |
| lint | ruff check（select 明示、予算系含む） | 0.16.8 | staged + full | block |
| type check | pyright strict + 追加 error | 1.1.414 (2026-09-10) | full | block |
| security (SAST) | bandit `-ll -ii`（src のみ） | 1.9.4 (2026-02-25) | staged + full | block |
| dependency | deptry（未使用 / 未宣言 / transitive 依存） | 0.25.1 (2026-03-18) | full | block |
| test | pytest + pytest-cov（branch, floor 80%） | 9.1.1 / 7.1.0 | full | block |

test 補助（2026-09-22 追加）: pytest-asyncio 1.4.0（async test、`asyncio_mode = "auto"`）、
types-defusedxml（defusedxml の型 stub）。外部 API の test は cassette 再生のみ
（`tests/conftest.py` の `cassette` fixture — 既定 replay、`JRP_CASSETTE_SYNTHETIC=1` で合成、
`JRP_CASSETTE_RECORD=1` で live 録音 = 人間ゲート）。verify は offline・key 不要。

**無いもの**: 既知脆弱性の依存監査（pip-audit / uv audit）は著者指定のツール集合に
含まれない。外部 API SDK を入れる step 5-6 で追加を再検討する。秘密スキャンは harness 側
（`hooks/secret-scan-precommit.sh`）。

## 例外（許可リスト）

- `src/jev_research_pipeline/jev/_sdk.py` 先頭の pyright directive（reportUnknownMember /
  Argument / Variable を off）— 2026-09-22。typesafe-sdk 0.7.1 の JSONContent / JSONValue は
  文字列前方参照の TypeAliasType で、pyright 1.1.414 が Unknown に解決する。SDK 呼び出しを
  この 1 file に閉じ、他は JevState と SystemOneResponse だけを見る。typesafe-sdk bump 時に
  directive を外して再検査する。

## 発火の実証（2026-09-22）

probe（未整形・未使用 import・`eval`・int を str で返す・transitive 依存 `yaml` の import・
`assert False` のテスト）を注入し、full で 6 category すべて、staged で format / lint /
security が発火、exit 1 を確認。probe 削除後 exit 0。`--staged` 実測 0.4s。

## 予算系

`pyproject.toml` の `[tool.ruff.lint.mccabe]` / `[tool.ruff.lint.pylint]`:
C901 = 10、PLR0912 = 12、PLR0911 = 6、PLR0915 = 50、PLR0917（位置引数）= 5。
**空 corpus で設定**（分布実測なし）— src/ の関数が 200 を超えたら分布を実測して
p99 に合わせ直す。変更は上げずに刈る、変える場合はここに日付つき理由。

PLR0913（引数総数）ではなく PLR0917（位置引数数）を選んだ: 型の `new(*, ...)` は
保存 field ごとに 1 keyword を取り、keyword-only なので呼び出し側で全引数が名指しされる。
0913 が狙う取り違えのバグクラスが構造的に起きない。

## 再調査トリガー

- 12 ヶ月経過（2027-09-22）
- pyright: ty / pyrefly が 1.0 到達
- bandit / deptry / pytest-cov: 最終リリースが 12 ヶ月以上前になった
- 外部 SDK（typesafe-sdk / pydantic-ai）導入時: 依存脆弱性監査の追加判断

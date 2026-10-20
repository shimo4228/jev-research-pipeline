"""`jrp eval gate check`: the author's blind check of the silver labels (research report 2026-10-20-sx-eval-loop).

`--out FILE` writes up to CHECK_N labelled items, drawn evenly over the label (yes, partial,
no) and the kind (S, X) with the set's name as the seed, each with three boxes and no silver
label on the page (the research report: a shown suggestion pulls a checker toward it), and
the key beside it (FILE.key.json). `--read FILE` reads the ticked boxes back and prints the
agreement: positive vs negative (yes and partial count as positive, as everywhere in the
gate eval) with Wilson's interval, and the three-way counts. A few dozen items say whether
the labeller is broken, not how to correct it (about 200 would be needed for that,
research report §B), so the score never reads this file.

The page holds third-party text (excerpts, claims): it goes through report.markdown.sanitize,
so nothing in it runs or fetches when the file is opened in Obsidian.
"""

import json
import random
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, get_args

from jev_research_pipeline.report.markdown import sanitize

from .gate_set import GateSet, Material
from .silver import Answer, is_positive
from .stats import wilson

CHECK_N: Final = 30
ANSWERS: Final[tuple[Answer, ...]] = get_args(Answer.__value__)
_HEAD: Final = re.compile(r"^## (\d+)\. ")
_BOX: Final = re.compile(r"^- \[([xX ])\] (yes|partial|no)\b")


def _pick(gs: GateSet, answers: Mapping[str, Answer], n: int) -> list[tuple[Material, Answer]]:
    groups: dict[tuple[str, Answer], list[Material]] = {}
    for item in sorted(answers):
        m = gs.materials.get(item)
        if m is not None:
            groups.setdefault((m.kind, answers[item]), []).append(m)
    rng = random.Random(f"{gs.manifest.name}/check")
    for ms in groups.values():
        rng.shuffle(ms)
    out: list[tuple[Material, Answer]] = []
    while len(out) < n and any(groups.values()):
        for key in sorted(groups):
            if groups[key] and len(out) < n:
                out.append((groups[key].pop(), key[1]))
    rng.shuffle(out)
    return out


def _block(i: int, m: Material) -> list[str]:
    q = m.question
    lines = [f"## {i}. {m.line} / {'S 文献' if m.kind == 's' else 'X claim'}", ""]
    lines.append(f"**問い**: {sanitize(q.title, one_line=True)}")
    if q.brief:
        lines.append(f"**背景**: {sanitize(q.brief, one_line=True)}")
    if m.kind == "s" and q.evidence:
        lines.append(f"**根拠として数えるもの**: {sanitize(' / '.join(q.evidence), one_line=True)}")
    if q.not_:
        lines.append(f"**この問いではないもの**: {sanitize(' / '.join(q.not_), one_line=True)}")
    lines.append("")
    if m.kind == "s":
        lines.append(
            f"**文献**: {sanitize(m.title, one_line=True)} ({sanitize(m.adapter, one_line=True)})"
        )
        lines += ["", "> " + sanitize(m.excerpt, one_line=True)]
        question = "この文献は、この問いの根拠を取りに行く価値があるか"
    else:
        lines.append(f"**論文**: {sanitize(m.title, one_line=True)}")
        lines += ["", "> " + sanitize(m.claim, one_line=True)]
        question = "この claim は、この問いを前に進めるか"
    lines += ["", f"{question}:", "", "- [ ] yes", "- [ ] partial", "- [ ] no", ""]
    return lines


def write_check(gs: GateSet, answers: Mapping[str, Answer], out: Path, *, n: int = CHECK_N) -> int:
    """The check page and its key; returns how many items it holds."""
    picked = _pick(gs, answers, n)
    if not picked:
        return 0
    lines = [
        f"# silver label の確認(set {gs.manifest.name})",
        "",
        "各項目で、あなたの判断に当たる箱を 1 つだけ [x] にしてください。silver label は伏せてあります。",
        "yes = そのまま当たる、partial = 関係するが間接的、no = 当たらない。",
        "",
    ]
    for i, (m, _) in enumerate(picked, 1):
        lines += _block(i, m)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    key = [
        {"n": i, "item": m.item, "kind": m.kind, "silver": a} for i, (m, a) in enumerate(picked, 1)
    ]
    out.with_suffix(".key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    return len(picked)


@dataclass(frozen=True)
class Agreement:
    answered: int
    agree: int
    """Positive (yes, partial) vs no, the author's against the silver label."""
    exact: int
    confusion: Mapping[tuple[str, str], int]
    """(author, silver) → items."""

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.agree, self.answered) if self.answered else None


def read_check(page: Path) -> Agreement:
    """The author's ticks against the key; an item with no or several ticks is skipped."""
    key = {
        row["n"]: row
        for row in json.loads(page.with_suffix(".key.json").read_text(encoding="utf-8"))
    }
    ticks: dict[int, list[str]] = {}
    current: int | None = None
    for line in page.read_text(encoding="utf-8").splitlines():
        if head := _HEAD.match(line):
            current = int(head.group(1))
        elif (box := _BOX.match(line)) and current is not None and box.group(1) in "xX":
            ticks.setdefault(current, []).append(box.group(2))
    confusion: Counter[tuple[str, str]] = Counter()
    agree = exact = answered = 0
    for n, picked in ticks.items():
        if len(picked) != 1 or n not in key:
            continue
        author, silver = picked[0], str(key[n]["silver"])
        answered += 1
        exact += author == silver
        agree += is_positive(author) == is_positive(silver)  # pyright: ignore[reportArgumentType]
        confusion[(author, silver)] += 1
    return Agreement(answered, agree, exact, dict(confusion))


def render_agreement(a: Agreement) -> str:
    if not a.answered:
        return "印の付いた項目がありません。"
    lo, hi = a.interval or (0.0, 0.0)
    rows = [
        f"著者と silver label の一致(yes+partial / no): {a.answered} 件中 {a.agree} 件 "
        f"[{lo * 100:.0f}%, {hi * 100:.0f}%]、3 値の一致 {a.exact} 件",
        "| 著者 \\ silver | " + " | ".join(ANSWERS) + " |",
        "|---|" + "---|" * len(ANSWERS),
    ]
    for author in ANSWERS:
        rows.append(
            f"| {author} | "
            + " | ".join(str(a.confusion.get((author, s), 0)) for s in ANSWERS)
            + " |"
        )
    return "\n".join(rows) + "\n"

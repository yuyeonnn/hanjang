"""AI 비용 한눈에 — `python -m hanjang.cost`. llm.py 가 부를 때마다 남기는 data/llm_cost.csv 를 센다."""

import sys
from collections import defaultdict
from datetime import date, timedelta

from hanjang.llm import LOG

NAMES = {"writer:note": "노트 쓰기", "article:article": "피드 기사", "reader:title": "공시 분류", "business:business": "사업보고서 요약",
         "scan:holdings": "캡처 읽기"}  # 처음 보는 일은 그 이름 그대로


def report(lines: list[str], today: date) -> str:
    by_day: dict[str, float] = defaultdict(float)
    by_job: dict[str, list] = defaultdict(lambda: [0, 0.0])
    month = today.strftime("%Y-%m")
    for ln in lines:
        at, label, _, _, _, usd = ln.rstrip().split(",")
        by_day[at[:10]] += float(usd)
        if at.startswith(month):
            by_job[label][0] += 1
            by_job[label][1] += float(usd)
    week = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    avg = sum(by_day[d] for d in week) / 7
    out = [f"오늘 ${by_day[today.isoformat()]:.2f} · 이번 달 ${sum(v for d, v in by_day.items() if d.startswith(month)):.2f}"
           f" · 최근 7일 하루 평균 ${avg:.2f} → 한 달이면 약 ${avg * 30:.0f} (약 {avg * 30 * 1400:,.0f}원)", "", "최근 7일"]
    out += [f"  {d[5:]}  ${by_day[d]:.2f}" for d in week]
    out += ["", "이번 달 일감별로"]
    out += [f"  {NAMES.get(k, k):12s} {n:5,}콜  ${v:.2f}" for k, (n, v) in sorted(by_job.items(), key=lambda x: -x[1][1])]
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(report(LOG.read_text(encoding="utf-8").splitlines() if LOG.exists() else [], date.today()))

"""AI 호출은 여기 한 곳. 읽기(reader)·쓰기(writer) 둘뿐 — 숫자는 묻지 않는다 (불변식 2).
퀀트점프 `desk.py` 의 `_openai`·`_ask` 에서 복사해 줄였다."""

import json
import time
from pathlib import Path

import httpx

from hanjang.sources import env

MODELS = {"reader": "gpt-4.1-mini", "writer": "gpt-4.1"}  # 읽기는 싼 모델, 글은 좋은 모델
PRICE = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00)}  # USD / 1M 토큰 (입력, 출력)
PROMPTS = Path(__file__).parent / "prompts"
spent = {"usd": 0.0, "calls": 0}  # 이번 실행 비용 — 끝에 찍는다
CAP_USD = 3.0  # 한 번 실행 상한. ponytail: 주간 1회 · 100종목이면 $1 안쪽 (실측 뒤 조정)


def _openai(model: str, system: str, user: str | list, schema: dict | None = None) -> str:
    for wait in (10, 30, 60, None):
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {env()['OPENAI_API_KEY']}"},
            json={"model": model, "temperature": 0,
                  # 스키마가 있으면 구조화 출력(strict) — 정해 둔 칸·선택지 밖의 값은 API 가 아예 만들지 않는다
                  "response_format": {"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}}
                  if schema else {"type": "json_object"},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=120,
        )  # fmt: skip
        if r.status_code == 429 and "insufficient_quota" in r.text:
            raise RuntimeError("OpenAI 크레딧 소진")
        if wait is None or not (r.status_code == 429 or r.status_code >= 500):
            break
        time.sleep(wait)
    if r.status_code != 200:  # 응답 본문엔 키가 없다
        raise RuntimeError(f"OpenAI HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    pin, pout = PRICE[model]
    spent["usd"] += (j["usage"]["prompt_tokens"] * pin + j["usage"]["completion_tokens"] * pout) / 1e6
    spent["calls"] += 1
    return j["choices"][0]["message"]["content"]


def ask(prompt: str, task: str, payload, check, schema: dict | None = None, image: str | None = None):
    """묻고 `check(parsed)` 로 검사 — 실패하면 두 번까지 다시, 그래도 실패면 None.
    같은 입력에도 답이 매번 조금 달라서, 한 번 더 물으면 통과하는 일이 많다(실측 12장 중 2장)."""
    system = (PROMPTS / f"{prompt}.md").read_text(encoding="utf-8")
    user = json.dumps({"task": task, "input": payload}, ensure_ascii=False, default=str)
    if image:  # 사진 한 장(data URL) — 캡처 읽기. 저장하지 않고 이 요청에만 싣는다
        user = [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": image}}]
    for _ in range(3):
        if spent["usd"] >= CAP_USD:
            raise RuntimeError(f"실행 비용 상한 ${CAP_USD} 도달")
        try:
            return check(json.loads(_openai(MODELS[prompt], system, user, schema)))
        except (ValueError, KeyError, TypeError):
            continue
    return None

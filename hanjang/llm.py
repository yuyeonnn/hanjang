"""AI 호출은 여기 한 곳. 읽기(reader)·쓰기(writer) 둘뿐 — 숫자는 묻지 않는다 (불변식 2).
퀀트점프 `desk.py` 의 `_openai`·`_ask` 에서 복사해 줄였다."""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from hanjang.sources import ROOT, env

MODELS = {"reader": "gpt-4.1-mini", "writer": "gpt-4.1", "scan": "gpt-4.1-mini"}  # 읽기는 싼 모델, 글은 좋은 모델 · 캡처 읽기(scan)가 빠져 있어 늘 실패하던 것
# 일감(지시문 파일 이름)마다 다른 모델 — 없으면 MODELS. 노트는 싼 모델로 먼저 쓰고, 검사에 떨어지면 MODELS["writer"] 로 다시 쓴다(notes.write).
# 2026-10-12 평가: 서버 재료 30편에서 버릇 0.7/100문장(gpt-4.1 3.3) · 정말 틀린 문장 2(gpt-4.1 0~1) · 값 약 1/6. 되돌리려면 이 줄을 비운다
BY_TASK: dict[str, str] = {"writer": "gpt-5.6-luna"}
# USD / 1M 토큰 (입력, 캐시된 입력, 출력) — 같은 지시문 앞부분은 OpenAI 가 알아서 싸게 받는다(1,024토큰 이상, 75% 할인)
PRICE = {"gpt-4.1-mini": (0.40, 0.10, 1.60), "gpt-4.1": (2.00, 0.50, 8.00), "gpt-4.1-nano": (0.10, 0.025, 0.40),
         "gpt-5.6-luna": (0.20, 0.02, 1.20), "gpt-6-luna": (0.10, 0.01, 0.50)}
PROMPTS = Path(__file__).parent / "prompts"
spent = {"usd": 0.0, "calls": 0}  # 이번 실행 비용 — 끝에 찍는다
LOG = ROOT / "data" / "llm_cost.csv"  # 부를 때마다 한 줄 — 시각,일,모델,입력토큰,출력토큰,캐시된 입력,USD (python -m hanjang.cost 가 센다. 옛 줄엔 캐시 칸이 없다)
LANGSMITH = "https://api.smith.langchain.com/runs"  # .env 에 LANGSMITH_API_KEY 가 있을 때만 — 지시문·답·토큰을 한 화면에서 본다
CAP_USD = 6.0  # 한 번 실행 상한 — 월요일 노트 100장(약 $2) + 뉴닉식 기사 30편(약 $1.5). ponytail: 실측 뒤 조정


def trace(model: str, system: str, user: str | list, out: str, usage: tuple[int, int, int], usd: float, t0: datetime, label: str) -> None:
    """LangSmith 에 한 줄 — 못 보내도 글쓰기는 계속. 사진(보유 종목 캡처)은 보내지 않는다."""
    key = env().get("LANGSMITH_API_KEY")
    if not key:
        return
    if isinstance(user, list):
        user = [x if x.get("type") == "text" else {"type": "text", "text": "[사진 — 보내지 않음]"} for x in user]
    tin, tout, cached = usage
    try:
        httpx.post(LANGSMITH, headers={"x-api-key": key}, timeout=5, json={
            "id": str(uuid.uuid4()), "name": label or model, "run_type": "llm", "session_name": env().get("LANGSMITH_PROJECT", "hanjang"),
            "start_time": t0.isoformat(), "end_time": datetime.now(timezone.utc).isoformat(), "tags": [label.split(":")[0]],
            "inputs": {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            "outputs": {"choices": [{"message": {"role": "assistant", "content": out}}],
                        "usage_metadata": {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout, "input_token_details": {"cache_read": cached}}},
            "extra": {"metadata": {"ls_provider": "openai", "ls_model_name": model, "ls_model_type": "chat", "task": label, "usd": round(usd, 6)}}})  # fmt: skip
    except httpx.HTTPError:
        pass


def body_of(model: str, system: str, user: str | list, schema: dict | None) -> dict:
    """요청 한 건 — gpt-5·6 계열은 temperature 를 받지 않는다. 대신 생각하는 토큰을 쓰지 않게(reasoning_effort none) 한다."""
    return ({"model": model} | ({"reasoning_effort": "none"} if model.startswith(("gpt-5", "gpt-6")) else {"temperature": 0})
            # 스키마가 있으면 구조화 출력(strict) — 정해 둔 칸·선택지 밖의 값은 API 가 아예 만들지 않는다
            | {"response_format": {"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}} if schema else {"type": "json_object"},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})  # fmt: skip


def _openai(model: str, system: str, user: str | list, schema: dict | None = None, label: str = "") -> str:
    t0 = datetime.now(timezone.utc)
    for wait in (10, 30, 60, None):
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {env()['OPENAI_API_KEY']}"},
            json=body_of(model, system, user, schema),
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
    pin, pcached, pout = PRICE[model]
    tin, tout = j["usage"]["prompt_tokens"], j["usage"]["completion_tokens"]
    cached = (j["usage"].get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    usd = ((tin - cached) * pin + cached * pcached + tout * pout) / 1e6  # 캐시된 입력은 싼 값으로 — 예전엔 전부 제값으로 세어 약 30% 많게 적혔다
    spent["usd"] += usd
    spent["calls"] += 1
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')},{label},{model},{tin},{tout},{cached},{usd:.6f}\n")
    except OSError:  # 기록을 못 남겨도 글쓰기는 계속
        pass
    out = j["choices"][0]["message"]["content"]
    trace(model, system, user, out, (tin, tout, cached), usd, t0, label)
    return out


BATCH_WAIT = 30 * 60  # 묶음 처리를 기다리는 시간(초) — 넘으면 거두고, 못 받은 것은 부르는 쪽이 평소처럼 하나씩 묻는다
API = "https://api.openai.com/v1"


def user_of(task: str, payload) -> str:
    return json.dumps({"task": task, "input": payload}, ensure_ascii=False, default=str)


def batch(prompt: str, task: str, jobs: dict[str, tuple], prompt_file: str | None = None, wait: float | None = None) -> dict[str, str]:
    """여러 건을 한꺼번에 맡겨 반값에 받는다(OpenAI Batch) — jobs = {이름: (payload, schema)} → {이름: 답 글}.
    검사는 하지 않는다(부르는 쪽이 한다). 기다려도 안 끝나거나 무엇이든 잘못되면 받은 것만 돌려준다 — 빈 것일 수도 있다.
    매일 실행은 급하지 않아서 쓴다: 같은 모델·같은 답, 값만 절반 (2026-10-11)."""
    if not jobs or spent.get("no_credit"):
        return {}
    name = prompt_file or prompt
    model = model_of(prompt, prompt_file)
    system = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    head = {"Authorization": f"Bearer {env()['OPENAI_API_KEY']}"}
    users = {k: user_of(task, payload) for k, (payload, _) in jobs.items()}
    lines = "\n".join(json.dumps({"custom_id": k, "method": "POST", "url": "/v1/chat/completions", "body": body_of(model, system, users[k], schema)},
                                 ensure_ascii=False) for k, (_, schema) in jobs.items())  # fmt: skip
    out: dict[str, str] = {}
    t0 = datetime.now(timezone.utc)
    try:
        f = httpx.post(f"{API}/files", headers=head, data={"purpose": "batch"}, files={"file": ("batch.jsonl", lines.encode("utf-8"))}, timeout=120)
        f.raise_for_status()
        b = httpx.post(f"{API}/batches", headers=head, timeout=60,
                       json={"input_file_id": f.json()["id"], "endpoint": "/v1/chat/completions", "completion_window": "24h"})  # fmt: skip
        b.raise_for_status()
        bid, end = b.json()["id"], time.time() + (BATCH_WAIT if wait is None else wait)
        while True:
            st = httpx.get(f"{API}/batches/{bid}", headers=head, timeout=60).json()
            if st["status"] in ("completed", "failed", "expired", "cancelled"):
                break
            if time.time() > end:  # 못 기다린다 — 거두고(끝난 것까지는 값이 나간다) 받은 것만 쓴다
                httpx.post(f"{API}/batches/{bid}/cancel", headers=head, timeout=60)
                end = float("inf")
            time.sleep(20)
        if not st.get("output_file_id"):
            return {}
        pin, pcached, pout = PRICE[model]
        for ln in httpx.get(f"{API}/files/{st['output_file_id']}/content", headers=head, timeout=120).text.splitlines():
            r = json.loads(ln)
            body = (r.get("response") or {}).get("body") or {}
            if (r.get("response") or {}).get("status_code") != 200 or r["custom_id"] not in users:
                continue
            tin, tout = body["usage"]["prompt_tokens"], body["usage"]["completion_tokens"]
            cached = (body["usage"].get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            usd = ((tin - cached) * pin + cached * pcached + tout * pout) / 1e6 / 2  # 묶음 처리는 반값
            spent["usd"] += usd
            spent["calls"] += 1
            out[r["custom_id"]] = body["choices"][0]["message"]["content"]
            try:
                with LOG.open("a", encoding="utf-8") as fh:
                    fh.write(f"{datetime.now().isoformat(timespec='seconds')},{name}:{task},{model}-batch,{tin},{tout},{cached},{usd:.6f}\n")
            except OSError:
                pass
            trace(model, system, users[r["custom_id"]], out[r["custom_id"]], (tin, tout, cached), usd, t0, f"{name}:{task}:batch")
    except (httpx.HTTPError, KeyError, ValueError) as err:  # 묶음 처리가 안 돼도 매일 실행은 간다 — 하나씩 묻는 길로
        print(f"묶음 처리 실패 — 하나씩 묻는다: {type(err).__name__} {str(err)[:120]}")
    return out


def model_of(prompt: str, prompt_file: str | None = None) -> str:
    return BY_TASK.get(prompt_file or prompt) or MODELS[prompt]


def ask(prompt: str, task: str, payload, check, schema: dict | None = None, image: str | None = None,
        prompt_file: str | None = None, model: str | None = None, tries: int = 3):
    """묻고 `check(parsed)` 로 검사 — 실패하면 두 번까지 다시(tries), 그래도 실패면 None. model 을 주면 그 모델로(다시 쓸 때).
    같은 입력에도 답이 매번 조금 달라서, 한 번 더 물으면 통과하는 일이 많다(실측 12장 중 2장)."""
    system = (PROMPTS / f"{prompt_file or prompt}.md").read_text(encoding="utf-8")  # prompt = 모델(MODELS 의 열쇠)
    user = user_of(task, payload)
    if image:  # 사진 한 장(data URL) — 캡처 읽기. 저장하지 않고 이 요청에만 싣는다
        user = [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": image}}]
    model = model or model_of(prompt, prompt_file)
    for _ in range(tries):
        if spent["usd"] >= CAP_USD:
            raise RuntimeError(f"실행 비용 상한 ${CAP_USD} 도달")
        if spent.get("no_credit"):  # 크레딧이 바닥나면 더 묻지 않는다 — 노트는 코드 문장으로 (매일 실행이 끝까지 돌게)
            return None
        try:
            return check(json.loads(_openai(model, system, user, schema, f"{prompt_file or prompt}:{task}")))
        except (ValueError, KeyError, TypeError):
            continue
        except RuntimeError as err:
            if "크레딧 소진" not in str(err):
                raise
            spent["no_credit"] = True  # ponytail: 화면 서버에선 다시 켤 때까지 남는다(캡처 읽기) — 채운 뒤 hanjang-web 재시작
            return None
    return None

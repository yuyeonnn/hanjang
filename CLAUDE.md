# CLAUDE.md

**한장(Hanjang)** — 내가 가진 주식이 지금 어떤 상황인지, 공시·재무·뉴스·수급을 **쉬운 글 한 장**으로 꿰어 보여주는 앱.
네이버·토스는 정보를 늘어놓고, 한장은 설명한다. 약속하는 것은 **수익이 아니라 이해**다.

> 지금 단계: **1단계 4주차 — 설문·메일·주간 자동 실행까지** (매일 07:00: `uv run python -m hanjang.daily` = 받기→노트(월요일 전부·화~일 바뀐 종목만)→월요일만 안내 메일 · 화면: `uv run python -m hanjang.web` · 테스트 `uv run pytest`). **한장 전용 파이썬 환경** — 명령 앞에 `UV_PROJECT_ENVIRONMENT=C:/venvs/hanjang` (사용자 환경 변수가 퀀트점프 환경을 가리킨다. 섞으면 서로의 패키지를 바꾼다). 기사는 `.env` 의 `NEWS_DEV=1` 일 때만(내 컴퓨터) · 배포 [docs/deploy.md](docs/deploy.md). 메일은 `.env` 의 `SMTP_HOST·SMTP_PORT·SMTP_USER·SMTP_PASSWORD·SMTP_FROM·BASE_URL` — 비어 있으면 서버 콘솔에 찍힌다. 남은 것: 서버에 올리기([docs/deploy.md](docs/deploy.md)) · KRX 시세 견적 문의([docs/krx-inquiry.md](docs/krx-inquiry.md), 사용자가 보냄). 구상 [docs/concept.md](docs/concept.md) · 제품 [docs/PRD.md](docs/PRD.md) · DB [docs/erd.md](docs/erd.md) · 일정 [docs/plan.md](docs/plan.md) · 샘플 [docs/sample-note.md](docs/sample-note.md) · 데이터 사용권 [docs/data-rights.md](docs/data-rights.md) · 화면 디자인 [docs/design.md](docs/design.md) (Stitch 「Warm Editorial Finance」).
> **퀀트점프(`../quant-jump`, 개인용 엔진) 없이 혼자 돈다.** 데이터를 직접 받고 노트를 직접 만든다. 퀀트점프에서는 코드만 복사해 온다.

## 불변식

1. **「사라/팔아라」·비중·주가 예측을 싣지 않는다.** 사실과 해설만. 유료화 전에 유사투자자문 해당 여부를 전문가에게 확인한다.
2. **숫자는 코드가 계산하고, LLM은 옮겨 적기만 한다. 모든 문장에 원문 링크.** 「쉬운데 틀리지 않는 글」이 이 앱의 전부다.
3. **쓸 권리가 확인된 데이터만 쓴다.** 토스 수급 등 개인용 데이터는 금지. 네이버는 화면 구성만 참고하고 데이터는 가져오지 않는다. 뉴스는 제목·링크·우리 요약까지.
4. **퀀트점프에 기대지 않는다.** 퀀트점프를 접어도 한장은 돌아야 한다. 퀀트점프의 DB·파일·서버를 읽지 않고, 필요한 코드만 **복사**해 온다(비중·예측·토스 수급 코드는 가져오지 않는다). 퀀트점프 쪽은 고치지 않는다.
5. **수익률이 좋아진다고 말하지 않는다.** 거시 민감도는 「과거에 그랬다」는 측정 사실로만, 보장 없음을 함께 적는다.

## 진행 순서

샘플 노트 → 모바일 웹(앱 아님) → 20명 6주 시험 → 넓히기 → 정식 앱·제휴.
시험의 계속/접음 기준은 [docs/concept.md](docs/concept.md) §9 — **시작 전에 정해두고 바꾸지 않는다.**

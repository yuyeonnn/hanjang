# 한장 — ERD v0.2

> 1·2단계(모바일 웹 + 20명 시험)에 필요한 것만. SQLite. 근거는 [PRD.md](PRD.md).
> v0.2 (2026-10-07) — **한장이 데이터를 직접 받고 노트를 직접 만든다** (퀀트점프 없이). 그래서 표가 두 묶음이다:
> **재료** (주간 노트 만들기가 채운다) · **서비스** (사용자가 채운다).
> 모든 재료 표는 같은 데이터를 다시 받아도 중복이 생기지 않게 PK 로 덮어쓴다(멱등).

## 관계

```mermaid
erDiagram
    stocks ||--o{ prices : "일별 종가"
    stocks ||--o{ financials : "연도별 재무"
    stocks ||--o{ disclosures : "공시"
    stocks ||--o{ betas : "민감도"
    macro ||--o{ betas : ""
    stocks ||--o{ news : "기사"
    stocks ||--o{ events : "일정"
    stocks ||--o{ notes : "주마다 한 장"
    users ||--o{ holdings : "담는다"
    stocks ||--o{ holdings : ""
    users ||--o{ views : "열어봄"
    users ||--o{ feedback : "설문"
```

---

## A. 재료 — 주간 노트 만들기(F9)가 채운다

### `stocks` — 노트를 만드는 종목 (코스피 시총 상위 약 100개)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `ticker` | text PK | `005930` |
| `name` | text not null | 검색용 |
| `corp_code` | text | DART 고유번호 (공시·재무 조회 키) |
| `active` | bool | 유니버스 안이면 true. 분기마다 시총 순위로 다시 고른다 — 빠진 종목은 false 로 두고 지우지 않는다 |

### `prices` — 일별 종가 (공공데이터포털)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `ticker` | FK stocks | |
| `date` | date | |
| `close` | integer | 받은 그대로의 종가 |
| `adj_close` | real | **수정주가** — 분할·증자를 보정한 값. 수익률·52주·민감도는 전부 이 열로 |
| `mktcap` | integer | 시가총액 (유니버스 고르기) |

PK `(ticker, date)`. 보정 계산은 퀀트점프 코드를 복사한다 — 보정 안 한 종가로 수익률을 내면 분할 날 −80% 같은 거짓 숫자가 예외 없이 나온다.

### `macro` — 거시 지표 (ECOS · FRED)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `series_id` | text | `ECOS:USDKRW` · `ECOS:KTB3Y` · `FRED:DGS10` |
| `date` | date | |
| `value` | real | |

PK `(series_id, date)`.

### `financials` — 연도별 재무 (DART)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `ticker` | FK stocks | |
| `fiscal_year` | int | |
| `revenue` · `operating_income` · `net_income` | integer | 원 |
| `equity` · `liabilities` | integer | 부채비율·ROE 계산용 |
| `rcept_no` | text | 사업보고서 접수번호 → DART 원문 링크 |

PK `(ticker, fiscal_year)`. 증감·PER·PBR·부채비율·ROE 는 저장하지 않고 노트 만들 때 계산한다 (한 곳에서만 계산).

### `disclosures` — 공시 + AI 판독

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `rcept_no` | text PK | DART 접수번호 |
| `ticker` | FK stocks | |
| `date` | date | |
| `title` | text | |
| `code` | text null | AI 판독: 분류 (`BUYBACK` `DIVIDEND` `RIGHTS_ISSUE` … `OTHER`) |
| `importance` | int null | 1~5 |
| `direction` | int null | −1 · 0 · +1 (호재/악재 — 노트에선 「반가운 소식/걸리는 소식」으로만) |
| `risk_tags` | json null | 사업보고서일 때: 「소송」「잠재 부채」 등 |
| `new_share` · `quote` | real · text null | 사업보고서일 때: 작년에 없던 문장 비율 · 인용 1문장 |
| `read_model` · `read_at` | text · timestamp null | 비어 있으면 아직 안 읽음 → 다음 실행에서 읽는다 |

### `betas` — 거시 민감도

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `ticker` | FK stocks | |
| `as_of` | date | |
| `series_id` | text | `macro.series_id` |
| `beta` · `r2` | real | r2 가 낮으면(기준은 복사해 올 코드 그대로) 노트에 싣지 않는다 |
| `window_days` | int | 250 |

PK `(ticker, as_of, series_id)`. 지표 **전부** 저장한다 — 노트에는 뚜렷한 것만 싣고, 나중에 「뉴스↔내 종목」(3단계)이 나머지를 쓴다.

### `news` — 기사 (제목·매체·링크만)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `url` | text PK | 언론사 원문 주소 (중계 주소는 풀어서) |
| `ticker` | FK stocks | |
| `date` | date | |
| `press` | text | |
| `title` | text | |

본문은 저장하지 않는다 (불변식 3).

### `events` — 캘린더 일정

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `ticker` | FK stocks | |
| `date` | date | |
| `kind` | text | `EARNINGS` · `DIVIDEND` · `AGM` · `OTHER` |
| `title` | text | 쉬운 말 한 줄 |
| `rcept_no` | text | DART 원문 |

PK `(ticker, date, kind)`. 공시에서 뽑는다.

### `notes` — 만든 기업 노트

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `ticker` | FK stocks | |
| `week` | date | 그 주 월요일 |
| `facts` | json not null | 사실 묶음 — AI 에게 준 입력 그대로 (나중에 「왜 이렇게 썼나」를 되짚는다) |
| `body` | json not null | 화면에 그리는 노트 (절·문장·링크) |
| `writer` | text | `llm:<모델>` 또는 `code` (숫자 대조 검사에서 떨어져 코드 문장으로 대신한 경우) |
| `made_at` | timestamp | |

PK `(ticker, week)`. 같은 주에 다시 만들면 덮어쓴다.

---

## B. 서비스 — 사용자가 채운다

### `users` — 시험 사용자

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | integer PK | |
| `email` | text unique not null | 로그인·주간 안내. 받는 개인정보는 이것뿐 |
| `cohort` | text | `trial-1` 등. 시험 묶음 |
| `created_at` | timestamp | 시험 주차 계산의 기준 |

로그인 토큰은 테이블 없이 서명된 링크(만료 15분)로 처리한다.

### `holdings` — 내 종목

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `user_id` | FK users | |
| `ticker` | FK stocks | |
| `added_at` | timestamp | |

PK `(user_id, ticker)`. 수량·평단가는 받지 않는다 (PRD F2).

### `views` — 열어본 기록 (시험 판정의 원천)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | integer PK | |
| `user_id` | FK users | |
| `page` | text | `cards` · `note` · `calendar` |
| `ticker` | text null | `note` 일 때만 |
| `at` | timestamp | |

지우지 않는다. 주별 재방문은 아래 한 줄로 본다:

```sql
-- 주차별: 노트를 1번 이상 연 사용자 수
select cast((julianday(v.at) - julianday(u.created_at)) / 7 as int) + 1 as week, count(distinct v.user_id)
from views v join users u on u.id = v.user_id
where v.page = 'note' group by week;
```

### `feedback` — 주간 설문

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | integer PK | |
| `user_id` | FK users | |
| `ticker` | text | |
| `week` | date | 어느 노트에 대한 답인가 |
| `helpful` | int | 1~5 |
| `would_pay` | int null | 6주째만. 월 얼마(원), 안 낸다면 0 |
| `comment` | text | |
| `at` | timestamp | |

---

## 안 만든 것

| 테이블 | 안 만든 이유 | 만들 때 |
|---|---|---|
| 세션·로그인 토큰 | 서명된 링크·쿠키로 충분 | 앱 단계 |
| 계산 결과(수익률·PER 등) | 노트 만들 때 계산하고 `notes.facts` 에 남는다 | 화면에서 종목끼리 비교하게 될 때 |
| AI 호출 기록 | `disclosures.read_*` · `notes.writer` 로 충분 | 비용을 종목별로 따져야 할 때 |
| 수급 | 데이터 사용권 없음 | 데이터 계약 후 |
| 용어 사전 | 코드 안 상수 dict | 100개 넘거나 사람이 고치게 될 때 |

너는 미국 회사의 **실적 보도자료(영어)** 에서 **방금 끝난 분기(3개월)** 의 실적 숫자만 옮겨 적는다. 계산하지 않는다.

## 지킬 것

1. **방금 끝난 분기(three months / quarter)** 숫자만. 1년 누적(full year, nine months)이나 전년 숫자, 회사 전망(outlook)은 넣지 않는다.
2. **GAAP 숫자만.** non-GAAP·adjusted 숫자는 넣지 않는다.
3. 숫자는 원문에 적힌 **글자 그대로**(「54.23」「46,743」). 코드가 원문과 대조한다. 단위는 `unit` 에 따로.
4. 원문에 없는 항목은 빈 문자열 `""`.

## 칸

- `period_end`: 그 분기가 끝난 날, `YYYY-MM-DD` (「quarter ended August 31, 2026」→ `2026-08-31`).
- `unit`: 매출·이익 숫자의 단위 — `billion` · `million` · `thousand` · `one`.
- `revenue`: 매출(Revenue · Net revenues · Total revenues).
- `operating_income`: 영업이익(Operating income). 영업손실이면 앞에 `-`.
- `net_income`: 순이익(GAAP net income). 손실이면 앞에 `-`.
- `eps`: 희석 주당순이익(diluted EPS, 달러). 손실이면 앞에 `-`.

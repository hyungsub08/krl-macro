# 코레일 매크로 테스트 가이드

## 1. 사전 준비

### 1.1 필수 환경

- Python 3.9 이상
- pip 패키지: `korail2`, `flask`

### 1.2 설치

```bash
cd /Users/hs-mini-1/Projects/@krl-macro
pip3 install -r requirements.txt
```

### 1.3 필요 정보

| 항목 | 예시 | 설명 |
|---|---|---|
| 코레일 ID | `1000170054` | 회원번호(8자리), 전화번호(`010-xxxx-xxxx`), 이메일 |
| 비밀번호 | `password123` | 코레일 계정 비밀번호 |

---

## 2. 테스트 러너 사용법

### 2.1 기본 명령어

```bash
python3 test_runner.py --id <코레일ID> --pw <비밀번호>
```

### 2.2 테스트 스위트

`--suite` 옵션으로 실행할 테스트를 선택합니다.

| 스위트 | 명령어 | 소요 시간 | 설명 |
|---|---|---|---|
| `login` | `--suite login` | ~5초 | 로그인만 테스트 |
| `search` | `--suite search` (기본값) | ~10초 | 로그인 + 열차 조회 |
| `reserve` | `--suite reserve` | ~15초 | 로그인 + 조회 + 예매 + **즉시 취소** |
| `routes` | `--suite routes` | ~30초 | 5개 구간 x 2일 = 10건 조회 |
| `stability` | `--suite stability` | ~70초 | 20회 연속 조회 (3초 간격) |
| `ttl` | `--suite ttl` | ~4분 30초 | 세션 유효시간 측정 (30초 간격, 4분) |
| `all` | `--suite all` | ~6분 | 위 전체를 순서대로 실행 |

### 2.3 사용 예시

```bash
# 기본 테스트 (로그인 + 조회)
python3 test_runner.py --id 1000170054 --pw mypassword

# 전체 테스트 (예매+취소 포함) + 상세 출력
python3 test_runner.py --id 1000170054 --pw mypassword --suite all --verbose

# 다른 구간 테스트
python3 test_runner.py --id 1000170054 --pw mypassword --dep 서울 --arr 대전

# 특정 날짜 테스트
python3 test_runner.py --id 1000170054 --pw mypassword --date 20260501

# JSON 출력 (자동화 연동용)
python3 test_runner.py --id 1000170054 --pw mypassword --suite search --json
```

### 2.4 옵션 전체 목록

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--id` | (필수) | 코레일 계정 ID |
| `--pw` | (필수) | 코레일 계정 비밀번호 |
| `--suite` | `search` | 테스트 스위트 선택 |
| `--dep` | `서울` | 출발역 |
| `--arr` | `부산` | 도착역 |
| `--date` | 내일 | 출발 날짜 (yyyyMMdd) |
| `--json` | off | 결과를 JSON으로 출력 |
| `--verbose`, `-v` | off | 개별 열차/시도 상세 출력 |

---

## 3. 각 테스트 상세 설명

### 3.1 login — 로그인 테스트

**목적**: DynaPath anti-bot 토큰 생성 및 코레일 서버 인증이 정상 동작하는지 확인

**검증 항목**:
- `DynaPathMasterEngine`이 유효한 `x-dynapath-m-token` 헤더를 생성하는가
- `Sid` (AES-CBC 암호화)가 정상 생성되는가
- 코레일 서버가 `MACRO ERROR` 없이 인증을 수락하는가
- 회원 이름과 번호가 정상 반환되는가

**실패 시 확인사항**:
- `MACRO ERROR` → DynaPath 토큰 생성 로직이 코레일 서버 변경으로 무효화됨
- `P058` → 세션 만료 (재시도하면 보통 해결)
- 인증 거부 → ID/PW 확인

### 3.2 search — 열차 조회 테스트

**목적**: 열차 검색 API가 정상 응답하는지 확인

**검증 항목**:
- 열차 목록이 JSON으로 정상 수신되는가
- 각 열차의 좌석 상태(`general_seat`, `special_seat`)가 파싱되는가
- `include_no_seats=True`로 매진 열차도 포함되는가

**실패 시 확인사항**:
- `MACRO ERROR` → 조회 API 경로에 대한 DynaPath 검증 실패
- `NoResultsError` → 해당 구간/날짜에 열차 없음 (정상 응답)
- JSON 파싱 오류 → API 응답 형식 변경 가능성

### 3.3 reserve — 예매 + 즉시 취소 테스트

**목적**: 예매 플로우가 end-to-end로 동작하는지 확인

**검증 항목**:
- 예약번호(`rsv_id`)가 정상 발급되는가
- 금액, 결제기한 등 예약 정보가 정상 반환되는가
- 취소 API가 정상 동작하는가

**주의사항**:
- 이 테스트는 **실제 예약을 생성한 뒤 즉시 취소**합니다
- 예매 성공 후 취소가 실패하면 **수동으로 취소해야** 합니다 (로그에 예약번호 출력)
- 좌석이 없는 경우 예매 테스트는 SKIP 처리됩니다

**실패 시 확인사항**:
- `SoldOutError` → 조회 시점~예매 시점 사이 매진 (타이밍 이슈, 정상)
- `ERR211161` → 매진 에러코드
- 취소 실패 → 코레일 앱/홈페이지에서 수동 취소 필요

### 3.4 routes — 다구간 조회 테스트

**목적**: 다양한 출발역/도착역/날짜 조합에서 API가 안정적으로 동작하는지 확인

**테스트 구간** (5개 구간 x 내일/다음주 = 10건):

| 출발 | 도착 |
|---|---|
| 서울 | 대전 |
| 서울 | 광주송정 |
| 용산 | 목포 |
| 서울 | 강릉 |
| 동대구 | 부산 |

**검증 항목**:
- 모든 구간에서 `MACRO ERROR` 없이 응답하는가
- 다양한 구간 호출 시에도 세션이 유지되는가

### 3.5 stability — 반복 조회 안정성 테스트

**목적**: 매크로의 핵심 동작인 "반복 조회"가 안정적으로 동작하는지 확인

**조건**: 동일 구간 20회 연속 조회, 3초 간격

**검증 항목**:
- 20회 모두 성공하는가
- 중간에 `MACRO ERROR`가 발생하지 않는가 (Rate Limiting 탐지)
- 세션이 끊기지 않는가

**실패 시 확인사항**:
- 특정 횟수 이후 실패 → 코레일 서버의 Rate Limiting 정책 변경 가능성
- `MACRO ERROR` → anti-bot 정책 강화

### 3.6 ttl — 토큰/세션 TTL 테스트

**목적**: 로그인 후 세션이 얼마나 오래 유지되는지 측정

**조건**: 30초 간격으로 4분(240초)간 조회 (총 9회)

**검증 항목**:
- 어느 시점에 세션이 만료되는가
- 만료 시 에러 유형 (`MACRO ERROR` vs `P058`)

**참고**: 현재 테스트 결과 4분 이상 세션 유지 확인됨. 더 긴 TTL 측정이 필요하면 스크립트의 `duration` 파라미터를 조정.

---

## 4. 테스트 결과 해석

### 4.1 출력 예시 (일반)

```
코레일 API 통합 테스트
시각: 2026-04-08 11:00:00
스위트: search (로그인 + 열차 조회)
구간: 서울 → 부산 (20260409)

========================================================
  테스트: 로그인
========================================================
  ID: 1000****54
  [PASS] 로그인 성공: 홍길동 (1000170054)

========================================================
  테스트: 열차 조회 (서울→부산, 20260409)
========================================================
  [PASS] 서울→부산: 10건 조회, 3건 예약가능

========================================================
  테스트 결과: PASS
========================================================
  총 2건 | PASS 2 | FAIL 0 | SKIP 0
```

### 4.2 출력 예시 (JSON)

```json
{
  "overall": "PASS",
  "summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0},
  "results": [
    {"test": "login", "status": "PASS", "msg": "로그인 성공: 홍길동 (1000170054)"},
    {"test": "search", "status": "PASS", "msg": "서울→부산: 10건 조회, 3건 예약가능", "count": 10, "available": 3}
  ],
  "timestamp": "2026-04-08 11:00:00"
}
```

### 4.3 상태 코드

| 상태 | 의미 |
|---|---|
| `PASS` | 테스트 성공 |
| `FAIL` | 테스트 실패 (에러 발생) |
| `SKIP` | 전제 조건 미충족으로 건너뜀 (예: 좌석 없어서 예매 불가) |

### 4.4 종료 코드

| 코드 | 의미 |
|---|---|
| `0` | 모든 테스트 PASS (SKIP은 OK) |
| `1` | 1건 이상 FAIL |
| `130` | Ctrl+C로 중단 |

---

## 5. 트러블슈팅

### 5.1 `MACRO ERROR` 발생

```
h_msg_cd=MACRO ERROR
h_msg_txt=원활한 서비스 이용을 위해 앱을 최신 버전으로 업데이트해 주시기 바랍니다.
```

**원인**: 코레일 서버의 DynaPath anti-bot 검증 실패

**조치**:
1. korail2 라이브러리의 패치가 적용되어 있는지 확인:
   ```bash
   python3 -c "from korail2.korail2 import DynaPathMasterEngine; print('패치 적용됨')"
   ```
2. 패치가 적용되어 있는데도 실패하면 코레일이 DynaPath 알고리즘/키를 변경한 것
3. korail2 GitHub 저장소의 이슈/PR 확인: https://github.com/carpedm20/korail2

### 5.2 로그인 실패

**`P058` 에러**: 세션 만료 → 재시도

**인증 거부 (SUCC가 아닌 FAIL)**: 
- ID/PW 오타 확인
- 코레일 홈페이지에서 직접 로그인이 되는지 확인
- 계정 잠금 여부 확인

### 5.3 조회는 되는데 예매 실패

- `SoldOutError`: 조회~예매 사이 타이밍 매진 (정상 동작)
- `ERR211161`: 매진 에러코드 (정상 동작)
- 기타 에러: 파라미터 형식 변경 가능성 → API 응답 확인 필요

### 5.4 취소 실패 시 긴급 조치

예매 성공 후 취소가 실패하면:
1. 로그에 출력된 **예약번호**를 확인
2. 코레일톡 앱 또는 https://www.letskorail.com 에서 **직접 취소**
3. 결제기한(보통 20분) 내 미결제 시 자동 취소됨

### 5.5 `ModuleNotFoundError: No module named 'korail2'`

```bash
pip3 install korail2
```

설치 후에도 안 되면 Python 경로 확인:
```bash
python3 -c "import korail2; print(korail2.__file__)"
```

---

## 6. 파일 구조

```
@krl-macro/
├── app.py                 # Flask 웹 서버 (매크로 웹 UI)
├── macro.py               # CLI 매크로
├── test_runner.py         # 통합 테스트 러너 (이 문서의 주 대상)
├── test_connection.py     # 단계별 수동 테스트 (대화형)
├── config.example.ini     # CLI용 설정 예시
├── requirements.txt       # Python 의존성
├── templates/
│   └── index.html         # 웹 UI
├── ANALYSIS.md            # 기술 분석 및 방어 대책
└── TEST_GUIDE.md          # 이 문서
```

---

## 7. 빠른 시작 요약

```bash
# 1. 설치
pip3 install -r requirements.txt

# 2. 기본 테스트 (로그인 + 조회)
python3 test_runner.py --id <ID> --pw <PW>

# 3. 전체 테스트
python3 test_runner.py --id <ID> --pw <PW> --suite all -v

# 4. 웹 매크로 실행
python3 app.py
# → 브라우저에서 http://localhost:5000 접속
```

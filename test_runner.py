#!/usr/bin/env python3
"""코레일 API 통합 테스트 러너

사용법:
    python3 test_runner.py                    # 전체 테스트 (예매 제외)
    python3 test_runner.py --suite all        # 전체 테스트 (예매+취소 포함)
    python3 test_runner.py --suite login      # 로그인만
    python3 test_runner.py --suite search     # 로그인 + 조회
    python3 test_runner.py --suite reserve    # 예매 + 즉시 취소
    python3 test_runner.py --suite stability  # 반복 조회 안정성
    python3 test_runner.py --suite ttl        # 토큰 TTL
    python3 test_runner.py --suite routes     # 다구간 조회

옵션:
    --id ID        코레일 회원번호/전화번호/이메일
    --pw PW        코레일 비밀번호
    --dep DEP      출발역 (기본: 서울)
    --arr ARR      도착역 (기본: 부산)
    --date DATE    출발 날짜 yyyyMMdd (기본: 내일)
    --json         JSON 출력
    --verbose      상세 출력
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta

from korail2 import (
    AdultPassenger,
    Korail,
    KorailError,
    NoResultsError,
    ReserveOption,
    SoldOutError,
    TrainType,
)


# ── 출력 유틸 ───────────────────────────────────────────────

class TestReporter:
    def __init__(self, verbose=False, use_json=False):
        self.verbose = verbose
        self.use_json = use_json
        self.results = []

    def header(self, title):
        if not self.use_json:
            print(f"\n{'='*60}")
            print(f"  {title}")
            print(f"{'='*60}")

    def info(self, msg):
        if not self.use_json:
            print(f"  {msg}")

    def detail(self, msg):
        if self.verbose and not self.use_json:
            print(f"    {msg}")

    def ok(self, test_name, msg, **extra):
        self.results.append({"test": test_name, "status": "PASS", "msg": msg, **extra})
        if not self.use_json:
            print(f"  [PASS] {msg}")

    def fail(self, test_name, msg, **extra):
        self.results.append({"test": test_name, "status": "FAIL", "msg": msg, **extra})
        if not self.use_json:
            print(f"  [FAIL] {msg}")

    def skip(self, test_name, msg):
        self.results.append({"test": test_name, "status": "SKIP", "msg": msg})
        if not self.use_json:
            print(f"  [SKIP] {msg}")

    def summary(self):
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        skipped = sum(1 for r in self.results if r["status"] == "SKIP")
        total = len(self.results)
        overall = "PASS" if failed == 0 else "FAIL"

        if self.use_json:
            print(json.dumps({
                "overall": overall,
                "summary": {"total": total, "passed": passed, "failed": failed, "skipped": skipped},
                "results": self.results,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False, indent=2))
        else:
            print(f"\n{'='*60}")
            print(f"  테스트 결과: {overall}")
            print(f"{'='*60}")
            print(f"  총 {total}건 | PASS {passed} | FAIL {failed} | SKIP {skipped}")
            if failed > 0:
                print(f"\n  실패 항목:")
                for r in self.results:
                    if r["status"] == "FAIL":
                        print(f"    - [{r['test']}] {r['msg']}")
            print()

        return 0 if failed == 0 else 1


# ── 테스트 스위트 ───────────────────────────────────────────

def test_login(korail_id, korail_pw, rpt):
    """로그인 테스트"""
    rpt.header("테스트: 로그인")
    rpt.info(f"ID: {korail_id[:4]}****{korail_id[-2:]}")

    try:
        korail = Korail(korail_id, korail_pw, auto_login=True)
    except Exception as e:
        rpt.fail("login", f"로그인 예외: {e}", error=str(e))
        return None

    if korail.logined:
        rpt.ok("login", f"로그인 성공: {korail.name} ({korail.membership_number})",
               name=korail.name, membership=korail.membership_number)
        return korail
    else:
        rpt.fail("login", "로그인 거부 (인증 실패)")
        return None


def test_search(korail, dep, arr, date, rpt):
    """단일 구간 조회 테스트"""
    rpt.header(f"테스트: 열차 조회 ({dep}→{arr}, {date})")

    try:
        trains = korail.search_train(
            dep, arr, date, "070000",
            train_type=TrainType.KTX,
            passengers=[AdultPassenger()],
            include_no_seats=True,
        )
    except NoResultsError:
        rpt.ok("search", f"{dep}→{arr}: API 정상 응답 (결과 0건)", count=0, available=0)
        return []
    except Exception as e:
        rpt.fail("search", f"{dep}→{arr}: 조회 실패 - {e}", error=str(e))
        return None

    avail = sum(1 for t in trains if t.has_seat())
    rpt.ok("search", f"{dep}→{arr}: {len(trains)}건 조회, {avail}건 예약가능",
           count=len(trains), available=avail)

    for t in trains:
        seat = []
        if t.has_general_seat(): seat.append("일반O")
        elif t.general_seat == '13': seat.append("일반X")
        if t.has_special_seat(): seat.append("특실O")
        elif t.special_seat == '13': seat.append("특실X")
        dep_t = f"{t.dep_time[:2]}:{t.dep_time[2:4]}"
        arr_t = f"{t.arr_time[:2]}:{t.arr_time[2:4]}"
        rpt.detail(f"{t.train_type_name} {t.train_no}호 {dep_t}→{arr_t} [{', '.join(seat)}]")

    return trains


def test_reserve_cancel(korail, trains, rpt):
    """예매 + 즉시 취소 테스트"""
    rpt.header("테스트: 예매 + 즉시 취소")

    available = [t for t in trains if t.has_seat()]
    if not available:
        rpt.skip("reserve", "예약 가능한 열차 없음 (전석 매진)")
        return

    target = available[0]
    dep_t = f"{target.dep_time[:2]}:{target.dep_time[2:4]}"
    train_info = f"{target.train_type_name} {target.train_no}호 {dep_t}"
    rpt.info(f"대상: {train_info}")

    # 예매
    try:
        rsv = korail.reserve(target, passengers=[AdultPassenger()],
                             option=ReserveOption.GENERAL_FIRST)
    except SoldOutError:
        rpt.ok("reserve", f"예매 API 호출 성공 (타이밍 매진 - API 자체는 정상)")
        return
    except Exception as e:
        rpt.fail("reserve", f"예매 실패: {e}", error=str(e))
        return

    rpt.ok("reserve", f"예매 성공: {rsv.rsv_id} ({rsv.price}원)",
           rsv_id=rsv.rsv_id, price=rsv.price)

    # 즉시 취소
    try:
        korail.cancel(rsv)
        rpt.ok("cancel", f"취소 성공: {rsv.rsv_id}")
    except Exception as e:
        rpt.fail("cancel", f"취소 실패: {e} (수동 취소 필요! 예약번호: {rsv.rsv_id})",
                 error=str(e), rsv_id=rsv.rsv_id)


def test_multi_routes(korail, rpt):
    """다구간 조회 테스트"""
    rpt.header("테스트: 다구간 조회")

    routes = [
        ("서울", "대전"), ("서울", "광주송정"), ("용산", "목포"),
        ("서울", "강릉"), ("동대구", "부산"),
    ]
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    next_week = (datetime.now() + timedelta(days=7)).strftime("%Y%m%d")

    for dep, arr in routes:
        for date in [tomorrow, next_week]:
            label = f"{dep}→{arr} ({date})"
            try:
                trains = korail.search_train(
                    dep, arr, date, "070000",
                    train_type=TrainType.KTX,
                    passengers=[AdultPassenger()],
                    include_no_seats=True,
                )
                avail = sum(1 for t in trains if t.has_seat())
                rpt.ok(f"route:{label}", f"{label}: {len(trains)}건 ({avail}건 가능)",
                       count=len(trains), available=avail)
            except NoResultsError:
                rpt.ok(f"route:{label}", f"{label}: API 정상 (결과 0건)")
            except Exception as e:
                rpt.fail(f"route:{label}", f"{label}: {e}", error=str(e))


def test_stability(korail, dep, arr, date, rpt, count=20, interval=3):
    """반복 조회 안정성 테스트"""
    rpt.header(f"테스트: 반복 조회 안정성 ({count}회, {interval}초 간격)")

    ok_count = 0
    fail_count = 0

    for i in range(1, count + 1):
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            trains = korail.search_train(
                dep, arr, date, "070000",
                train_type=TrainType.KTX,
                passengers=[AdultPassenger()],
                include_no_seats=True,
            )
            ok_count += 1
            rpt.detail(f"[{ts}] #{i:02d}: OK ({len(trains)}건)")
        except NoResultsError:
            ok_count += 1
            rpt.detail(f"[{ts}] #{i:02d}: OK (0건)")
        except Exception as e:
            fail_count += 1
            rpt.detail(f"[{ts}] #{i:02d}: FAIL - {e}")

        if i < count:
            time.sleep(interval)

    if fail_count == 0:
        rpt.ok("stability", f"{count}회 연속 조회 모두 성공")
    else:
        rpt.fail("stability", f"{count}회 중 {fail_count}회 실패",
                 ok=ok_count, fail=fail_count)


def test_ttl(korail, dep, arr, date, rpt, duration=240, step=30):
    """토큰/세션 TTL 테스트"""
    points = list(range(0, duration + 1, step))
    rpt.header(f"테스트: 세션 TTL ({duration}초, {step}초 간격)")
    rpt.info(f"테스트 포인트: {points}초")

    start = time.time()
    last_ok_sec = 0
    first_fail_sec = None

    for target_sec in points:
        elapsed = time.time() - start
        if target_sec > elapsed:
            wait = target_sec - elapsed
            rpt.detail(f"대기 {wait:.0f}초...")
            time.sleep(wait)

        actual_sec = int(time.time() - start)
        ts = datetime.now().strftime("%H:%M:%S")

        try:
            trains = korail.search_train(
                dep, arr, date, "070000",
                train_type=TrainType.KTX,
                passengers=[AdultPassenger()],
                include_no_seats=True,
            )
            rpt.detail(f"[{ts}] +{actual_sec}s: OK ({len(trains)}건)")
            last_ok_sec = actual_sec
        except NoResultsError:
            rpt.detail(f"[{ts}] +{actual_sec}s: OK (0건)")
            last_ok_sec = actual_sec
        except Exception as e:
            rpt.detail(f"[{ts}] +{actual_sec}s: FAIL - {e}")
            if first_fail_sec is None:
                first_fail_sec = actual_sec

    if first_fail_sec is None:
        rpt.ok("ttl", f"세션 {duration}초 이상 유효 (만료 없음)",
               ttl_lower_bound=duration)
    else:
        rpt.fail("ttl", f"+{first_fail_sec}초에 만료 (마지막 성공: +{last_ok_sec}초)",
                 first_fail=first_fail_sec, last_ok=last_ok_sec)


# ── 메인 ────────────────────────────────────────────────────

SUITES = {
    "login":     "로그인만 테스트",
    "search":    "로그인 + 열차 조회",
    "reserve":   "로그인 + 조회 + 예매/취소",
    "routes":    "로그인 + 다구간 조회 (5구간 x 2일)",
    "stability": "로그인 + 반복 조회 20회",
    "ttl":       "로그인 + 세션 TTL 측정 (4분)",
    "all":       "전체 테스트",
}


def main():
    parser = argparse.ArgumentParser(
        description="코레일 API 통합 테스트 러너",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(f"  {k:12s} {v}" for k, v in SUITES.items()),
    )
    parser.add_argument("--suite", default="search", choices=SUITES.keys(),
                        help="실행할 테스트 스위트 (기본: search)")
    parser.add_argument("--id", dest="korail_id", required=True,
                        help="코레일 회원번호/전화번호/이메일")
    parser.add_argument("--pw", dest="korail_pw", required=True,
                        help="코레일 비밀번호")
    parser.add_argument("--dep", default="서울", help="출발역 (기본: 서울)")
    parser.add_argument("--arr", default="부산", help="도착역 (기본: 부산)")
    parser.add_argument("--date", default=None,
                        help="출발 날짜 yyyyMMdd (기본: 내일)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 출력")
    args = parser.parse_args()

    date = args.date or (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    suite = args.suite
    rpt = TestReporter(verbose=args.verbose, use_json=args.json)

    if not args.json:
        print(f"\n코레일 API 통합 테스트")
        print(f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"스위트: {suite} ({SUITES[suite]})")
        print(f"구간: {args.dep} → {args.arr} ({date})")

    # 모든 스위트는 로그인이 필요
    korail = test_login(args.korail_id, args.korail_pw, rpt)
    if korail is None:
        return rpt.summary()

    if suite == "login":
        return rpt.summary()

    # 조회
    if suite in ("search", "reserve", "all"):
        trains = test_search(korail, args.dep, args.arr, date, rpt)
    else:
        trains = None

    # 예매+취소
    if suite in ("reserve", "all") and trains:
        test_reserve_cancel(korail, trains, rpt)

    # 다구간
    if suite in ("routes", "all"):
        test_multi_routes(korail, rpt)

    # 반복 안정성
    if suite in ("stability", "all"):
        test_stability(korail, args.dep, args.arr, date, rpt)

    # TTL
    if suite in ("ttl", "all"):
        test_ttl(korail, args.dep, args.arr, date, rpt)

    return rpt.summary()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[중단] Ctrl+C")
        sys.exit(130)

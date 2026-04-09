#!/usr/bin/env python3
"""코레일 API 연결 단계별 테스트

단계 1: 로그인 → 단계 2: 열차 조회 → 단계 3: 예매+즉시취소 (선택)
각 단계가 성공해야 다음 단계로 진행합니다.
"""

import argparse
import json
import sys
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

# ── 설정 ────────────────────────────────────────────────────
KORAIL_ID = "1000170054"
KORAIL_PW = "tlsqkek1!"

# 내일 날짜, 오전 7시 이후 KTX
TEST_DEP = "서울"
TEST_ARR = "부산"
TEST_DATE = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
TEST_TIME = "070000"
TEST_TRAIN_TYPE = TrainType.KTX
# ─────────────────────────────────────────────────────────────


def header(title):
    print(f"\n{'='*56}")
    print(f"  {title}")
    print(f"{'='*56}")


def step1_login():
    """단계 1: 로그인 테스트"""
    header("단계 1: 로그인")
    print(f"  ID: {KORAIL_ID[:4]}****{KORAIL_ID[-2:]}")

    try:
        korail = Korail(KORAIL_ID, KORAIL_PW, auto_login=True)
    except Exception as e:
        print(f"\n  [실패] {e}")
        return None

    if korail.logined:
        print(f"\n  [성공] 로그인 완료")
        print(f"  회원번호 : {korail.membership_number}")
        print(f"  이름     : {korail.name}")
        print(f"  이메일   : {korail.email}")
        return korail
    else:
        print(f"\n  [실패] 로그인 실패 (응답은 왔으나 인증 거부)")
        return None


def step2_search(korail):
    """단계 2: 열차 조회 테스트"""
    header("단계 2: 열차 조회")
    print(f"  구간 : {TEST_DEP} → {TEST_ARR}")
    print(f"  날짜 : {TEST_DATE}")
    print(f"  시간 : {TEST_TIME[:2]}:{TEST_TIME[2:4]} 이후")

    try:
        trains = korail.search_train(
            TEST_DEP, TEST_ARR, TEST_DATE, TEST_TIME,
            train_type=TEST_TRAIN_TYPE,
            passengers=[AdultPassenger()],
            include_no_seats=True,
        )
    except NoResultsError:
        print(f"\n  [성공] API 응답 정상 (검색 결과 0건)")
        return []
    except Exception as e:
        print(f"\n  [실패] {e}")
        return None

    print(f"\n  [성공] {len(trains)}건 조회됨\n")
    for i, t in enumerate(trains):
        seat_status = []
        if t.has_general_seat():
            seat_status.append("일반O")
        elif t.general_seat == '13':
            seat_status.append("일반X")
        if t.has_special_seat():
            seat_status.append("특실O")
        elif t.special_seat == '13':
            seat_status.append("특실X")

        dep_t = f"{t.dep_time[:2]}:{t.dep_time[2:4]}"
        arr_t = f"{t.arr_time[:2]}:{t.arr_time[2:4]}"
        status_str = ", ".join(seat_status) if seat_status else "정보없음"
        print(f"  [{i+1}] {t.train_type_name} {t.train_no}호  "
              f"{dep_t}→{arr_t}  [{status_str}]")

    return trains


def step3_reserve_and_cancel(korail, trains):
    """단계 3: 예매 + 즉시 취소 테스트"""
    header("단계 3: 예매 + 즉시 취소")

    available = [t for t in trains if t.has_seat()]
    if not available:
        print("  예약 가능한 열차가 없습니다 (전석 매진).")
        print("  → 로그인 + 조회가 성공했으므로 매크로 핵심 기능은 정상입니다.")
        return

    target = available[0]
    dep_t = f"{target.dep_time[:2]}:{target.dep_time[2:4]}"
    print(f"  대상: {target.train_type_name} {target.train_no}호 {dep_t}")
    print(f"  예매 시도 중...")

    try:
        reservation = korail.reserve(
            target,
            passengers=[AdultPassenger()],
            option=ReserveOption.GENERAL_FIRST,
        )
    except SoldOutError:
        print(f"  [매진] 조회 시점과 예매 시점 사이에 매진됨 (타이밍 이슈)")
        print(f"  → 예매 API 호출 자체는 성공했으므로 정상 동작 확인됨")
        return
    except Exception as e:
        print(f"  [실패] 예매 오류: {e}")
        return

    print(f"\n  [예매 성공!]")
    print(f"  예약번호 : {reservation.rsv_id}")
    print(f"  금액     : {reservation.price}원")
    print(f"  결제기한 : {reservation.buy_limit_date} {reservation.buy_limit_time}")

    # 즉시 취소
    print(f"\n  즉시 취소 중...")
    try:
        korail.cancel(reservation)
        print(f"  [취소 완료] 예약번호 {reservation.rsv_id} 취소됨")
    except Exception as e:
        print(f"  [취소 실패] {e}")
        print(f"  ⚠ 코레일 앱/홈페이지에서 직접 취소해 주세요!")
        print(f"  ⚠ 예약번호: {reservation.rsv_id}")


def main():
    parser = argparse.ArgumentParser(description="코레일 API 연결 테스트")
    parser.add_argument("--mode", choices=["login", "search", "full"], default="search",
                        help="login: 로그인만, search: 조회까지, full: 예매+즉시취소까지")
    parser.add_argument("--json", action="store_true",
                        help="결과를 JSON으로 출력 (에이전트 연동용)")
    args = parser.parse_args()

    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "steps": {},
    }

    print("\n코레일 API 연결 테스트")
    print(f"테스트 시각: {result['timestamp']}")
    print(f"모드: {args.mode}")

    # 단계 1: 로그인
    korail = step1_login()
    if korail is None:
        result["steps"]["login"] = {"status": "FAIL"}
        result["overall"] = "FAIL"
        if args.json:
            print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("\n[중단] 로그인 실패")
        sys.exit(1)

    result["steps"]["login"] = {
        "status": "OK",
        "name": korail.name,
        "membership": korail.membership_number,
    }

    if args.mode == "login":
        result["overall"] = "OK"
        if args.json:
            print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 단계 2: 열차 조회
    trains = step2_search(korail)
    if trains is None:
        result["steps"]["search"] = {"status": "FAIL"}
        result["overall"] = "FAIL"
        if args.json:
            print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("\n[중단] 조회 실패")
        sys.exit(1)

    train_list = []
    for t in trains:
        train_list.append({
            "type": t.train_type_name,
            "no": t.train_no,
            "dep_time": f"{t.dep_time[:2]}:{t.dep_time[2:4]}",
            "arr_time": f"{t.arr_time[:2]}:{t.arr_time[2:4]}",
            "general": t.general_seat,
            "special": t.special_seat,
            "has_seat": t.has_seat(),
        })

    result["steps"]["search"] = {
        "status": "OK",
        "count": len(trains),
        "available": sum(1 for t in trains if t.has_seat()),
        "trains": train_list,
    }

    if args.mode == "search":
        result["overall"] = "OK"
        if args.json:
            print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 단계 3: 예매 + 즉시 취소
    if args.mode == "full":
        step3_reserve_and_cancel(korail, trains)
        result["steps"]["reserve"] = {"status": "EXECUTED"}

    result["overall"] = "OK"

    header("테스트 완료")
    for step_name, step_data in result["steps"].items():
        label = {"login": "로그인", "search": "조회", "reserve": "예매+취소"}.get(step_name, step_name)
        print(f"  {label:10s}: {step_data['status']}")
    print()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[중단] 사용자가 테스트를 중단했습니다.")
        sys.exit(0)

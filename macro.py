#!/usr/bin/env python3
"""코레일 매진 표 자동 예매 매크로"""

import configparser
import sys
import time
from datetime import datetime

from korail2 import (
    AdultPassenger,
    ChildPassenger,
    Korail,
    NoResultsError,
    ReserveOption,
    SeniorPassenger,
    SoldOutError,
    TrainType,
)

# ── 설정 로드 ──────────────────────────────────────────────

TRAIN_TYPE_MAP = {
    "ALL": TrainType.ALL,
    "KTX": TrainType.KTX,
    "SAEMAEUL": TrainType.SAEMAEUL,
    "MUGUNGHWA": TrainType.MUGUNGHWA,
    "ITX_CHEONGCHUN": TrainType.ITX_CHEONGCHUN,
    "NURIRO": TrainType.NURIRO,
}

SEAT_OPTION_MAP = {
    "GENERAL_FIRST": ReserveOption.GENERAL_FIRST,
    "GENERAL_ONLY": ReserveOption.GENERAL_ONLY,
    "SPECIAL_FIRST": ReserveOption.SPECIAL_FIRST,
    "SPECIAL_ONLY": ReserveOption.SPECIAL_ONLY,
}


def load_config(path="config.ini"):
    cfg = configparser.ConfigParser()
    if not cfg.read(path, encoding="utf-8"):
        print(f"[오류] 설정 파일을 찾을 수 없습니다: {path}")
        print("config.example.ini 을 config.ini 로 복사한 뒤 수정하세요.")
        sys.exit(1)
    return cfg


def build_passengers(cfg):
    passengers = []
    adult = int(cfg.get("passengers", "adult", fallback="1"))
    child = int(cfg.get("passengers", "child", fallback="0"))
    senior = int(cfg.get("passengers", "senior", fallback="0"))

    if adult > 0:
        passengers.append(AdultPassenger(adult))
    if child > 0:
        passengers.append(ChildPassenger(child))
    if senior > 0:
        passengers.append(SeniorPassenger(senior))

    if not passengers:
        passengers.append(AdultPassenger())

    return passengers


# ── 메인 로직 ──────────────────────────────────────────────


def run():
    cfg = load_config()

    # 계정
    korail_id = cfg["account"]["id"]
    korail_pw = cfg["account"]["pw"]

    # 열차 조건
    dep = cfg["train"]["dep"]
    arr = cfg["train"]["arr"]
    date = cfg["train"]["date"]
    time_str = cfg["train"]["time"]
    train_type = TRAIN_TYPE_MAP.get(
        cfg.get("train", "train_type", fallback="ALL").upper(), TrainType.ALL
    )
    seat_option = SEAT_OPTION_MAP.get(
        cfg.get("train", "seat_option", fallback="GENERAL_FIRST").upper(),
        ReserveOption.GENERAL_FIRST,
    )

    # 승객
    passengers = build_passengers(cfg)

    # 매크로 설정
    interval = float(cfg.get("macro", "interval", fallback="1.0"))
    max_attempts = int(cfg.get("macro", "max_attempts", fallback="0"))
    train_numbers_raw = cfg.get("macro", "train_numbers", fallback="").strip()
    target_numbers = (
        {n.strip() for n in train_numbers_raw.split(",") if n.strip()}
        if train_numbers_raw
        else set()
    )

    # 안내 출력
    print("=" * 56)
    print("  코레일 자동 예매 매크로")
    print("=" * 56)
    print(f"  구간      : {dep} → {arr}")
    print(f"  날짜/시간 : {date} / {time_str}")
    print(f"  열차 종류 : {cfg.get('train', 'train_type', fallback='ALL')}")
    print(f"  좌석 옵션 : {cfg.get('train', 'seat_option', fallback='GENERAL_FIRST')}")
    passenger_desc = []
    for p in passengers:
        if isinstance(p, SeniorPassenger):
            passenger_desc.append(f"경로 {p.count}명")
        elif isinstance(p, ChildPassenger):
            passenger_desc.append(f"어린이 {p.count}명")
        else:
            passenger_desc.append(f"어른 {p.count}명")
    print(f"  승객      : {', '.join(passenger_desc)}")
    if target_numbers:
        print(f"  열차번호  : {', '.join(sorted(target_numbers))}")
    print(f"  조회 간격 : {interval}초")
    print(f"  최대 시도 : {'무제한' if max_attempts == 0 else f'{max_attempts}회'}")
    print("=" * 56)

    # 로그인
    print("\n[로그인 중...]")
    try:
        korail = Korail(korail_id, korail_pw, auto_login=True)
    except Exception as e:
        print(f"[오류] 로그인 실패: {e}")
        sys.exit(1)
    print("[로그인 성공]\n")

    # 매크로 시작
    attempt = 0
    while True:
        attempt += 1
        if max_attempts > 0 and attempt > max_attempts:
            print(f"\n[종료] 최대 시도 횟수({max_attempts}회)에 도달했습니다.")
            break

        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] 조회 시도 #{attempt}...", end=" ")

        try:
            trains = korail.search_train(
                dep,
                arr,
                date,
                time_str,
                train_type=train_type,
                passengers=passengers,
                include_no_seats=True,
            )
        except NoResultsError:
            print("검색 결과 없음")
            time.sleep(interval)
            continue
        except Exception as e:
            print(f"조회 오류: {e}")
            # 세션 만료 시 재로그인
            if "P058" in str(e) or "로그인" in str(e):
                print("[재로그인 시도...]")
                try:
                    korail.login(korail_id, korail_pw)
                    print("[재로그인 성공]")
                except Exception:
                    print("[재로그인 실패] 프로그램을 종료합니다.")
                    sys.exit(1)
            time.sleep(interval)
            continue

        # 예약 가능한 열차 필터링
        available = []
        for train in trains:
            # 특정 열차번호 필터
            if target_numbers and train.train_no not in target_numbers:
                continue
            if train.has_seat():
                available.append(train)

        if not available:
            sold_out_count = len(trains)
            if target_numbers:
                sold_out_count = sum(
                    1 for t in trains if t.train_no in target_numbers
                )
            print(f"매진 (조회 {sold_out_count}건)")
            time.sleep(interval)
            continue

        # 예약 가능한 열차 발견 → 예매 시도
        for train in available:
            train_info = (
                f"{train.train_type_name} {train.train_no}호 "
                f"{train.dep_time[:2]}:{train.dep_time[2:4]} "
                f"{train.dep_name}→{train.arr_name}"
            )
            print(f"\n\n{'=' * 56}")
            print(f"  좌석 발견! {train_info}")
            print(f"{'=' * 56}")

            try:
                reservation = korail.reserve(
                    train,
                    passengers=passengers,
                    option=seat_option,
                )
                print(f"\n  *** 예매 성공! ***")
                print(f"  예약번호  : {reservation.rsv_id}")
                print(f"  열차      : {train_info}")
                print(f"  결제기한  : {reservation.buy_limit_date} {reservation.buy_limit_time}")
                print(f"  금액      : {reservation.price}원")
                print(f"{'=' * 56}\n")
                print("결제 기한 내에 결제를 완료해 주세요.")
                return  # 예매 성공 시 종료

            except SoldOutError:
                print(f"  예매 실패 (매진) - 다음 열차 시도...")
                continue
            except Exception as e:
                print(f"  예매 오류: {e}")
                continue

        # 모든 available 열차 예매 실패 시 계속 시도
        print("예매 가능 열차 모두 실패, 재시도...")
        time.sleep(interval)

    print("\n프로그램을 종료합니다.")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n[사용자 중단] 프로그램을 종료합니다.")
        sys.exit(0)

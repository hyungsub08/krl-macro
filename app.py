#!/usr/bin/env python3
"""코레일 매진 표 자동 예매 - 웹 서버"""

import threading
import time
import uuid
from datetime import datetime

from flask import Flask, jsonify, render_template, request

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

app = Flask(__name__)

# ── 상수 ────────────────────────────────────────────────────

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

# 주요 역 목록
STATIONS = [
    "서울", "용산", "영등포", "광명", "수원", "천안아산", "오송", "대전",
    "서대전", "김천구미", "구미", "동대구", "경주", "포항", "밀양",
    "울산(통도사)", "부산", "마산", "창원중앙", "진주", "익산", "전주",
    "광주송정", "광주", "목포", "여수EXPO", "순천", "강릉", "동해",
    "정동진", "춘천", "원주", "제천", "안동", "영주", "행신", "인천공항T2",
]

# ── 세션 저장소 ─────────────────────────────────────────────

sessions = {}  # session_id -> MacroSession


class MacroSession:
    def __init__(self):
        self.logs = []
        self.status = "idle"  # idle, running, stopped, success, error
        self.attempt = 0
        self.reservation = None
        self.stop_flag = False
        self.thread = None
        self.korail = None

    def log(self, msg, level="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = {"time": ts, "msg": msg, "level": level}
        self.logs.append(entry)
        # 최대 500개 로그 유지
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def stop(self):
        self.stop_flag = True
        self.status = "stopped"


# ── 매크로 워커 ─────────────────────────────────────────────


def build_passengers(adult, child, senior):
    passengers = []
    if adult > 0:
        passengers.append(AdultPassenger(adult))
    if child > 0:
        passengers.append(ChildPassenger(child))
    if senior > 0:
        passengers.append(SeniorPassenger(senior))
    return passengers or [AdultPassenger()]


def macro_worker(session, params):
    try:
        session.status = "running"
        session.log("로그인 중...")

        try:
            korail = Korail(params["id"], params["pw"], auto_login=True)
            session.korail = korail
        except Exception as e:
            session.log(f"로그인 실패: {e}", "error")
            session.status = "error"
            return

        session.log("로그인 성공!")

        passengers = build_passengers(
            params["adult"], params["child"], params["senior"]
        )
        train_type = TRAIN_TYPE_MAP.get(params["train_type"], TrainType.ALL)
        seat_option = SEAT_OPTION_MAP.get(params["seat_option"], ReserveOption.GENERAL_FIRST)
        interval = params["interval"]
        max_attempts = params["max_attempts"]

        target_numbers = set()
        if params.get("train_numbers"):
            target_numbers = {
                n.strip() for n in params["train_numbers"].split(",") if n.strip()
            }

        session.log(
            f"매크로 시작: {params['dep']} → {params['arr']} "
            f"({params['date']} {params['time']})"
        )

        while not session.stop_flag:
            session.attempt += 1
            if max_attempts > 0 and session.attempt > max_attempts:
                session.log(f"최대 시도 횟수({max_attempts}회) 도달", "warn")
                session.status = "stopped"
                return

            try:
                trains = korail.search_train(
                    params["dep"],
                    params["arr"],
                    params["date"],
                    params["time"],
                    train_type=train_type,
                    passengers=passengers,
                    include_no_seats=True,
                )
            except NoResultsError:
                session.log(f"#{session.attempt} 검색 결과 없음")
                time.sleep(interval)
                continue
            except Exception as e:
                err = str(e)
                session.log(f"#{session.attempt} 조회 오류: {e}", "warn")
                if "P058" in err or "로그인" in err:
                    session.log("세션 만료 - 재로그인 시도...")
                    try:
                        korail.login(params["id"], params["pw"])
                        session.log("재로그인 성공")
                    except Exception:
                        session.log("재로그인 실패", "error")
                        session.status = "error"
                        return
                elif "MACRO ERROR" in err or "최신 버전" in err or "업데이트" in err:
                    session.consecutive_macro_errors = getattr(session, "consecutive_macro_errors", 0) + 1
                    if session.consecutive_macro_errors == 1:
                        session.log("⚠ DynaPath anti-bot 차단 감지", "error")
                        session.log("원인: 앱 버전 또는 토큰 알고리즘이 서버 검증과 불일치", "error")
                        session.log("대응 1: 간격을 5초 이상으로 늘려 재시도", "warn")
                        session.log("대응 2: 지속 실패 시 korail2 라이브러리의 _version 및 DynaPath 알고리즘 업데이트 필요", "warn")
                        session.log("상세 가이드: ANALYSIS.md 섹션 8.2 참조", "warn")
                    if session.consecutive_macro_errors >= 3:
                        session.log(f"MACRO ERROR {session.consecutive_macro_errors}회 연속 발생 - 매크로 중지", "error")
                        session.log("권장 대안: TLS 에뮬레이션(curl_cffi), 브라우저 자동화(Playwright), 또는 실제 기기 자동화로 전환", "error")
                        session.status = "error"
                        return
                time.sleep(interval)
                continue

            # 예약 가능 열차 필터링
            available = []
            for train in trains:
                if target_numbers and train.train_no not in target_numbers:
                    continue
                if train.has_seat():
                    available.append(train)

            if not available:
                session.log(f"#{session.attempt} 매진 (조회 {len(trains)}건)")
                time.sleep(interval)
                continue

            # 예매 시도
            for train in available:
                if session.stop_flag:
                    return

                train_info = (
                    f"{train.train_type_name} {train.train_no}호 "
                    f"{train.dep_time[:2]}:{train.dep_time[2:4]} "
                    f"{train.dep_name}→{train.arr_name}"
                )
                session.log(f"좌석 발견! {train_info}", "success")

                try:
                    reservation = korail.reserve(
                        train, passengers=passengers, option=seat_option
                    )
                    session.reservation = {
                        "rsv_id": reservation.rsv_id,
                        "train_info": train_info,
                        "buy_limit_date": getattr(reservation, "buy_limit_date", ""),
                        "buy_limit_time": getattr(reservation, "buy_limit_time", ""),
                        "price": getattr(reservation, "price", ""),
                    }
                    session.log(
                        f"예매 성공! 예약번호: {reservation.rsv_id}", "success"
                    )
                    session.status = "success"
                    return

                except SoldOutError:
                    session.log(f"예매 실패 (매진) - {train_info}", "warn")
                    continue
                except Exception as e:
                    session.log(f"예매 오류: {e}", "warn")
                    continue

            session.log("예매 가능 열차 모두 실패, 재시도...")
            time.sleep(interval)

    except Exception as e:
        session.log(f"예상치 못한 오류: {e}", "error")
        session.status = "error"


# ── 라우트 ──────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html", stations=STATIONS)


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.json
    session_id = str(uuid.uuid4())[:8]
    session = MacroSession()
    sessions[session_id] = session

    params = {
        "id": data["korailId"],
        "pw": data["korailPw"],
        "dep": data["dep"],
        "arr": data["arr"],
        "date": data["date"].replace("-", ""),
        "time": data.get("time", "000000").replace(":", "") + "00",
        "train_type": data.get("trainType", "ALL"),
        "seat_option": data.get("seatOption", "GENERAL_FIRST"),
        "adult": int(data.get("adult", 1)),
        "child": int(data.get("child", 0)),
        "senior": int(data.get("senior", 0)),
        "interval": float(data.get("interval", 5.0)),
        "max_attempts": int(data.get("maxAttempts", 0)),
        "train_numbers": data.get("trainNumbers", ""),
    }

    thread = threading.Thread(target=macro_worker, args=(session, params), daemon=True)
    session.thread = thread
    thread.start()

    return jsonify({"sessionId": session_id})


@app.route("/api/status/<session_id>")
def api_status(session_id):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "세션을 찾을 수 없습니다"}), 404

    return jsonify(
        {
            "status": session.status,
            "attempt": session.attempt,
            "reservation": session.reservation,
            "logs": session.logs[-50:],  # 최근 50개
        }
    )


@app.route("/api/stop/<session_id>", methods=["POST"])
def api_stop(session_id):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "세션을 찾을 수 없습니다"}), 404
    session.stop()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

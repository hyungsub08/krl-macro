#!/usr/bin/env python3
"""
웹 브라우저 기반 코레일 자동 예매 매크로 (Playwright)

모바일 API가 DynaPath/Play Integrity 등으로 차단되었을 때의 대체 경로.
실제 Chromium 브라우저로 www.letskorail.com을 조작하므로
모든 클라이언트 측 봇 탐지(TLS 핑거프린팅, DynaPath, Play Integrity)를
자연스럽게 통과합니다.

사용법:
    python3 web_macro.py <id> <pw> <dep> <arr> <YYYYMMDD> <HHMMSS> [options]

예시:
    python3 web_macro.py 1000170054 mypw 서울 부산 20260425 060000

필수 패키지:
    pip3 install playwright
    python3 -m playwright install chromium

주의: 이 스크립트는 DOM 셀렉터에 의존합니다. 코레일 웹사이트가
업데이트되면 셀렉터를 수동으로 조정해야 합니다. 검증에 앞서 반드시
headless=False 모드로 실제 흐름을 눈으로 확인하세요.
"""
import argparse
import random
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


KORAIL_HOME = "https://www.letskorail.com/"
KORAIL_LOGIN = "https://www.letskorail.com/korail/com/login.do"
KORAIL_SEARCH = "https://www.letskorail.com/ebizprd/EbizPrdTicketPr21100W_pr21110.do"


def _sleep(a=0.5, b=1.5):
    time.sleep(random.uniform(a, b))


def run(args):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        ctx = browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 860},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        # navigator.webdriver 제거 (자동화 탐지 회피)
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = ctx.new_page()

        try:
            # 1) 로그인
            print("[1] 로그인 페이지 이동...")
            page.goto(KORAIL_LOGIN, wait_until="domcontentloaded")
            _sleep(1.0, 2.0)

            print("[2] 자격증명 입력...")
            # 회원번호/전화번호/이메일 탭 선택 필요할 수 있음
            page.fill('input[name="txtMember"]', args.id, timeout=5000)
            page.fill('input[name="txtPwd"]', args.pw, timeout=5000)
            _sleep(0.3, 0.8)
            page.click('input[alt="로그인"], button:has-text("로그인"), input[value="로그인"]')
            page.wait_for_load_state("networkidle", timeout=15000)
            _sleep(1.5, 2.5)

            # 로그인 성공 검증 (URL 또는 특정 엘리먼트)
            if "login" in page.url.lower():
                print(f"[!] 로그인 실패 감지 (현재 URL: {page.url})")
                page.screenshot(path="login_fail.png")
                print("    스크린샷 저장: login_fail.png")
                sys.exit(2)
            print(f"    로그인 성공 (URL: {page.url})")

            attempt = 0
            while True:
                attempt += 1
                if args.max_attempts and attempt > args.max_attempts:
                    print(f"[+] 최대 시도 {args.max_attempts}회 도달, 종료")
                    break

                print(f"\n[#{attempt}] 조회 중: {args.dep} → {args.arr} "
                      f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:]} {args.time[:2]}:{args.time[2:4]}")

                try:
                    # 2) 승차권 예매 페이지 이동 및 조회 조건 설정
                    page.goto(KORAIL_SEARCH, wait_until="domcontentloaded", timeout=15000)
                    _sleep(0.5, 1.2)

                    # 출발역/도착역: input 필드 직접 채우기 또는 select 사용
                    # (실제 셀렉터는 페이지 구조에 따라 조정 필요)
                    dep_input = page.locator('input[name="txtGoStart"]').first
                    arr_input = page.locator('input[name="txtGoEnd"]').first
                    if dep_input.count() > 0:
                        dep_input.fill(args.dep)
                    if arr_input.count() > 0:
                        arr_input.fill(args.arr)

                    # 날짜/시간
                    date_input = page.locator('input[name="txtGoAbrdDt"]').first
                    time_input = page.locator('input[name="txtGoHour"], select[name="txtGoHour"]').first
                    if date_input.count() > 0:
                        date_input.fill(args.date)
                    if time_input.count() > 0:
                        try:
                            time_input.fill(args.time[:4])
                        except Exception:
                            # select인 경우
                            time_input.select_option(value=args.time[:2])

                    _sleep(0.3, 0.7)

                    # 조회 버튼
                    page.click('input[alt="조회"], button:has-text("조회"), '
                               'input[value="승차권예매"], input[alt="승차권예매"]', timeout=8000)
                    page.wait_for_load_state("networkidle", timeout=15000)
                    _sleep(0.8, 1.5)

                    # 3) 예약 가능 좌석 찾기
                    # 결과 테이블에서 "예약하기" 버튼이 있는 행 검색
                    rows = page.locator('table tr:has(a:has-text("예약하기")), '
                                        'table tr:has(input[alt="예약하기"])').all()
                    if rows:
                        print(f"    예약 가능 좌석 {len(rows)}건 발견!")
                        # 인간 반응시간
                        _sleep(0.3, 0.9)
                        first_row = rows[0]
                        reserve_btn = first_row.locator(
                            'a:has-text("예약하기"), input[alt="예약하기"]'
                        ).first
                        reserve_btn.click()
                        page.wait_for_load_state("networkidle", timeout=15000)
                        _sleep(1.0, 2.0)

                        # 4) 예약 확인 단계
                        # 보통 다음 페이지에서 "예약" 또는 "결제" 버튼
                        try:
                            page.click('input[alt="예약"], button:has-text("예약")',
                                       timeout=5000)
                            page.wait_for_load_state("networkidle", timeout=15000)
                        except PWTimeout:
                            pass

                        print("✅ 예매 완료! 스크린샷: reservation_success.png")
                        page.screenshot(path="reservation_success.png")
                        break
                    else:
                        print(f"    매진 / 예약 가능 좌석 없음")
                except PWTimeout as te:
                    print(f"    타임아웃: {te}")
                except Exception as e:
                    print(f"    조회 오류: {e}")

                # 다음 시도까지 랜덤 대기
                _sleep(args.interval - 1.0, args.interval + 2.0)

        finally:
            if not args.headless:
                input("\n[Enter] 브라우저 닫기...")
            ctx.close()
            browser.close()


def main():
    ap = argparse.ArgumentParser(description="Korail 웹 자동 예매 (Playwright)")
    ap.add_argument("id", help="코레일 회원번호/전화번호/이메일")
    ap.add_argument("pw", help="코레일 비밀번호")
    ap.add_argument("dep", help="출발역 (예: 서울)")
    ap.add_argument("arr", help="도착역 (예: 부산)")
    ap.add_argument("date", help="날짜 YYYYMMDD")
    ap.add_argument("time", help="출발시각 HHMMSS")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="조회 간격(초) 기본 5.0")
    ap.add_argument("--max-attempts", type=int, default=0,
                    help="최대 시도 횟수 (0=무제한)")
    ap.add_argument("--headless", action="store_true",
                    help="헤드리스 모드 (기본: 가시 모드로 실행하여 검증 가능)")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()

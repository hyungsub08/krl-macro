#!/usr/bin/env python3
"""
MACRO ERROR 진단 스크립트

로그인은 성공하는데 ScheduleView(조회)만 실패하는 원인을 파악하기 위해
서버의 전체 원본 응답(headers + body)을 덤프합니다.

사용법:
    python3 diagnose_macro_error.py <korail_id> <korail_pw>

예시:
    python3 diagnose_macro_error.py 1000170054 mypassword
"""
import sys
import json
from korail2 import Korail

if len(sys.argv) < 3:
    print("Usage: python3 diagnose_macro_error.py <korail_id> <korail_pw>")
    sys.exit(1)

korail_id = sys.argv[1]
korail_pw = sys.argv[2]

print("=" * 70)
print("KORAIL MACRO ERROR DIAGNOSIS")
print("=" * 70)

# 1) 로그인
print("\n[1] 로그인 시도...")
k = Korail(korail_id, korail_pw, auto_login=False)
ok = k.login(korail_id, korail_pw)
print(f"    로그인 결과: {'SUCCESS' if ok else 'FAIL'}")
print(f"    세션 Key: {k._key[:30] if k._key else '(없음)'}...")
print(f"    앱 Version: {k._version}")
print(f"    Device: {k._device}")

if not ok:
    sys.exit(1)

# 2) 검색 요청 원본 응답 덤프
print("\n[2] ScheduleView 요청 원본 응답 캡처...")
from korail2.korail2 import (
    KORAIL_SEARCH_SCHEDULE,
    AdultPassenger,
    Passenger,
    TrainType,
)
from functools import reduce
from datetime import datetime, timedelta

passengers = Passenger.reduce([AdultPassenger()])
adult_count = 1
child_count = toddler_count = senior_count = 0

kst_now = datetime.utcnow() + timedelta(hours=9)
date = kst_now.strftime("%Y%m%d")
time = kst_now.strftime("%H%M%S")

url = KORAIL_SEARCH_SCHEDULE
headers, sid = k._get_auth_headers_and_sid(url)
data = {
    'Device': k._device,
    'Key': k._key,
    'radJobId': '1',
    'selGoTrain': TrainType.KTX,
    'txtCardPsgCnt': '0',
    'txtGdNo': '',
    'txtGoAbrdDt': date,
    'txtGoEnd': '0020',
    'txtGoHour': time,
    'txtGoStart': '0001',
    'txtJobDv': '',
    'txtMenuId': '11',
    'txtPsgFlg_1': adult_count,
    'txtPsgFlg_2': child_count,
    'txtPsgFlg_8': toddler_count,
    'txtPsgFlg_3': senior_count,
    'txtPsgFlg_4': '0',
    'txtPsgFlg_5': '0',
    'txtSeatAttCd_2': '000',
    'txtSeatAttCd_3': '000',
    'txtSeatAttCd_4': '015',
    'txtTrnGpCd': TrainType.KTX,
    'Version': k._version,
}
if sid:
    data['Sid'] = sid

print(f"    URL: {url}")
print(f"    전송 헤더 keys: {list(headers.keys())}")
print(f"    전송 데이터 keys: {list(data.keys())}")

r = k._session.post(url, data=data, headers=headers)

print("\n" + "=" * 70)
print("RAW SERVER RESPONSE")
print("=" * 70)
print(f"HTTP Status: {r.status_code}")
print(f"Response Headers:")
for key, val in r.headers.items():
    print(f"    {key}: {val}")

print(f"\nResponse Body (원본):")
print(r.text)

print(f"\nResponse Body (파싱된 JSON):")
try:
    j = r.json()
    print(json.dumps(j, ensure_ascii=False, indent=2))
except Exception as e:
    print(f"    JSON 파싱 실패: {e}")

print("\n" + "=" * 70)
print("분석 참고 필드")
print("=" * 70)
try:
    j = r.json()
    print(f"strResult    : {j.get('strResult')}")
    print(f"h_msg_cd     : {j.get('h_msg_cd')}")
    print(f"h_msg_txt    : {j.get('h_msg_txt')}")
    for key in j:
        if key not in ('strResult', 'h_msg_cd', 'h_msg_txt'):
            print(f"{key:12s} : {j[key]}")
except Exception:
    pass

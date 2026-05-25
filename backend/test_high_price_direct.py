import requests
import json
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

def test_ka10086(code):
    # 환경변수에서 토큰 가져오기
    token = os.getenv("KIWOOM_ACCESS_TOKEN")
    if not token:
        print("KIWOOM_ACCESS_TOKEN 환경변수가 설정되지 않았습니다.")
        return
    
    url = "https://api.kiwoom.com/api/dostk/mrkcond"
    
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10086",
        "cont-yn": "N",
        "next-key": ""
    }
    
    body = {
        "stk_cd": code,
        "qry_dt": "20260525",  # 최근 영업일
        "indc_tp": "1"  # 1: 금액(백만원)
    }
    
    response = requests.post(url, headers=headers, json=body)
    print(f"=== {code} ===")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        items = data.get("daly_stkpc", [])
        print(f"최근 5일 데이터:")
        for item in items[:5]:
            high_pric = item.get('high_pric')
            amt_mn = item.get('amt_mn')
            print(f"  date: {item.get('date')}, high_pric: {high_pric}, amt_mn: {amt_mn}")
        
        # 변환 후 값 확인
        highs_original = [item.get('high_pric') for item in items[:5]]
        highs_converted = [float(h) * 1000000 if h else 0 for h in highs_original]
        print(f"high_pric 원본: {highs_original}")
        print(f"high_pric 변환 후(원): {highs_converted}")
        print(f"max(high_pric 변환 후): {max(highs_converted) if highs_converted else 0}")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    test_ka10086("005930")  # 삼성전자
    print()
    test_ka10086("000660")  # SK하이닉스

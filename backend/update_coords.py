"""
카카오 주소 검색 API로 hospital_shuttle.json의 좌표를 자동 업데이트하는 스크립트.
실행: python backend/update_coords.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# 프로젝트 루트 기준 .env 로드
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import httpx

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
DATA_PATH = Path(__file__).parent / "app/data/hospital_shuttle.json"


async def geocode(client: httpx.AsyncClient, address: str, name: str) -> dict | None:
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}

    # 1차: 주소 검색
    r = await client.get(
        "https://dapi.kakao.com/v2/local/search/address.json",
        headers=headers,
        params={"query": address, "size": 1},
    )
    data = r.json()
    if data.get("documents"):
        doc = data["documents"][0]
        return {"lat": float(doc["y"]), "lng": float(doc["x"])}

    # 2차: 키워드 검색 (주소 검색 실패 시)
    r2 = await client.get(
        "https://dapi.kakao.com/v2/local/search/keyword.json",
        headers=headers,
        params={"query": name, "size": 1},
    )
    data2 = r2.json()
    if data2.get("documents"):
        doc = data2["documents"][0]
        return {"lat": float(doc["y"]), "lng": float(doc["x"])}

    return None


async def main():
    if not KAKAO_REST_API_KEY:
        print("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        sys.exit(1)

    with open(DATA_PATH, encoding="utf-8") as f:
        db = json.load(f)

    updated = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for hospital in db["hospitals"]:
            # 병원 본체 좌표
            coords = await geocode(client, hospital["address"], hospital["name"])
            if coords:
                old = (hospital["lat"], hospital["lng"])
                hospital["lat"] = coords["lat"]
                hospital["lng"] = coords["lng"]
                print(f"[병원] {hospital['name']}")
                print(f"  이전: {old} → 이후: ({coords['lat']}, {coords['lng']})")
                updated += 1
            else:
                print(f"[병원] {hospital['name']} - 좌표 찾기 실패, 주소: {hospital['address']}")

            # 정류장 좌표
            seen_stops = set()
            for route in hospital["shuttle_routes"]:
                for stop in route["stops"]:
                    if stop["stop_id"] in seen_stops:
                        continue
                    seen_stops.add(stop["stop_id"])

                    coords = await geocode(client, stop["address"], stop["name"])
                    if coords:
                        old = (stop["lat"], stop["lng"])
                        stop["lat"] = coords["lat"]
                        stop["lng"] = coords["lng"]
                        print(f"  [정류장] {stop['name']}")
                        print(f"    이전: {old} → 이후: ({coords['lat']}, {coords['lng']})")
                        updated += 1
                    else:
                        print(f"  [정류장] {stop['name']} - 좌표 찾기 실패, 주소: {stop['address']}")

    # 같은 stop_id를 공유하는 stops도 일괄 업데이트
    # (위에서 수정한 첫 번째 stop만 반영되므로, 같은 ID의 나머지도 동기화)
    coords_by_stop_id = {}
    for hospital in db["hospitals"]:
        for route in hospital["shuttle_routes"]:
            for stop in route["stops"]:
                if stop["stop_id"] not in coords_by_stop_id:
                    coords_by_stop_id[stop["stop_id"]] = (stop["lat"], stop["lng"])
                else:
                    stop["lat"], stop["lng"] = coords_by_stop_id[stop["stop_id"]]

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {updated}개 좌표 업데이트 → {DATA_PATH}")


if __name__ == "__main__":
    asyncio.run(main())

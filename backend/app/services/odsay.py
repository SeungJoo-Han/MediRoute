"""
ODsay 대중교통 API 연동
- 출발지/목적지 좌표 기반 실제 대중교통 경로 탐색
- 비상업 목적 무료 (https://lab.odsay.com)
"""
import httpx
from typing import Optional, List
from ..config import ODSAY_API_KEY

ODSAY_BASE = "https://api.odsay.com/v1/api"

# trafficType 코드
TYPE_SUBWAY = 1
TYPE_BUS = 2
TYPE_WALK = 3


async def search_transit_routes(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
) -> Optional[List[dict]]:
    """
    ODsay API로 실제 대중교통 경로 탐색.
    반환: 경로 목록 (최대 3개) or None (키 없음 / 오류)
    """
    if not ODSAY_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ODSAY_BASE}/searchPubTransPathT",
                params={
                    "SX": origin_lng,
                    "SY": origin_lat,
                    "EX": dest_lng,
                    "EY": dest_lat,
                    "apiKey": ODSAY_API_KEY,
                },
                headers={
                    "Referer": "http://localhost:8000",
                    "Origin": "http://localhost:8000",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"[ODsay] API 오류: {e}")
        return None

    if "error" in data:
        print(f"[ODsay] API 에러 응답: {data['error']}")
        return None
    if not data.get("result") or not data["result"].get("path"):
        print(f"[ODsay] 경로 없음: {data}")
        return None

    routes = []
    for path in data["result"]["path"][:3]:
        info = path.get("info", {})
        segments = _parse_subpaths(path.get("subPath", []))

        if not segments:
            continue

        routes.append({
            "type": "transit",
            "total_minutes": info.get("totalTime", 0),
            "fare": info.get("payment", 0),
            "transfers": info.get("busTransitCount", 0) + info.get("subwayTransitCount", 0),
            "segments": segments,
        })

    return routes if routes else None


def _parse_subpaths(subpaths: list) -> list:
    segments = []
    for sub in subpaths:
        traffic_type = sub.get("trafficType")
        duration = sub.get("sectionTime", 0)

        if traffic_type == TYPE_WALK:
            distance = sub.get("distance", 0)
            if duration == 0 and distance == 0:
                continue  # 무의미한 도보 구간 스킵
            segments.append({
                "type": "walk",
                "duration_minutes": duration,
                "distance_m": distance,
            })

        elif traffic_type == TYPE_SUBWAY:
            lanes = sub.get("lane", [])
            line_name = lanes[0].get("name", "지하철") if lanes else "지하철"
            segments.append({
                "type": "subway",
                "line_name": line_name,
                "from_name": sub.get("startName", ""),
                "to_name": sub.get("endName", ""),
                "duration_minutes": duration,
                "station_count": sub.get("stationCount", 0),
                "from_lat": sub.get("startY"),
                "from_lng": sub.get("startX"),
                "to_lat": sub.get("endY"),
                "to_lng": sub.get("endX"),
            })

        elif traffic_type == TYPE_BUS:
            lanes = sub.get("lane", [])
            bus_no = lanes[0].get("busNo", "버스") if lanes else "버스"
            bus_type = lanes[0].get("type", 1) if lanes else 1
            segments.append({
                "type": "bus",
                "bus_no": str(bus_no),
                "bus_type": bus_type,  # 1=일반, 2=좌석, 3=마을, 5=광역, 6=공항 등
                "from_name": sub.get("startName", ""),
                "to_name": sub.get("endName", ""),
                "duration_minutes": duration,
                "station_count": sub.get("stationCount", 0),
                "from_lat": sub.get("startY"),
                "from_lng": sub.get("startX"),
                "to_lat": sub.get("endY"),
                "to_lng": sub.get("endX"),
            })

    return segments

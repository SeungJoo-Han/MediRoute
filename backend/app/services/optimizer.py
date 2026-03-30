"""
경로 최적화 서비스
- 셔틀 경로 + 일반 대중교통 비교
- 정류장이 멀 경우 대중교통으로 정류장까지 이동 후 셔틀 탑승 경로도 계산
- 가장 빠른 경로 추천
"""
import json
import math
import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from ..config import MAX_WALK_DISTANCE_METERS, WALK_SPEED_M_PER_MIN

# 셔틀 데이터 로드
_DATA_PATH = os.path.join(os.path.dirname(__file__), "../data/hospital_shuttle.json")
with open(_DATA_PATH, encoding="utf-8") as f:
    SHUTTLE_DB: dict = json.load(f)

# 대중교통 실효 속도: 직선거리 × 1.4(우회계수) ÷ 10km/h(대기·환승 포함 평균)
# 실측 기준: 서울 시내 평균 대중교통 실효속도 약 10km/h
TRANSIT_DETOUR_FACTOR = 1.4
TRANSIT_SPEED_M_PER_MIN = 10000 / 60
TRANSIT_MIN_MINUTES = 15.0

# 환승·탑승 준비 여유 시간 (정류장 도착 후 실제 탑승까지 필요한 시간)
TRANSFER_BUFFER_MINUTES = 2


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 직선 거리 (미터)"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _walk_minutes(distance_m: float) -> float:
    """거리(m) → 도보 시간(분)"""
    return distance_m / WALK_SPEED_M_PER_MIN


def _transit_minutes(distance_m: float) -> float:
    """직선거리(m) → 대중교통 소요시간 추정(분). 우회계수 1.4 적용."""
    return max(TRANSIT_MIN_MINUTES, distance_m * TRANSIT_DETOUR_FACTOR / TRANSIT_SPEED_M_PER_MIN)


def _get_day_type(dt: datetime) -> str:
    """요일 타입 반환: weekday / saturday / sunday"""
    wd = dt.weekday()
    if wd == 5:
        return "saturday"
    if wd == 6:
        return "sunday"
    return "weekday"


def _next_departure(schedule_times: List[str], after_time: datetime) -> Optional[Dict]:
    """
    after_time 이후 가장 빠른 출발 시간 반환.
    반환: {"departure_str": "HH:MM", "wait_minutes": float} or None
    """
    if not schedule_times:
        return None

    for time_str in schedule_times:
        hh, mm = map(int, time_str.split(":"))
        dep_dt = after_time.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dep_dt >= after_time:
            wait = (dep_dt - after_time).total_seconds() / 60
            return {"departure_str": time_str, "wait_minutes": round(wait, 1)}

    return None


def find_hospital(hospital_id: str) -> Optional[dict]:
    for h in SHUTTLE_DB["hospitals"]:
        if h["id"] == hospital_id:
            return h
    return None


def get_all_hospitals() -> List[dict]:
    return [
        {
            "id": h["id"],
            "name": h["name"],
            "address": h["address"],
            "lat": h["lat"],
            "lng": h["lng"],
            "shuttle_info_url": h.get("shuttle_info_url", ""),
        }
        for h in SHUTTLE_DB["hospitals"]
    ]


def calculate_routes(
    origin_lat: float,
    origin_lng: float,
    hospital_id: str,
    departure_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    출발지 좌표 + 병원 ID + 출발시간 기준으로 가능한 모든 경로를 계산.

    정류장이 도보 거리(1500m) 이내면 도보로, 초과 시 대중교통으로 정류장까지
    이동하는 경로를 포함하여 일반 대중교통과 비교 후 최적 경로를 추천.
    """
    if departure_time is None:
        departure_time = datetime.now()

    hospital = find_hospital(hospital_id)
    if not hospital:
        return {"error": f"병원 ID '{hospital_id}'를 찾을 수 없습니다."}

    day_type = _get_day_type(departure_time)

    # 출발지 → 병원 직선거리 기반 대중교통 추정
    dist_origin_to_hospital = _haversine_meters(
        origin_lat, origin_lng, hospital["lat"], hospital["lng"]
    )
    direct_transit_min = _transit_minutes(dist_origin_to_hospital)

    valid_routes = []
    unavailable_routes = []

    # --- 셔틀 경로 탐색 ---
    for route in hospital["shuttle_routes"]:
        if route["direction"] != "to_hospital":
            continue

        schedules = route["schedules"]
        today_times = schedules.get(day_type)

        if not today_times:
            unavailable_routes.append({
                "type": "shuttle_unavailable",
                "route_id": route["route_id"],
                "route_name": route["route_name"],
                "reason": f"{'주말' if day_type != 'weekday' else '평일'} 운행 없음",
            })
            continue

        boarding_stop = route["stops"][0]
        alighting_stop = route["stops"][-1]

        dist_to_stop = _haversine_meters(
            origin_lat, origin_lng,
            boarding_stop["lat"], boarding_stop["lng"]
        )

        # 정류장까지 이동 방법 결정
        if dist_to_stop <= MAX_WALK_DISTANCE_METERS:
            to_stop_min = _walk_minutes(dist_to_stop)
            to_stop_mode = "walk"
        else:
            to_stop_min = _transit_minutes(dist_to_stop)
            to_stop_mode = "transit"

        arrival_at_stop = departure_time + timedelta(minutes=to_stop_min)

        if to_stop_mode == "walk":
            # 도보 시간은 정확하므로 실제 도착 시각 기준으로 다음 셔틀 탐색
            next_dep_ref = arrival_at_stop + timedelta(minutes=TRANSFER_BUFFER_MINUTES)
        else:
            # 대중교통 추정 시간은 부정확(너무 느림) → 출발 시각 기준으로 탐색
            # ODsay가 실제 시간을 받으면 navigation.py에서 재계산
            next_dep_ref = departure_time

        next_dep = _next_departure(today_times, next_dep_ref)

        if not next_dep:
            unavailable_routes.append({
                "type": "shuttle_last_departed",
                "route_id": route["route_id"],
                "route_name": route["route_name"],
                "boarding_stop": boarding_stop["name"],
                "reason": f"오늘 운행이 모두 종료되었습니다 (막차 {today_times[-1]})",
            })
            continue

        shuttle_travel_min = route["travel_time_minutes"]
        walk_from_stop_min = _walk_minutes(
            _haversine_meters(
                alighting_stop["lat"], alighting_stop["lng"],
                hospital["lat"], hospital["lng"]
            )
        )

        total_min = to_stop_min + TRANSFER_BUFFER_MINUTES + next_dep["wait_minutes"] + shuttle_travel_min + walk_from_stop_min
        arrival_dt = departure_time + timedelta(minutes=total_min)

        # 첫 번째 세그먼트: 정류장까지 이동
        if to_stop_mode == "walk":
            first_segment = {
                "type": "walk",
                "label": "도보",
                "from_name": "출발지",
                "to_name": boarding_stop["name"],
                "from_lat": origin_lat,
                "from_lng": origin_lng,
                "to_lat": boarding_stop["lat"],
                "to_lng": boarding_stop["lng"],
                "duration_minutes": round(to_stop_min, 1),
                "distance_m": round(dist_to_stop),
            }
        else:
            first_segment = {
                "type": "transit_to_stop",
                "label": "대중교통",
                "from_name": "출발지",
                "to_name": boarding_stop["name"],
                "from_lat": origin_lat,
                "from_lng": origin_lng,
                "to_lat": boarding_stop["lat"],
                "to_lng": boarding_stop["lng"],
                "duration_minutes": round(to_stop_min, 1),
                "distance_m": round(dist_to_stop),
                "note": "추정값 · 실제 소요시간은 네이버지도·카카오맵 확인",
            }

        valid_routes.append({
            "type": "shuttle",
            "to_stop_mode": to_stop_mode,
            "route_id": route["route_id"],
            "route_name": route["route_name"],
            "total_minutes": round(total_min, 1),
            "arrival_time": arrival_dt.strftime("%H:%M"),
            "fare": route["fare"],
            "notes": route.get("notes", ""),
            "segments": [
                first_segment,
                {
                    "type": "wait",
                    "label": "셔틀 대기",
                    "location": boarding_stop["name"],
                    "duration_minutes": round(next_dep["wait_minutes"] + TRANSFER_BUFFER_MINUTES, 1),
                    "departure_time": next_dep["departure_str"],
                },
                {
                    "type": "shuttle",
                    "label": "셔틀버스",
                    "from_name": boarding_stop["name"],
                    "to_name": alighting_stop["name"],
                    "from_lat": boarding_stop["lat"],
                    "from_lng": boarding_stop["lng"],
                    "to_lat": alighting_stop["lat"],
                    "to_lng": alighting_stop["lng"],
                    "duration_minutes": shuttle_travel_min,
                    "departure_time": next_dep["departure_str"],
                    "route_name": route["route_name"],
                    "waypoints": [
                        {"name": wp["name"], "lat": wp["lat"], "lng": wp["lng"]}
                        for wp in route.get("waypoints", [])
                    ],
                },
            ],
        })

    # 시간순 정렬
    valid_routes.sort(key=lambda r: r["total_minutes"])

    # 대중교통 직접 이동 vs 셔틀 경로 비교 → 추천 결정
    best_shuttle_min = valid_routes[0]["total_minutes"] if valid_routes else None

    if best_shuttle_min is not None and round(best_shuttle_min) <= round(direct_transit_min):
        recommendation = "shuttle"
    else:
        recommendation = "transit"

    transit_route = {
        "type": "transit_estimate",
        "label": "대중교통 (추정)",
        "total_minutes": round(direct_transit_min, 1),
        "notes": "실제 소요 시간은 네이버지도·카카오맵에서 확인하세요",
        "distance_m": round(dist_origin_to_hospital),
    }

    return {
        "hospital": {
            "id": hospital["id"],
            "name": hospital["name"],
            "address": hospital["address"],
            "lat": hospital["lat"],
            "lng": hospital["lng"],
        },
        "origin": {"lat": origin_lat, "lng": origin_lng},
        "departure_time": departure_time.strftime("%H:%M"),
        "day_type": day_type,
        "routes": valid_routes,
        "unavailable_routes": unavailable_routes,
        "transit_estimate": transit_route,
        "recommendation": recommendation,  # "shuttle" | "transit"
    }

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import asyncio

from ..services.kakao import geocode_address, search_keyword, get_car_duration_minutes
from ..services.optimizer import calculate_routes, _next_departure, TRANSFER_BUFFER_MINUTES, find_hospital, _get_day_type
from ..services.odsay import search_transit_routes
from ..config import KAKAO_JS_KEY, ODSAY_API_KEY

router = APIRouter(tags=["navigation"])


class RouteRequest(BaseModel):
    origin_address: str
    hospital_id: str
    departure_time: Optional[str] = None  # "HH:MM" 형식, 없으면 현재 시간
    departure_date: Optional[str] = None  # "YYYY-MM-DD" 형식, 없으면 오늘


@router.get("/config")
async def get_config():
    """프론트엔드 설정값 (카카오 JS 키 등) 반환"""
    return {"kakao_js_key": KAKAO_JS_KEY}


@router.get("/geocode")
async def geocode(address: str = Query(..., description="변환할 주소")):
    """주소를 위경도 좌표로 변환"""
    result = await geocode_address(address)
    if not result:
        raise HTTPException(status_code=404, detail="주소를 찾을 수 없습니다.")
    return result


@router.get("/search")
async def search_places(
    keyword: str = Query(..., description="검색 키워드"),
    lat: Optional[float] = None,
    lng: Optional[float] = None,
):
    """장소 키워드 검색 (자동완성)"""
    results = await search_keyword(keyword, x=lng, y=lat)
    return {"results": results}


@router.post("/route")
async def find_route(req: RouteRequest):
    """
    출발지 주소 + 병원 ID + 출발 시간 기준으로 최적 경로 계산.
    셔틀버스 포함 경로와 일반 대중교통 경로를 함께 반환.
    """
    # 1. 출발지 주소 → 좌표
    origin = await geocode_address(req.origin_address)
    if not origin:
        raise HTTPException(status_code=400, detail=f"출발지 주소를 찾을 수 없습니다: {req.origin_address}")

    # 2. 출발 날짜·시간 파싱
    departure_dt = None
    if req.departure_time:
        try:
            if req.departure_date:
                dep_date = datetime.strptime(req.departure_date, "%Y-%m-%d").date()
            else:
                dep_date = datetime.now().date()
            hh, mm = map(int, req.departure_time.split(":"))
            departure_dt = datetime(dep_date.year, dep_date.month, dep_date.day, hh, mm)
        except ValueError:
            raise HTTPException(status_code=400, detail="날짜/시간 형식이 올바르지 않습니다.")

    # 3. 셔틀 경로 계산
    result = calculate_routes(
        origin_lat=origin["lat"],
        origin_lng=origin["lng"],
        hospital_id=req.hospital_id,
        departure_time=departure_dt,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    result["origin"]["address"] = origin["address"]

    dep_dt = departure_dt or datetime.now()

    # 4. 셔틀 구간 소요시간을 카카오 자동차 경로로 동적 계산
    shuttle_car_tasks = []
    shuttle_seg_refs = []  # (route_idx, segment_idx)
    for r_idx, route in enumerate(result["routes"]):
        for s_idx, seg in enumerate(route["segments"]):
            if seg["type"] == "shuttle":
                shuttle_car_tasks.append(
                    get_car_duration_minutes(
                        seg["from_lat"], seg["from_lng"],
                        seg["to_lat"], seg["to_lng"],
                    )
                )
                shuttle_seg_refs.append((r_idx, s_idx))

    if shuttle_car_tasks:
        car_results = await asyncio.gather(*shuttle_car_tasks, return_exceptions=True)
        for (r_idx, s_idx), car_min in zip(shuttle_seg_refs, car_results):
            if isinstance(car_min, Exception) or car_min is None:
                continue
            seg = result["routes"][r_idx]["segments"][s_idx]
            old_min = seg["duration_minutes"]
            seg["duration_minutes"] = car_min
            result["routes"][r_idx]["total_minutes"] += (car_min - old_min)
            arrival = dep_dt + timedelta(minutes=result["routes"][r_idx]["total_minutes"])
            result["routes"][r_idx]["arrival_time"] = arrival.strftime("%H:%M")

    if not ODSAY_API_KEY:
        return result
    hospital = result["hospital"]

    # 4. ODsay 병렬 호출: 병원행 직통 + 각 셔틀 정류장행
    # 셔틀 경로 중 transit_to_stop 구간만 추출 (정류장 좌표 수집)
    transit_to_stop_indices = []  # (route_idx, segment_idx, to_lat, to_lng)
    for r_idx, route in enumerate(result["routes"]):
        for s_idx, seg in enumerate(route["segments"]):
            if seg["type"] == "transit_to_stop":
                transit_to_stop_indices.append((r_idx, s_idx, seg["to_lat"], seg["to_lng"]))

    # 동시 최대 5개 제한 (too many requests 방지)
    tasks = [
        search_transit_routes(origin["lat"], origin["lng"], hospital["lat"], hospital["lng"])
    ]
    for _, _, to_lat, to_lng in transit_to_stop_indices:
        tasks.append(search_transit_routes(origin["lat"], origin["lng"], to_lat, to_lng))

    sem = asyncio.Semaphore(4)

    async def limited(coro, delay: float = 0):
        await asyncio.sleep(delay)
        async with sem:
            return await coro

    all_results = await asyncio.gather(
        *[limited(t, delay=i * 0.3) for i, t in enumerate(tasks)],
        return_exceptions=True
    )

    # 5. 병원행 직통 대중교통 결과 처리
    transit_routes_raw = all_results[0] if not isinstance(all_results[0], Exception) else None
    if transit_routes_raw:
        for t in transit_routes_raw:
            arrival = dep_dt + timedelta(minutes=t["total_minutes"])
            t["arrival_time"] = arrival.strftime("%H:%M")
            # 각 세그먼트에 예상 출발 시각 추가
            cur_time = dep_dt
            for seg in t.get("segments", []):
                seg["start_time"] = cur_time.strftime("%H:%M")
                cur_time += timedelta(minutes=seg.get("duration_minutes", 0))
        result["transit_routes"] = transit_routes_raw

    # 6. 셔틀 정류장행 대중교통 결과를 각 세그먼트에 적용
    hospital_data = find_hospital(req.hospital_id)
    day_type = _get_day_type(dep_dt)

    for i, (r_idx, s_idx, _, _) in enumerate(transit_to_stop_indices):
        odsay_result = all_results[i + 1]
        if isinstance(odsay_result, Exception) or not odsay_result:
            continue

        best = odsay_result[0]
        seg = result["routes"][r_idx]["segments"][s_idx]
        old_duration = seg["duration_minutes"]  # 교체 전에 저장

        # 세그먼트별 예상 출발 시각 계산 (transit_to_stop은 항상 첫 세그먼트라 dep_dt에서 시작)
        detail_segments = best["segments"]
        cur_time = dep_dt
        for d_seg in detail_segments:
            d_seg["start_time"] = cur_time.strftime("%H:%M")
            cur_time += timedelta(minutes=d_seg.get("duration_minutes", 0))

        new_transit_min = best["total_minutes"]
        result["routes"][r_idx]["segments"][s_idx] = {
            "type": "transit_to_stop",
            "from_name": seg["from_name"],
            "to_name": seg["to_name"],
            "from_lat": seg["from_lat"],
            "from_lng": seg["from_lng"],
            "to_lat": seg["to_lat"],
            "to_lng": seg["to_lng"],
            "duration_minutes": new_transit_min,
            "transit_fare": best.get("fare", 0),
            "detail": detail_segments,
        }

        # 실제 대중교통 소요시간을 반영해 대기 세그먼트와 셔틀 출발 시각 재계산
        route_segs = result["routes"][r_idx]["segments"]
        recalculated = False
        moved_to_unavailable = False
        if (s_idx + 1 < len(route_segs) and route_segs[s_idx + 1]["type"] == "wait"
                and hospital_data):
            wait_seg = route_segs[s_idx + 1]
            shuttle_seg = route_segs[s_idx + 2] if s_idx + 2 < len(route_segs) else None
            old_wait = wait_seg["duration_minutes"]

            route_id = result["routes"][r_idx]["route_id"]
            shuttle_route = next(
                (r for r in hospital_data["shuttle_routes"] if r["route_id"] == route_id), None
            )
            if shuttle_route:
                today_times = shuttle_route["schedules"].get(day_type) or []
                new_arrival_ready = dep_dt + timedelta(minutes=new_transit_min + TRANSFER_BUFFER_MINUTES)
                new_dep = _next_departure(today_times, new_arrival_ready)
                if new_dep:
                    new_wait = round(new_dep["wait_minutes"] + TRANSFER_BUFFER_MINUTES, 1)
                    delta = (new_transit_min - old_duration) + (new_wait - old_wait)
                    wait_seg["duration_minutes"] = new_wait
                    wait_seg["departure_time"] = new_dep["departure_str"]
                    if shuttle_seg:
                        shuttle_seg["departure_time"] = new_dep["departure_str"]
                    result["routes"][r_idx]["total_minutes"] += delta
                    arrival = dep_dt + timedelta(minutes=result["routes"][r_idx]["total_minutes"])
                    result["routes"][r_idx]["arrival_time"] = arrival.strftime("%H:%M")
                    recalculated = True
                else:
                    # 실제 도착 시각 기준으로 막차가 이미 지남 → unavailable로 이동
                    result["unavailable_routes"].append({
                        "type": "shuttle_last_departed",
                        "route_id": result["routes"][r_idx]["route_id"],
                        "route_name": result["routes"][r_idx]["route_name"],
                        "boarding_stop": wait_seg.get("location", ""),
                        "reason": f"오늘 운행이 모두 종료되었습니다 (막차 {today_times[-1]})" if today_times else "운행 정보 없음",
                    })
                    moved_to_unavailable = True

        if moved_to_unavailable:
            result["routes"][r_idx] = None  # 나중에 일괄 제거
        elif not recalculated:
            result["routes"][r_idx]["total_minutes"] += (new_transit_min - old_duration)
            arrival = dep_dt + timedelta(minutes=result["routes"][r_idx]["total_minutes"])
            result["routes"][r_idx]["arrival_time"] = arrival.strftime("%H:%M")

    # unavailable로 이동된 경로 제거
    result["routes"] = [r for r in result["routes"] if r is not None]

    # 7. transit_fare 루트 레벨로 집계 (transit_to_stop 세그먼트의 대중교통 요금)
    for route in result["routes"]:
        for seg in route.get("segments", []):
            if seg["type"] == "transit_to_stop" and seg.get("transit_fare"):
                route["transit_fare"] = seg["transit_fare"]
                break

    # 8. 모든 시간 업데이트 완료 후 재정렬 + 추천 결정
    if result["routes"]:
        result["routes"].sort(key=lambda r: r["total_minutes"])

    if transit_routes_raw:
        best_shuttle = min(r["total_minutes"] for r in result["routes"]) if result["routes"] else None
        best_transit = min(t["total_minutes"] for t in transit_routes_raw)
        result["recommendation"] = "shuttle" if (best_shuttle is not None and round(best_shuttle) <= round(best_transit)) else "transit"

    return result

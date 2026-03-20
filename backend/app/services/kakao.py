"""
카카오 REST API 연동 서비스
- 주소 → 좌표 변환 (geocoding)
- 키워드 장소 검색
- 자동차 경로 소요시간 계산 (Kakao Mobility Directions v1)
"""
import httpx
from typing import Optional
from ..config import KAKAO_REST_API_KEY

KAKAO_LOCAL_BASE = "https://dapi.kakao.com/v2/local"
KAKAO_NAVI_BASE = "https://apis-navi.kakaomobility.com/v1"

# 동일 구간 중복 API 호출 방지용 메모리 캐시
_car_duration_cache: dict[tuple, int] = {}


def _headers():
    from ..config import KAKAO_REST_API_KEY as _key
    return {"Authorization": f"KakaoAK {_key}"}


async def get_car_duration_minutes(
    from_lat: float, from_lng: float,
    to_lat: float, to_lng: float,
) -> Optional[float]:
    """
    카카오 Mobility Directions API로 자동차 경로 소요시간(분) 반환.
    실패 시 None 반환 (호출자가 fallback 처리).
    결과는 메모리 캐시에 저장 (서버 재시작 전까지 유지).
    """
    if not KAKAO_REST_API_KEY:
        return None

    cache_key = (round(from_lat, 5), round(from_lng, 5), round(to_lat, 5), round(to_lng, 5))
    if cache_key in _car_duration_cache:
        return _car_duration_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{KAKAO_NAVI_BASE}/directions",
                headers=_headers(),
                params={
                    "origin": f"{from_lng},{from_lat}",
                    "destination": f"{to_lng},{to_lat}",
                    "priority": "RECOMMEND",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        routes = data.get("routes", [])
        if not routes or routes[0].get("result_code") != 0:
            return None

        duration_sec = routes[0]["summary"]["duration"]
        duration_min = round(duration_sec / 60, 1)
        _car_duration_cache[cache_key] = duration_min
        return duration_min

    except Exception as e:
        print(f"[Kakao Navi] 자동차 경로 오류: {e}")
        return None


async def get_car_route(
    from_lat: float, from_lng: float,
    to_lat: float, to_lng: float,
) -> Optional[dict]:
    """
    카카오 Mobility Directions API로 자동차 소요시간 + 실제 도로 좌표 반환.
    반환: {"duration_min": float, "road_coords": [{lat, lng}, ...]} or None
    """
    if not KAKAO_REST_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{KAKAO_NAVI_BASE}/directions",
                headers=_headers(),
                params={
                    "origin": f"{from_lng},{from_lat}",
                    "destination": f"{to_lng},{to_lat}",
                    "priority": "RECOMMEND",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        routes = data.get("routes", [])
        if not routes or routes[0].get("result_code") != 0:
            return None

        route = routes[0]
        duration_min = round(route["summary"]["duration"] / 60, 1)

        # vertexes: [lng1, lat1, lng2, lat2, ...]
        road_coords = []
        for section in route.get("sections", []):
            for road in section.get("roads", []):
                vx = road.get("vertexes", [])
                for i in range(0, len(vx) - 1, 2):
                    road_coords.append({"lat": vx[i + 1], "lng": vx[i]})

        # duration 캐시도 갱신
        cache_key = (round(from_lat, 5), round(from_lng, 5), round(to_lat, 5), round(to_lng, 5))
        _car_duration_cache[cache_key] = duration_min

        return {"duration_min": duration_min, "road_coords": road_coords}

    except Exception as e:
        print(f"[Kakao Navi] 자동차 경로 오류: {e}")
        return None


async def geocode_address(address: str) -> Optional[dict]:
    """
    주소 문자열을 위경도 좌표로 변환.
    반환: {"lat": float, "lng": float, "address": str} or None
    """
    if not KAKAO_REST_API_KEY:
        return None

    async with httpx.AsyncClient() as client:
        # 1차: 주소 검색
        resp = await client.get(
            f"{KAKAO_LOCAL_BASE}/search/address.json",
            headers=_headers(),
            params={"query": address, "size": 1},
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("documents"):
            doc = data["documents"][0]
            return {
                "lat": float(doc["y"]),
                "lng": float(doc["x"]),
                "address": doc.get("address_name", address),
            }

        # 2차: 키워드 검색 (주소 검색 실패 시)
        resp2 = await client.get(
            f"{KAKAO_LOCAL_BASE}/search/keyword.json",
            headers=_headers(),
            params={"query": address, "size": 1},
        )
        resp2.raise_for_status()
        data2 = resp2.json()

        if data2.get("documents"):
            doc = data2["documents"][0]
            return {
                "lat": float(doc["y"]),
                "lng": float(doc["x"]),
                "address": doc.get("road_address_name") or doc.get("address_name", address),
            }

    return None


async def search_keyword(keyword: str, x: float = None, y: float = None, radius: int = 5000) -> list:
    """
    키워드로 장소 검색 (자동완성 용도)
    """
    if not KAKAO_REST_API_KEY:
        return []

    params = {"query": keyword, "size": 5}
    if x and y:
        params.update({"x": x, "y": y, "radius": radius, "sort": "distance"})

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{KAKAO_LOCAL_BASE}/search/keyword.json",
            headers=_headers(),
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    return [
        {
            "name": doc["place_name"],
            "address": doc.get("road_address_name") or doc.get("address_name", ""),
            "lat": float(doc["y"]),
            "lng": float(doc["x"]),
            "category": doc.get("category_group_name", ""),
        }
        for doc in data.get("documents", [])
    ]

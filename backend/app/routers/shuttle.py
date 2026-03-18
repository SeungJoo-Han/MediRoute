from fastapi import APIRouter
from ..services.optimizer import get_all_hospitals, find_hospital, SHUTTLE_DB

router = APIRouter(tags=["shuttle"])


@router.get("/hospitals")
async def list_hospitals():
    """병원 목록 반환"""
    return {"hospitals": get_all_hospitals()}


@router.get("/hospitals/{hospital_id}/shuttles")
async def get_hospital_shuttles(hospital_id: str):
    """특정 병원의 셔틀 노선 정보 반환"""
    hospital = find_hospital(hospital_id)
    if not hospital:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"병원 ID '{hospital_id}'를 찾을 수 없습니다.")

    return {
        "hospital_id": hospital_id,
        "hospital_name": hospital["name"],
        "shuttle_routes": hospital["shuttle_routes"],
        "meta": SHUTTLE_DB.get("_meta", {}),
    }

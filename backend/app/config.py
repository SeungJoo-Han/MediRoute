import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일은 프로젝트 루트(backend의 상위)에 위치
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# 카카오 API 키 (https://developers.kakao.com 에서 발급)
KAKAO_REST_API_KEY: str = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_JS_KEY: str = os.getenv("KAKAO_JS_KEY", "")

# ODsay API 키 (https://lab.odsay.com 에서 발급 - 선택사항)
ODSAY_API_KEY: str = os.getenv("ODSAY_API_KEY", "")

# 도보 최대 거리 (미터) - 이 거리 이내의 셔틀 정류장만 추천
MAX_WALK_DISTANCE_METERS: int = int(os.getenv("MAX_WALK_DISTANCE_METERS", "1500"))

# 평균 도보 속도 (m/min) - 4 km/h 기준
WALK_SPEED_M_PER_MIN: float = 66.7

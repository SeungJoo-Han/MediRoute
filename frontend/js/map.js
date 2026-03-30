/**
 * 카카오 지도 관련 기능
 */

const MapManager = (() => {
  let map = null;
  let markers = [];
  let polylines = [];
  let overlays = [];

  const COLORS = {
    origin:       "#1565C0",
    hospital:     "#C62828",
    shuttle_stop: "#2E7D32",
    walk:         "#9E9E9E",
    subway:       "#1565C0",
    bus:          "#E65100",
    shuttle:      "#2E7D32",
    transit_est:  "#7B1FA2",  // ODsay 없을 때 추정 점선
  };

  function init(containerId) {
    if (map) { map.relayout(); return; }
    const container = document.getElementById(containerId);
    if (!container || !window.kakao) return;

    map = new kakao.maps.Map(container, {
      center: new kakao.maps.LatLng(37.5665, 126.9780),
      level: 7,
    });
  }

  function clear() {
    markers.forEach((m) => m.setMap(null));
    polylines.forEach((p) => p.setMap(null));
    overlays.forEach((o) => o.setMap(null));
    markers = [];
    polylines = [];
    overlays = [];
  }

  function addMarker({ lat, lng, label, color, zIndex = 1 }) {
    if (!map) return;

    const pos = new kakao.maps.LatLng(lat, lng);
    const svg = `<svg width="32" height="40" viewBox="0 0 32 40" xmlns="http://www.w3.org/2000/svg">
      <path d="M16 0C7.163 0 0 7.163 0 16c0 9.941 16 24 16 24S32 25.941 32 16C32 7.163 24.837 0 16 0z" fill="${color}"/>
      <circle cx="16" cy="16" r="8" fill="white" opacity="0.9"/>
    </svg>`;

    const markerImage = new kakao.maps.MarkerImage(
      "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg),
      new kakao.maps.Size(32, 40),
      { offset: new kakao.maps.Point(16, 40) }
    );

    const marker = new kakao.maps.Marker({ position: pos, image: markerImage, zIndex });
    marker.setMap(map);
    markers.push(marker);

    if (label) {
      const overlay = new kakao.maps.CustomOverlay({
        position: pos,
        content: `<div style="
          background:${color};color:white;padding:4px 8px;border-radius:4px;
          font-size:11px;font-weight:700;white-space:nowrap;
          box-shadow:0 1px 4px rgba(0,0,0,0.2);margin-top:-48px;
          font-family:'Noto Sans KR',sans-serif;
        ">${label}</div>`,
        yAnchor: 1.0,
        zIndex: zIndex + 1,
      });
      overlay.setMap(map);
      overlays.push(overlay);
    }
  }

  function drawLine({ points, color, dashed = false, strokeWeight = 4 }) {
    if (!map || points.length < 2) return;
    const path = points.map((p) => new kakao.maps.LatLng(p.lat, p.lng));
    const polyline = new kakao.maps.Polyline({
      path,
      strokeWeight,
      strokeColor: color,
      strokeOpacity: 0.85,
      strokeStyle: dashed ? "dashed" : "solid",
    });
    polyline.setMap(map);
    polylines.push(polyline);
  }

  function fitBounds(points) {
    if (!map || points.length === 0) return;
    const bounds = new kakao.maps.LatLngBounds();
    points.forEach((p) => bounds.extend(new kakao.maps.LatLng(p.lat, p.lng)));
    map.setBounds(bounds, 60);
  }

  /**
   * 지하철/버스 세그먼트 하나를 지도에 그림 (좌표 있는 경우만).
   */
  function drawTransitSeg(seg, allPoints) {
    const isSubway = seg.type === "subway";
    const isBus    = seg.type === "bus";
    if ((!isSubway && !isBus) || !seg.from_lat || !seg.to_lat) return;

    const color = isSubway ? COLORS.subway : COLORS.bus;

    // lane_coords 있으면 실제 선로/도로 곡선, 없으면 직선 fallback
const linePoints = (seg.lane_coords && seg.lane_coords.length >= 2)
      ? seg.lane_coords
      : [{ lat: seg.from_lat, lng: seg.from_lng }, { lat: seg.to_lat, lng: seg.to_lng }];

    drawLine({ points: linePoints, color, strokeWeight: 5 });
    addMarker({ lat: seg.from_lat, lng: seg.from_lng, label: seg.from_name, color, zIndex: 3 });
    addMarker({ lat: seg.to_lat,   lng: seg.to_lng,   label: seg.to_name,   color, zIndex: 3 });
    allPoints.push({ lat: seg.from_lat, lng: seg.from_lng });
    allPoints.push({ lat: seg.to_lat,   lng: seg.to_lng   });
    // walk: 좌표 없음 → 호출부에서 전후 세그먼트 좌표로 추론
  }

  /**
   * 세그먼트 배열에서 walk 구간의 시작/끝 좌표를 전후 세그먼트로 추론하여 점선으로 그림.
   * fallbackFrom/To: 배열 맨 앞/뒤 walk의 fallback 좌표 (출발지/목적지)
   */
  function drawSegmentsWithWalk(segs, allPoints, fallbackFrom, fallbackTo) {
    segs.forEach((seg, idx) => {
      if (seg.type === "walk") {
        // 이전 세그먼트 끝점 or fallbackFrom
        const prev = segs.slice(0, idx).reverse().find((s) => s.to_lat);
        const next = segs.slice(idx + 1).find((s) => s.from_lat);
        const fromPt = prev ? { lat: prev.to_lat, lng: prev.to_lng } : fallbackFrom;
        const toPt   = next ? { lat: next.from_lat, lng: next.from_lng } : fallbackTo;
        if (fromPt && toPt) {
          drawLine({ points: [fromPt, toPt], color: COLORS.walk, dashed: true, strokeWeight: 3 });
          allPoints.push(fromPt, toPt);
        }
      } else {
        drawTransitSeg(seg, allPoints);
      }
    });
  }

  /**
   * 셔틀 경로 렌더링.
   * 세그먼트 타입: walk | transit_to_stop | wait | shuttle
   */
  function renderRoute(routeData, selectedRoute) {
    if (!map) return;
    clear();

    const allPoints = [];

    if (routeData.origin) {
      addMarker({ lat: routeData.origin.lat, lng: routeData.origin.lng, label: "출발", color: COLORS.origin, zIndex: 5 });
      allPoints.push(routeData.origin);
    }
    if (routeData.hospital) {
      addMarker({ lat: routeData.hospital.lat, lng: routeData.hospital.lng, label: routeData.hospital.name, color: COLORS.hospital, zIndex: 5 });
      allPoints.push(routeData.hospital);
    }

    if (!selectedRoute || selectedRoute.type !== "shuttle") {
      fitBounds(allPoints);
      return;
    }

    selectedRoute.segments.forEach((seg) => {
      if (seg.type === "walk") {
        // 도보: 회색 점선
        drawLine({
          points: [{ lat: seg.from_lat, lng: seg.from_lng }, { lat: seg.to_lat, lng: seg.to_lng }],
          color: COLORS.walk,
          dashed: true,
        });
        addMarker({ lat: seg.to_lat, lng: seg.to_lng, label: seg.to_name, color: COLORS.shuttle_stop, zIndex: 3 });
        allPoints.push({ lat: seg.from_lat, lng: seg.from_lng });
        allPoints.push({ lat: seg.to_lat,   lng: seg.to_lng   });

      } else if (seg.type === "transit_to_stop") {
        if (seg.detail && seg.detail.length > 0) {
          // ODsay 상세 데이터: 지하철/버스/도보 각각 제대로 그림 (walk는 전후 좌표 추론)
          drawSegmentsWithWalk(
            seg.detail, allPoints,
            { lat: seg.from_lat, lng: seg.from_lng },
            { lat: seg.to_lat,   lng: seg.to_lng   }
          );
        } else {
          // ODsay 없음: 출발→정류장 추정 점선
          drawLine({
            points: [{ lat: seg.from_lat, lng: seg.from_lng }, { lat: seg.to_lat, lng: seg.to_lng }],
            color: COLORS.transit_est,
            dashed: true,
          });
          allPoints.push({ lat: seg.from_lat, lng: seg.from_lng });
        }
        // 정류장 마커는 항상 표시
        addMarker({ lat: seg.to_lat, lng: seg.to_lng, label: seg.to_name, color: COLORS.shuttle_stop, zIndex: 4 });
        allPoints.push({ lat: seg.to_lat, lng: seg.to_lng });

      } else if (seg.type === "shuttle") {
        // 셔틀버스: 초록 실선 (road_coords 있으면 실제 도로, 없으면 waypoints 직선)
        const waypoints = seg.waypoints || [];
        if (seg.road_coords && seg.road_coords.length >= 2) {
          drawLine({ points: seg.road_coords, color: COLORS.shuttle, strokeWeight: 5 });
        } else {
          const fallbackPath = [
            { lat: seg.from_lat, lng: seg.from_lng },
            ...waypoints.map(wp => ({ lat: wp.lat, lng: wp.lng })),
            { lat: seg.to_lat, lng: seg.to_lng },
          ];
          drawLine({ points: fallbackPath, color: COLORS.shuttle, strokeWeight: 5 });
        }
        waypoints.forEach(wp => {
          addMarker({ lat: wp.lat, lng: wp.lng, label: wp.name, color: COLORS.shuttle_stop, zIndex: 2 });
          allPoints.push({ lat: wp.lat, lng: wp.lng });
        });
        allPoints.push({ lat: seg.from_lat, lng: seg.from_lng });
        allPoints.push({ lat: seg.to_lat,   lng: seg.to_lng   });
      }
      // wait: 지도에 별도 표시 없음
    });

    fitBounds(allPoints);
  }

  /**
   * 대중교통 직통 경로 렌더링 (ODsay transit_routes).
   * 세그먼트 타입: subway | bus | walk
   */
  function renderTransitRoute(routeData, transitRoute) {
    if (!map) return;
clear();

    const allPoints = [];

    if (routeData.origin) {
      addMarker({ lat: routeData.origin.lat, lng: routeData.origin.lng, label: "출발", color: COLORS.origin, zIndex: 5 });
      allPoints.push(routeData.origin);
    }
    if (routeData.hospital) {
      addMarker({ lat: routeData.hospital.lat, lng: routeData.hospital.lng, label: routeData.hospital.name, color: COLORS.hospital, zIndex: 5 });
      allPoints.push(routeData.hospital);
    }

    drawSegmentsWithWalk(
      transitRoute.segments || [], allPoints,
      routeData.origin,
      routeData.hospital
    );

    fitBounds(allPoints);
  }

  function relayout() {
    if (map) map.relayout();
  }

  return { init, clear, renderRoute, renderTransitRoute, relayout };
})();

/**
 * MediRoute 메인 앱 로직
 */

const API_BASE = "";  // 같은 도메인 (FastAPI가 프론트 서빙)

// ===== 상태 =====
let hospitals = [];
let selectedHospitalId = "";
let selectedDate = "";        // "YYYY-MM-DD"
let currentRouteData = null;
let autocompleteTimer = null;

// ===== DOM 요소 =====
const elOriginInput = document.getElementById("origin-input");
const elAutoList = document.getElementById("autocomplete-list");
const elHospitalSearch = document.getElementById("hospital-search");
const elHospitalList = document.getElementById("hospital-list");
const elDateChips = document.getElementById("date-chips");
const elTimeInput = document.getElementById("time-input");
const elSearchBtn = document.getElementById("search-btn");
const elLoading = document.getElementById("loading");
const elResults = document.getElementById("results-container");
const elMapContainer = document.getElementById("map-container");
const elApiWarning = document.getElementById("api-warning");

// ===== 초기화 =====
async function init() {
  setDefaultDateTime();
  await loadConfig();
  await loadHospitals();

  elOriginInput.addEventListener("input", onOriginInput);
  elOriginInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { closeAutocomplete(); search(); }
  });

  elHospitalSearch.addEventListener("focus", () => renderHospitalDropdown(elHospitalSearch.value));
  elHospitalSearch.addEventListener("input", () => renderHospitalDropdown(elHospitalSearch.value));

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".input-wrap")) {
      closeAutocomplete();
      closeHospitalDropdown();
    }
  });

  elSearchBtn.addEventListener("click", search);
}

function setDefaultDateTime() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  elTimeInput.value = `${hh}:${mm}`;
  renderDateChips(now);
}

function toDateStr(d) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

function renderDateChips(baseDate) {
  const dayNames = ["일","월","화","수","목","금","토"];
  elDateChips.innerHTML = "";

  for (let i = 0; i < 7; i++) {
    const d = new Date(baseDate);
    d.setDate(baseDate.getDate() + i);
    const dateStr = toDateStr(d);
    const dow = d.getDay();
    const label = i === 0 ? "오늘" : i === 1 ? "내일" : dayNames[dow];
    const isWeekend = dow === 0 || dow === 6;

    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "date-chip" + (isWeekend ? " weekend" : "");
    chip.dataset.date = dateStr;
    chip.innerHTML = `<span class="chip-label">${label}</span><span class="chip-date">${d.getMonth()+1}/${d.getDate()}</span>`;

    chip.addEventListener("click", () => selectDateChip(dateStr));
    elDateChips.appendChild(chip);
  }

  selectDateChip(toDateStr(baseDate));
}

function selectDateChip(dateStr) {
  selectedDate = dateStr;
  elDateChips.querySelectorAll(".date-chip").forEach((c) => {
    c.classList.toggle("selected", c.dataset.date === dateStr);
  });
}

async function loadConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/config`);
    const cfg = await res.json();

    if (!cfg.kakao_js_key) {
      elApiWarning.classList.add("visible");
      return;
    }

    // 카카오 지도 SDK 동적 로드만 (지도 초기화는 결과 표시 시에)
    await loadKakaoMapSDK(cfg.kakao_js_key);
  } catch (e) {
    console.error("설정 로드 실패:", e);
    elApiWarning.classList.add("visible");
  }
}

function loadKakaoMapSDK(jsKey) {
  return new Promise((resolve, reject) => {
    if (window.kakao && kakao.maps) { resolve(); return; }

    const script = document.createElement("script");
    script.src = `//dapi.kakao.com/v2/maps/sdk.js?appkey=${jsKey}&autoload=false`;
    script.onload = () => {
      kakao.maps.load(() => resolve());
    };
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

async function loadHospitals() {
  try {
    const res = await fetch(`${API_BASE}/api/hospitals`);
    const data = await res.json();
    hospitals = data.hospitals || [];
    elHospitalSearch.placeholder = "병원명 검색 또는 클릭하여 선택";
  } catch (e) {
    console.error("병원 목록 로드 실패:", e);
    elHospitalSearch.placeholder = "병원 목록 로드 실패";
  }
}

// ===== 병원 검색 드롭다운 =====
const HOSPITAL_GROUPS = [
  { label: "가톨릭대학교", ids: ["cmcyoido", "cmcseoul", "cmcep"] },
  { label: "연세대학교",   ids: ["severance-sinchon", "gangnam-severance"] },
  { label: "성균관대학교", ids: ["samsungh"] },
  { label: "울산대학교",   ids: ["amc"] },
  { label: "고려대학교",   ids: ["guro-kumc"] },
  { label: "한양대학교",   ids: ["hanyang-seoul"] },
  { label: "이화여자대학교", ids: ["eumc-mokdong"] },
  { label: "중앙대학교",   ids: ["cau-hospital"] },
  { label: "순천향대학교", ids: ["schmc-seoul"] },
];

function appendHospitalItem(h) {
  const item = document.createElement("div");
  item.className = "autocomplete-item";
  item.innerHTML = `<span class="place-name">${h.name}</span>`;
  item.addEventListener("mousedown", (e) => {
    e.preventDefault();
    selectedHospitalId = h.id;
    elHospitalSearch.value = h.name;
    closeHospitalDropdown();
  });
  elHospitalList.appendChild(item);
}

function renderHospitalDropdown(query = "") {
  elHospitalList.innerHTML = "";

  if (query.trim()) {
    // 검색 시: flat 리스트
    const filtered = hospitals.filter((h) =>
      h.name.includes(query) || (h.short_name && h.short_name.includes(query))
    );
    if (filtered.length === 0) { closeHospitalDropdown(); return; }
    filtered.forEach(appendHospitalItem);
  } else {
    // 전체 표시: 대학별 그룹핑
    HOSPITAL_GROUPS.forEach((group) => {
      const groupHospitals = group.ids.map((id) => hospitals.find((h) => h.id === id)).filter(Boolean);
      if (groupHospitals.length === 0) return;

      const header = document.createElement("div");
      header.className = "autocomplete-group-header";
      header.textContent = group.label;
      elHospitalList.appendChild(header);

      groupHospitals.forEach(appendHospitalItem);
    });
    if (elHospitalList.children.length === 0) { closeHospitalDropdown(); return; }
  }

  elHospitalList.style.display = "block";
}

function closeHospitalDropdown() {
  elHospitalList.style.display = "none";
  elHospitalList.innerHTML = "";
}

// ===== 자동완성 =====
function onOriginInput() {
  const query = elOriginInput.value.trim();
  clearTimeout(autocompleteTimer);

  if (query.length < 2) { closeAutocomplete(); return; }

  autocompleteTimer = setTimeout(() => fetchAutocomplete(query), 300);
}

async function fetchAutocomplete(query) {
  try {
    const res = await fetch(`${API_BASE}/api/search?keyword=${encodeURIComponent(query)}`);
    const data = await res.json();
    renderAutocomplete(data.results || []);
  } catch (e) {
    closeAutocomplete();
  }
}

function renderAutocomplete(results) {
  elAutoList.innerHTML = "";
  if (results.length === 0) { closeAutocomplete(); return; }

  results.forEach((r) => {
    const item = document.createElement("div");
    item.className = "autocomplete-item";
    item.innerHTML = `
      <span class="place-name">${r.name}</span>
      <span class="place-address">${r.address}</span>
    `;
    item.addEventListener("click", () => {
      elOriginInput.value = r.address || r.name;
      closeAutocomplete();
    });
    elAutoList.appendChild(item);
  });

  elAutoList.style.display = "block";
}

function closeAutocomplete() {
  elAutoList.style.display = "none";
  elAutoList.innerHTML = "";
}

// ===== 길찾기 =====
async function search() {
  const origin = elOriginInput.value.trim();
  const hospitalId = selectedHospitalId;
  const time = elTimeInput.value;
  const date = selectedDate;

  if (!origin) {
    alert("출발지를 입력해주세요.");
    elOriginInput.focus();
    return;
  }

  if (!hospitalId) {
    alert("목적지 병원을 선택해주세요.");
    elHospitalSearch.focus();
    return;
  }

  setLoading(true);
  elResults.style.display = "none";

  try {
    const res = await fetch(`${API_BASE}/api/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        origin_address: origin,
        hospital_id: hospitalId,
        departure_time: time || null,
        departure_date: date || null,
      }),
    });

    if (!res.ok) {
      let msg = "경로 탐색 실패";
      try { const err = await res.json(); msg = err.detail || msg; } catch {}
      throw new Error(msg);
    }

    const data = await res.json();
    currentRouteData = data;
    renderResults(data);

    // 지도 표시 (컨테이너를 먼저 보여준 뒤 브라우저가 크기를 계산하도록 지연)
    if (window.kakao && kakao.maps) {
      elMapContainer.style.display = "block";
      const bestRoute = data.routes[0] || null;
      setTimeout(() => {
        MapManager.init("map");
        MapManager.renderRoute(data, bestRoute);
      }, 50);
    }
  } catch (e) {
    alert(`오류: ${e.message}`);
  } finally {
    setLoading(false);
  }
}

function setLoading(active) {
  elLoading.classList.toggle("active", active);
  elSearchBtn.disabled = active;
  elSearchBtn.innerHTML = active
    ? '<span class="spinner" style="width:18px;height:18px;border-width:2px"></span> 탐색 중...'
    : '<span>길찾기</span>';
}

// ===== 결과 렌더링 =====
function renderResults(data) {
  elResults.style.display = "block";

  const dayLabels = { weekday: "평일", saturday: "토요일", sunday: "일요일" };
  document.getElementById("result-info").innerHTML = `
    <span class="departure-info">
      ${data.origin.address || "출발지"} →
      <strong>${data.hospital.name}</strong> ·
      출발 ${data.departure_time} (${dayLabels[data.day_type] || data.day_type})
    </span>
  `;

  const container = document.getElementById("route-cards");
  container.innerHTML = "";

  const rec = data.recommendation; // "shuttle" | "transit"
  const hasRoutes = data.routes.length > 0;

  // 추천 안내 배너
  if (rec === "transit" || !hasRoutes) {
    container.insertAdjacentHTML("afterbegin", `
      <div class="notice-banner" style="background:#E8F5E9;border-color:#66BB6A;color:#2E7D32;margin-bottom:8px;">
        대중교통 직접 이동이 더 빠릅니다. 아래 셔틀 경로는 참고용입니다.
      </div>
    `);
  }

  if (!hasRoutes) {
    container.insertAdjacentHTML("beforeend", `
      <div class="unavailable-card" style="background:#FFF3E0;border-color:#FFB74D;">
        <span style="font-size:20px">🚌</span>
        <div>
          <div class="route-name">이용 가능한 셔틀 없음</div>
          <div class="reason">현재 시간에 이용 가능한 셔틀버스가 없습니다. 아래 대중교통 경로를 이용하세요.</div>
        </div>
      </div>
    `);
  } else {
    data.routes.forEach((route, idx) => {
      const isBest = idx === 0 && rec === "shuttle";
      container.appendChild(createRouteCard(route, isBest));
    });
  }

  // 대중교통 경로 (ODsay 실제 데이터 or 추정)
  if (data.transit_routes && data.transit_routes.length > 0) {
    // ODsay 실제 경로
    data.transit_routes.forEach((t, idx) => {
      const isRecommended = rec === "transit" && idx === 0;
      container.appendChild(createTransitCard(t, isRecommended));
    });
  } else if (data.transit_estimate) {
    // 추정값 fallback
    const t = data.transit_estimate;
    const isRecommended = rec === "transit";
    const card = document.createElement("div");
    card.className = "route-card" + (isRecommended ? " best" : "");
    card.style.borderLeft = isRecommended ? "4px solid #1565C0" : "4px solid #7B1FA2";
    card.innerHTML = `
      <div class="route-card-header" style="cursor:default;">
        ${isRecommended ? '<span class="route-type-badge badge-best">추천</span>' : ""}
        <div class="route-type-badge badge-transit">대중교통</div>
        <div class="route-summary">
          <div class="route-total-time">${Math.round(t.total_minutes)}<span>분 (추정)</span></div>
          <div class="route-arrival">거리 약 ${(t.distance_m / 1000).toFixed(1)}km</div>
        </div>
        <div class="route-meta">
          ${mapLinksHtml(data.origin.lat, data.origin.lng, data.origin.address || "출발지", data.hospital.lat, data.hospital.lng, data.hospital.name, "transit")}
        </div>
      </div>
    `;
    container.appendChild(card);
  }

  // 이용 불가 경로
  if (data.unavailable_routes && data.unavailable_routes.length > 0) {
    const section = document.createElement("div");
    section.className = "unavailable-section";
    section.innerHTML = `<div class="unavailable-title">⛔ 현재 이용 불가 셔틀</div>`;

    data.unavailable_routes.forEach((r) => {
      const card = document.createElement("div");
      card.className = "unavailable-card";
      card.innerHTML = `
        <span style="font-size:18px">🚌</span>
        <div>
          <div class="route-name">${r.route_name || ""}</div>
          <div class="reason">${r.reason || ""}</div>
        </div>
      `;
      section.appendChild(card);
    });

    container.appendChild(section);
  }

  // 데이터 출처 안내
  const selectedHospital = hospitals.find((h) => h.id === selectedHospitalId);
  const linkHtml = selectedHospital && selectedHospital.shuttle_info_url
    ? `<a href="${selectedHospital.shuttle_info_url}" target="_blank" style="color:#1565C0;font-weight:700;">${selectedHospital.name} 셔틀 안내</a>`
    : "병원 공식 홈페이지";

  container.insertAdjacentHTML("beforeend", `
    <div class="notice-banner" style="margin-top:12px;">
      ⚠️ 셔틀 운행 시간표는 병원 사정에 따라 변경될 수 있습니다.
      이용 전 ${linkHtml}에서 반드시 확인하세요.
    </div>
  `);
}

function createRouteCard(route, isBest) {
  const card = document.createElement("div");
  card.className = `route-card${isBest ? " best" : ""}`;

  const totalMin = Math.round(route.total_minutes);

  const modeLabel = route.to_stop_mode === "transit" ? "대중교통+셔틀" : "셔틀버스";

  card.innerHTML = `
    <div class="route-card-header">
      ${isBest ? '<span class="route-type-badge badge-best">추천</span>' : ""}
      <span class="route-type-badge badge-shuttle">${modeLabel}</span>
      <div class="route-summary">
        <div class="route-total-time">${totalMin}<span>분</span></div>
        <div class="route-arrival">도착 예정 ${route.arrival_time}</div>
      </div>
      <div class="route-meta">
        <div class="route-fare">${route.transit_fare ? `대중교통 ${route.transit_fare.toLocaleString()}원<br><small>셔틀 무료</small>` : "셔틀 무료"}</div>
        <div>${route.route_name}</div>
      </div>
      <span class="expand-icon">▾</span>
    </div>
    <div class="route-detail">
      <ul class="segment-list">
        ${route.segments.map(renderSegment).join("")}
      </ul>
      ${route.notes ? `<div style="margin-top:10px;font-size:12px;color:#616161;">📌 ${route.notes}</div>` : ""}
    </div>
  `;

  card.querySelector(".route-card-header").addEventListener("click", () => {
    const expanded = card.classList.toggle("expanded");
    // 지도 업데이트
    if (expanded && window.kakao && kakao.maps) {
      MapManager.renderRoute(currentRouteData, route);
    }
  });

  return card;
}

// ===== 지도 링크 헬퍼 =====
function mapLinksHtml(fLat, fLng, fName, tLat, tLng, tName, mode = "transit") {
  const timeVal = elTimeInput ? elTimeInput.value : "";

  const naverUrl = `https://map.naver.com/v5/directions/${fLng},${fLat},${encodeURIComponent(fName)}/${tLng},${tLat},${encodeURIComponent(tName)}/-/-/${mode}`;
  const kakaoUrl = `https://map.kakao.com/link/from/${encodeURIComponent(fName)},${fLat},${fLng}/to/${encodeURIComponent(tName)},${tLat},${tLng}`;

  const timeHint = timeVal
    ? `<div class="map-link-timehint">출발 ${timeVal} 기준으로 직접 설정하세요</div>`
    : "";

  return `
    <div class="map-links">
      ${timeHint}
      <a href="${naverUrl}" target="_blank" class="map-link map-link-naver">네이버지도</a>
      <a href="${kakaoUrl}" target="_blank" class="map-link map-link-kakao">카카오맵</a>
    </div>`;
}

function renderSegment(seg) {
  if (seg.type === "walk") {
    return `
      <li class="segment-item">
        <div class="segment-icon seg-walk">🚶</div>
        <div class="segment-info">
          <div class="segment-label">도보</div>
          <div class="segment-desc">${seg.from_name} → ${seg.to_name} · 약 ${seg.distance_m}m</div>
          ${mapLinksHtml(seg.from_lat, seg.from_lng, seg.from_name, seg.to_lat, seg.to_lng, seg.to_name, "walk")}
        </div>
        <div class="segment-time">${Math.round(seg.duration_minutes)}분</div>
      </li>
    `;
  }

  if (seg.type === "transit_to_stop") {
    if (seg.detail && seg.detail.length > 0) {
      // 상세 데이터가 있으면 각 항목을 독립 세그먼트로 펼쳐서 표시
      return seg.detail.map((d) => renderTransitDetailAsFlatSegment(d)).join("");
    }

    return `
      <li class="segment-item">
        <div class="segment-icon seg-transit">🚇</div>
        <div class="segment-info">
          <div class="segment-label">대중교통 이동 <span style="font-size:10px;color:#9E9E9E;">(추정)</span></div>
          <div class="segment-desc">${seg.from_name} → ${seg.to_name}</div>
          ${mapLinksHtml(seg.from_lat, seg.from_lng, seg.from_name, seg.to_lat, seg.to_lng, seg.to_name, "transit")}
        </div>
        <div class="segment-time">약 ${Math.round(seg.duration_minutes)}분</div>
      </li>
    `;
  }

  if (seg.type === "wait") {
    return `
      <li class="segment-item">
        <div class="segment-icon seg-wait">⏳</div>
        <div class="segment-info">
          <div class="segment-label">셔틀 대기</div>
          <div class="segment-desc">${seg.location}</div>
          <div class="segment-desc">출발 ${seg.departure_time}</div>
        </div>
        <div class="segment-time">${Math.round(seg.duration_minutes)}분 대기</div>
      </li>
    `;
  }

  if (seg.type === "shuttle") {
    return `
      <li class="segment-item">
        <div class="segment-icon seg-shuttle">🚌</div>
        <div class="segment-info">
          <div class="segment-label">셔틀버스</div>
          <div class="segment-desc">${seg.from_name} → ${seg.to_name}</div>
          <div class="segment-desc">${seg.route_name} · ${seg.departure_time} 출발</div>
        </div>
        <div class="segment-time">${seg.duration_minutes}분</div>
      </li>
    `;
  }

  return "";
}

function renderTransitDetailAsFlatSegment(d) {
  const depTime = d.start_time ? `<div class="segment-desc">${d.start_time} 출발</div>` : "";

  if (d.type === "walk") {
    if (!d.duration_minutes) return "";
    const distText = d.distance_m ? ` · 약 ${d.distance_m}m` : "";
    const walkLinks = (d.from_lat && d.to_lat)
      ? mapLinksHtml(d.from_lat, d.from_lng, d.from_name || "출발지", d.to_lat, d.to_lng, d.to_name || "도착지", "walk")
      : "";
    return `
      <li class="segment-item">
        <div class="segment-icon seg-walk">🚶</div>
        <div class="segment-info">
          <div class="segment-label">도보${distText}</div>
          ${d.from_name && d.to_name ? `<div class="segment-desc">${d.from_name} → ${d.to_name}</div>` : ""}
          ${walkLinks}
        </div>
        <div class="segment-time">${Math.round(d.duration_minutes)}분</div>
      </li>
    `;
  }

  if (d.type === "subway") {
    return `
      <li class="segment-item">
        <div class="segment-icon seg-transit">🚇</div>
        <div class="segment-info">
          <div class="segment-label" style="color:#1565C0;">${d.line_name}</div>
          ${depTime}
          <div class="segment-desc">${d.from_name} → ${d.to_name} · ${d.station_count}역</div>
        </div>
        <div class="segment-time">${d.duration_minutes}분</div>
      </li>
    `;
  }

  if (d.type === "bus") {
    return `
      <li class="segment-item">
        <div class="segment-icon" style="background:#FFF3E0;color:#E65100;font-size:16px;">🚌</div>
        <div class="segment-info">
          <div class="segment-label" style="color:#E65100;">${d.bus_no}번 버스</div>
          ${depTime}
          <div class="segment-desc">${d.from_name} → ${d.to_name} · ${d.station_count}정류장</div>
        </div>
        <div class="segment-time">${d.duration_minutes}분</div>
      </li>
    `;
  }

  return "";
}

function createTransitCard(route, isRecommended) {
  const card = document.createElement("div");
  card.className = `route-card${isRecommended ? " best" : ""}`;
  card.style.borderLeft = isRecommended ? "4px solid #1565C0" : "4px solid #7B1FA2";

  const transferText = route.transfers > 0 ? `환승 ${route.transfers}회` : "환승 없음";
  const fareText = route.fare ? `${route.fare.toLocaleString()}원` : "";

  card.innerHTML = `
    <div class="route-card-header">
      ${isRecommended ? '<span class="route-type-badge badge-best">추천</span>' : ""}
      <div class="route-type-badge badge-transit">대중교통</div>
      <div class="route-summary">
        <div class="route-total-time">${Math.round(route.total_minutes)}<span>분</span></div>
        <div class="route-arrival">도착 예정 ${route.arrival_time}</div>
      </div>
      <div class="route-meta">
        <div class="route-fare">${fareText}</div>
        <div>${transferText}</div>
      </div>
      <span class="expand-icon">▾</span>
    </div>
    <div class="route-detail">
      <ul class="segment-list">
        ${route.segments.map(renderTransitSegment).join("")}
      </ul>
      ${currentRouteData ? mapLinksHtml(
          currentRouteData.origin.lat, currentRouteData.origin.lng, currentRouteData.origin.address || "출발지",
          currentRouteData.hospital.lat, currentRouteData.hospital.lng, currentRouteData.hospital.name,
          "transit"
        ) : ""}
    </div>
  `;

  card.querySelector(".route-card-header").addEventListener("click", () => {
    const expanded = card.classList.toggle("expanded");
    if (expanded && window.kakao && kakao.maps) {
      MapManager.renderTransitRoute(currentRouteData, route);
    }
  });

  return card;
}

function renderTransitSegment(seg) {
  if (seg.type === "walk") {
    if (!seg.duration_minutes) return "";
    return `
      <li class="segment-item">
        <div class="segment-icon seg-walk">🚶</div>
        <div class="segment-info">
          <div class="segment-label">도보</div>
          <div class="segment-desc">약 ${seg.distance_m}m</div>
        </div>
        <div class="segment-time">${seg.duration_minutes}분</div>
      </li>
    `;
  }

  if (seg.type === "subway") {
    const depTime = seg.start_time ? `<div class="segment-dep-time">${seg.start_time} 출발</div>` : "";
    return `
      <li class="segment-item">
        <div class="segment-icon seg-transit">🚇</div>
        <div class="segment-info">
          <div class="segment-label" style="color:#1565C0;">${seg.line_name}</div>
          ${depTime}
          <div class="segment-desc">${seg.from_name} → ${seg.to_name}</div>
          <div class="segment-desc">${seg.station_count}개 역</div>
        </div>
        <div class="segment-time">${seg.duration_minutes}분</div>
      </li>
    `;
  }

  if (seg.type === "bus") {
    const depTime = seg.start_time ? `<div class="segment-dep-time">${seg.start_time} 출발</div>` : "";
    return `
      <li class="segment-item">
        <div class="segment-icon" style="background:#FFF3E0;color:#E65100;font-size:16px;">🚌</div>
        <div class="segment-info">
          <div class="segment-label" style="color:#E65100;">${seg.bus_no}번 버스</div>
          ${depTime}
          <div class="segment-desc">${seg.from_name} → ${seg.to_name}</div>
          <div class="segment-desc">${seg.station_count}개 정류장</div>
        </div>
        <div class="segment-time">${seg.duration_minutes}분</div>
      </li>
    `;
  }

  return "";
}

// ===== 시작 =====
document.addEventListener("DOMContentLoaded", init);

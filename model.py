import math
import ast
import networkx as nx

# ================= 파라미터 =================
PARAMS = {"A": 1.0, "B": 1.0, "C": 1.0}   # 안전 / 경사 / 교통 가중치
HARD_GRADE = 5.0       # 오르막 5% 이상 → 차단
MIN_LEN_BLOCK = 30     # 30m 미만은 차단 예외
FALLBACK_PEN = 20      # 우회로 없을 때 급경사 벌점
SPEED_KMH = 12         # 예상시간 계산용 평균속도(가정)

SAFETY = {
    "cycleway": 0, "pedestrian": 0, "path": 0, "footway": 0,
    "living_street": 0.1, "residential": 0.2, "service": 0.2,
    "unclassified": 0.5, "tertiary": 1.5, "secondary": 3,
    "primary": 8, "trunk": 10,
}
CAR_ROADS = {"trunk", "primary", "secondary"}


# ================= 보조 함수 =================
def first(v):
    """리스트 또는 '[...]' 문자열로 저장된 값에서 첫 번째 값을 꺼낸다"""
    if isinstance(v, str) and v.startswith("["):
        try:
            v = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return v
    if isinstance(v, list):
        return v[0] if v else None
    return v


def grade_of(d):
    try:
        g = float(d.get("grade", 0))
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(g) else g


def length_of(d):
    try:
        return float(d["length"])
    except (KeyError, TypeError, ValueError):
        return 0.0


def traffic_index(hw, hour):      # 교통량 모의값
    base = {"trunk": 0.9, "primary": 0.8, "secondary": 0.6, "tertiary": 0.4}.get(hw, 0.1)
    peak = 1.0 if hour in (7, 8, 9, 17, 18, 19) else 0.6
    return min(1.0, base * peak)


def safety_score(d):
    hw = first(d.get("highway", "unclassified"))
    s = SAFETY.get(hw, 0.5)
    try:
        lanes = int(first(d.get("lanes", 2)))
    except (TypeError, ValueError):
        lanes = 2
    return s + (3.0 if lanes >= 4 else 1.0 if lanes == 3 else 0.0)


def slope_score(g_pct):
    if g_pct > 0:
        return max(0.0, g_pct - 2) * 1.0
    return max(0.0, -g_pct - 3) * 0.5


def is_blocked(d):
    return grade_of(d) * 100 >= HARD_GRADE and length_of(d) >= MIN_LEN_BLOCK


# ================= 비용 함수 =================
def edge_cost(d, hour=12, hard=True, p=PARAMS):
    if hard and is_blocked(d):
        return None
    hw = first(d.get("highway", "unclassified"))
    g = grade_of(d) * 100
    penalty = (p["A"] * safety_score(d)
               + p["B"] * slope_score(g)
               + p["C"] * 2 * traffic_index(hw, hour))
    if (not hard) and is_blocked(d):
        penalty += FALLBACK_PEN
    return length_of(d) * (1 + penalty)


def build_safe_graph(G, hour=12, hard=True, p=PARAMS):
    H = G.copy()
    remove = []
    for u, v, k, d in H.edges(keys=True, data=True):
        c = edge_cost(d, hour, hard, p)
        if c is None:
            remove.append((u, v, k))
        else:
            d["cost"] = c
    H.remove_edges_from(remove)
    return H, len(remove)


def find_safe_route(G, o, t, hour=12, p=PARAMS):
    H, _ = build_safe_graph(G, hour, True, p)
    try:
        return nx.shortest_path(H, o, t, weight="cost"), H, "하드 차단"
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        H, _ = build_safe_graph(G, hour, False, p)
        return nx.shortest_path(H, o, t, weight="cost"), H, "⚠ 폴백(급경사 최소 포함)"


# ================= 지표 =================
def edges_of(Gx, route, weight):
    return [min(Gx[u][v].values(), key=lambda e: e.get(weight, length_of(e)))
            for u, v in zip(route[:-1], route[1:])]


def metrics(Gx, route, weight):
    es = edges_of(Gx, route, weight)
    total = sum(length_of(e) for e in es)
    car = sum(length_of(e) for e in es if first(e.get("highway")) in CAR_ROADS)
    steep = sum(length_of(e) for e in es if grade_of(e) * 100 >= HARD_GRADE)
    return {
        "거리(m)": round(total),
        "예상시간(분)": round(total / 1000 / SPEED_KMH * 60, 1),
        "차도 비율(%)": round(car / total * 100, 1) if total else 0,
        "최대 오르막(%)": round(max((grade_of(e) for e in es), default=0) * 100, 1),
        "누적 오르막(m)": round(sum(max(0, grade_of(e)) * length_of(e) for e in es), 1),
        "5%↑ 구간(m)": round(steep),
    }

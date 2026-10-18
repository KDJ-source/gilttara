import streamlit as st
import osmnx as ox
import networkx as nx
import folium
import pandas as pd
from streamlit_folium import st_folium
from model import PARAMS, find_safe_route, metrics, is_blocked

st.set_page_config(page_title="길따라 가실라", layout="wide")

CENTER = (35.835, 129.215)


@st.cache_resource
def load_graph():
    return ox.load_graphml("gyeongju_bike.graphml")


@st.cache_resource
def get_blocked_segments(_G):
    segs = []
    for u, v, k, d in _G.edges(keys=True, data=True):
        if is_blocked(d):
            segs.append([(_G.nodes[u]["y"], _G.nodes[u]["x"]),
                         (_G.nodes[v]["y"], _G.nodes[v]["x"])])
    return segs


G = load_graph()
blocked = get_blocked_segments(G)

# ---------- 사이드바 ----------
st.sidebar.header("옵션")
hour = st.sidebar.slider("출발 시간대", 0, 23, 14)
mode = st.sidebar.radio("경로 성향", ["안전 우선", "균형", "거리 우선"], index=0)
A = {"안전 우선": 2.0, "균형": 1.0, "거리 우선": 0.25}[mode]
show_block = st.sidebar.checkbox("블랙존(급경사) 표시", True)

# ---------- 상태 ----------
st.session_state.setdefault("pts", [])
st.session_state.setdefault("last_click", None)
pts = st.session_state.pts

if st.sidebar.button("출발/도착 초기화"):
    pts.clear()          # last_click은 그대로 둠 (이전 클릭이 다시 들어오는 것을 막기 위해)

st.title("길따라 가실라 🚲")
if len(pts) == 0:
    st.info("① 지도에서 **출발지**를 클릭하세요.")
elif len(pts) == 1:
    st.info("② 이제 **도착지**를 클릭하세요.")
else:
    st.success("경로가 표시되었습니다. 다시 클릭하면 새로 시작합니다.")

# ---------- 경로 계산 ----------
route_info = None
if len(pts) == 2:
    o = ox.distance.nearest_nodes(G, X=pts[0][1], Y=pts[0][0])
    t = ox.distance.nearest_nodes(G, X=pts[1][1], Y=pts[1][0])
    try:
        r_basic = nx.shortest_path(G, o, t, weight="length")
        r_safe, H, md = find_safe_route(G, o, t, hour, {**PARAMS, "A": A})
        route_info = (r_basic, r_safe, H, md)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        st.error("경로를 찾을 수 없습니다. 지도 범위 안에서 다시 찍어 주세요.")

# ---------- 지도 ----------
if pts:
    center = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
else:
    center = CENTER
m = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap")


def coords(Gx, r):
    return [(Gx.nodes[n]["y"], Gx.nodes[n]["x"]) for n in r]


if show_block:
    for seg in blocked:
        folium.PolyLine(seg, color="gray", weight=4, opacity=0.7).add_to(m)

if route_info:
    r_basic, r_safe, H, md = route_info
    folium.PolyLine(coords(G, r_basic), color="red", weight=4, opacity=0.7,
                    tooltip="기본 최단경로").add_to(m)
    folium.PolyLine(coords(H, r_safe), color="green", weight=6, opacity=0.9,
                    tooltip="길따라 가실라").add_to(m)

for i, p in enumerate(pts):
    folium.Marker(p, tooltip=["출발", "도착"][i],
                  icon=folium.Icon(color=["blue", "darkred"][i])).add_to(m)

out = st_folium(m, height=550, use_container_width=True,
                returned_objects=["last_clicked"])

# ---------- 클릭 처리 ----------
click = out.get("last_clicked") if out else None
if click:
    p = (click["lat"], click["lng"])
    if p != st.session_state.last_click:
        st.session_state.last_click = p
        if len(pts) >= 2:
            pts.clear()
        pts.append(p)
        st.rerun()

# ---------- 결과 표 ----------
if route_info:
    df = pd.DataFrame({"기본(최단거리)": metrics(G, r_basic, "length"),
                       "길따라 가실라": metrics(H, r_safe, "cost")}).T
    st.subheader("경로 비교")
    st.dataframe(df, use_container_width=True)
    if "폴백" in md:
        st.warning("우회로가 없어 급경사 구간이 일부 포함됩니다. 주의하세요.")
    st.caption("빨강=기본 최단경로 · 초록=길따라 가실라 · 회색=블랙존(5%↑ 오르막) | "
               "도로망 © OpenStreetMap contributors · 고도 SRTM · 교통량은 모의값 · 참고용 안내입니다.")

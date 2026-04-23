import streamlit as st
import requests
import datetime
import math

# 1. 페이지 설정 및 폰트 스타일 (24px 굵게)
st.set_page_config(page_title="날씨 스포일러", layout="centered")
st.markdown("<style>.stTabs [data-baseweb='tab-list'] button [data-testid='stMarkdownContainer'] p {font-size: 24px; font-weight: bold;}</style>", unsafe_allow_html=True)

# --- [기능] 위치 추적 (서버 IP 문제 해결 로직) ---
@st.cache_data
def get_user_location():
    try:
        # IP 기반 위치 추적 시도
        loc_res = requests.get('http://ip-api.com/json', timeout=5).json()
        if loc_res['status'] == 'success' and loc_res['countryCode'] == 'KR': # 한국일 때만 적용
            lat, lon = loc_res['lat'], loc_res['lon']
            addr_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&addressdetails=1"
            addr_res = requests.get(addr_url, headers={'User-Agent': 'WeatherSpoiler/1.0'}).json()
            town = addr_res.get('address', {}).get('city_district') or addr_res.get('address', {}).get('suburb') or "전주시 덕진구"
            return lat, lon, town
    except: pass
    # 서버가 외국에 있거나 실패 시, 사용자님의 기본 지역인 '전주'로 고정 (설계안 준수)
    return 35.843, 127.123, "전주시 덕진구"

def convert_to_grid(lat, lon):
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    DEGRAD = math.pi / 180.0
    re, slat1, slat2, olon, olat = RE / GRID, SLAT1 * DEGRAD, SLAT2 * DEGRAD, OLON * DEGRAD, OLAT * DEGRAD
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5))
    sf = math.pow(math.tan(math.pi * 0.25 + slat1 * 0.5), sn) * math.cos(slat1) / sn
    ro = re * sf / math.pow(math.tan(math.pi * 0.25 + olat * 0.5), sn)
    ra = re * sf / math.pow(math.tan(math.pi * 0.25 + (lat) * DEGRAD * 0.5), sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi: theta -= 2.0 * math.pi
    if theta < -math.pi: theta += 2.0 * math.pi
    nx, ny = math.floor(ra * math.sin(theta * sn) + XO + 0.5), math.floor(ro - ra * math.cos(theta * sn) + YO + 0.5)
    return nx, ny

@st.cache_data(ttl=3600)
def fetch_weather(nx, ny):
    try:
        service_key = st.secrets["SERVICE_KEY"]
        url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
        
        # 한국 시간(KST) 강제 설정 (서버가 외국에 있어도 오늘 날짜 잡기)
        kst_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        if kst_now.hour < 2 or (kst_now.hour == 2 and kst_now.minute < 10):
            base_date = (kst_now - datetime.timedelta(days=1)).strftime("%Y%m%d")
        else:
            base_date = kst_now.strftime("%Y%m%d")
            
        params = {'serviceKey': service_key, 'pageNo': '1', 'numOfRows': '1000', 'dataType': 'JSON', 'base_date': base_date, 'base_time': '0200', 'nx': str(nx), 'ny': str(ny)}
        res = requests.get(url, params=params, timeout=10).json()
        
        if res['response']['header']['resultCode'] == '00':
            return res['response']['body']['items']['item']
        else:
            st.warning(f"기상청 응답 오류: {res['response']['header']['resultMsg']}")
            return None
    except Exception as e:
        st.error(f"연동 오류: {e}")
        return None

# --- [메인 레이아웃] ---
st.title("☀️ 날씨 스포일러")
lat, lon, town_name = get_user_location()
st.caption(f"📍 위치: {town_name} (한국 외 접속 시 전주로 자동 고정)")

items = fetch_weather(*convert_to_grid(lat, lon))

if items:
    w = {}
    for i in items:
        t, c, v = i['fcstTime'], i['category'], i['fcstValue']
        if t not in w: w[t] = {}
        w[t][c] = v

    tab1, tab2 = st.tabs(["🏃 아침운동", "💼 출근길"])

    with tab1:
        st.header("새벽 05:00 가이드")
        t5 = w.get('0500', {})
        if t5:
            temp5, wind5, pcp5 = float(t5.get('TMP', 0)), float(t5.get('WSD', 0)), t5.get('PCP', '강수없음')
            c1, c2, c3 = st.columns(3)
            c1.metric("기온", f"{temp5}°C")
            c2.metric("풍속", f"{wind5}m/s")
            c3.metric("강수", pcp5)
            
            clothing = "봄·가을용 후드티" if temp5 > 5 else "기모 트레이닝복"
            res = [f"{clothing}만 입기엔 바람이 서늘해요.\n\n**바람막이**를 꼭 챙기세요!" if wind5 >= 3.0 else f"{clothing}가 운동하기 딱 좋은 기온입니다."]
            if pcp5 != '강수없음': res.append("바닥이 약간 젖어 있으니 미끄러움에 주의하셔야 합니다.")
            st.info(f"💡 **스포일러 결론**\n\n" + "\n\n".join(res))

    with tab2:
        st.header("오전 07:00~09:00 가이드")
        ct = ['0700', '0800', '0900']
        valid = [float(w[t]['TMP']) for t in ct if t in w]
        if valid:
            avg_t = sum(valid) / len(valid)
            max_p = max([int(w[t]['POP']) for t in ct if t in w])
            st.metric("평균 기온", f"{avg_t:.1f}°C")
            cloth = "가벼운 **자켓이나 가디건**" if avg_t <= 18 else "가벼운 **셔츠**"
            msg = "오후에도 비 소식이 없으니 우산 없이 가뿐하게 출근하세요!" if max_p < 30 else "오후에 **비 소식**이 있으니 우산을 꼭 챙기세요!"
            st.success(f"💡 **스포일러 결론**\n\n출근길은 평온합니다.\n\n{cloth}이면 충분해요.\n\n{msg}")
else:
    st.error("기상청 데이터를 불러오고 있습니다. 잠시만 기다려 주세요!")

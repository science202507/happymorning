import streamlit as st
import requests
import datetime
import math
from streamlit_js_eval import get_geolocation

# 1. 페이지 설정 및 폰트 스타일 (설계안 반영: 24px 굵게)
st.set_page_config(page_title="날씨 스포일러", layout="centered")

st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 24px; font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# 서버(Streamlit Cloud)는 UTC로 동작하므로 항상 한국 시간으로 계산
KST = datetime.timezone(datetime.timedelta(hours=9))
WEEKDAYS = "월화수목금토일"
SKY_TEXT = {1: "☀️ 맑음", 3: "⛅ 구름 많음", 4: "☁️ 흐림"}
PTY_TEXT = {1: "🌧️ 비", 2: "🌨️ 비 또는 눈", 3: "❄️ 눈", 4: "🌦️ 소나기"}

# --- [기능] 위치 추적 및 좌표 변환 ---
DEFAULT_LOCATION = (35.843, 127.123, "전주시 덕진구")

@st.cache_data(ttl=86400)
def get_town_name(lat, lon):
    # 좌표 → "전주시 덕진구 덕진동2가" 같은 한글 주소
    try:
        addr_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=16&addressdetails=1&accept-language=ko"
        addr = requests.get(addr_url, headers={'User-Agent': 'WeatherSpoiler/1.0'}, timeout=5).json().get('address', {})
        parts = [addr.get('city') or addr.get('county'), addr.get('borough'),
                 addr.get('quarter') or addr.get('suburb') or addr.get('town') or addr.get('village')]
        return " ".join(p for p in parts if p) or "현재 위치"
    except: return "현재 위치"

def get_user_location():
    # 서버 IP가 아니라 사용자 브라우저(휴대폰 GPS)의 위치를 사용
    geo = get_geolocation()
    if geo and 'coords' in geo:
        lat, lon = round(geo['coords']['latitude'], 3), round(geo['coords']['longitude'], 3)
        if 33 <= lat <= 39 and 124 <= lon <= 132:
            return lat, lon, get_town_name(lat, lon), "GPS 기반"
        return *DEFAULT_LOCATION, "기본 위치 · 기상청 예보는 국내 위치만 지원해요"
    if geo and 'error' in geo:
        return *DEFAULT_LOCATION, "기본 위치 · 위치 권한을 허용하면 내 동네 날씨가 나와요"
    return *DEFAULT_LOCATION, "기본 위치 · 내 위치를 확인하는 중이에요"

def convert_to_grid(lat, lon):
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * DEGRAD, SLAT2 * DEGRAD, OLON * DEGRAD, OLAT * DEGRAD
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5))
    sf = math.pow(math.tan(math.pi * 0.25 + slat1 * 0.5), sn) * math.cos(slat1) / sn
    ro = re * sf / math.pow(math.tan(math.pi * 0.25 + olat * 0.5), sn)
    ra = re * sf / math.pow(math.tan(math.pi * 0.25 + (lat) * DEGRAD * 0.5), sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi: theta -= 2.0 * math.pi
    if theta < -math.pi: theta += 2.0 * math.pi
    nx = math.floor(ra * math.sin(theta * sn) + XO + 0.5)
    ny = math.floor(ro - ra * math.cos(theta * sn) + YO + 0.5)
    return nx, ny

# --- [기능] 예보 기준 시각 / 대상 날짜 ---
def get_base_datetime(now):
    # 단기예보는 02·05·08·11·14·17·20·23시에 발표되고, 발표 10분 뒤부터 조회 가능
    t = now - datetime.timedelta(minutes=10)
    hours = [h for h in (2, 5, 8, 11, 14, 17, 20, 23) if h <= t.hour]
    if not hours:
        t -= datetime.timedelta(days=1)
        hours = [23]
    return t.strftime("%Y%m%d"), f"{hours[-1]:02d}00"

def get_target_date(now, hour):
    # 해당 시각이 아직 안 지났으면 오늘, 지났으면 내일 예보
    day = now.date() if now.hour < hour else now.date() + datetime.timedelta(days=1)
    return day.strftime("%Y%m%d")

def format_date(ymd):
    d = datetime.datetime.strptime(ymd, "%Y%m%d")
    label = "오늘" if d.date() == datetime.datetime.now(KST).date() else "내일"
    return f"{label} {d.month}월 {d.day}일({WEEKDAYS[d.weekday()]})"

@st.cache_data(ttl=3600)
def fetch_weather(nx, ny, base_date, base_time):
    try:
        service_key = st.secrets["SERVICE_KEY"]
        url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
        params = {'serviceKey': service_key, 'pageNo': '1', 'numOfRows': '1000', 'dataType': 'JSON', 'base_date': base_date, 'base_time': base_time, 'nx': str(nx), 'ny': str(ny)}
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if data['response']['header']['resultCode'] == '00':
            return data['response']['body']['items']['item']
        return None
    except: return None

# --- [기능] 날씨 값 읽기 ---
def read_hour(x, ymd):
    # 기상청 예보 한 시각의 값을 숫자로 정리
    h = {
        'temp': float(x['TMP']), 'wind': float(x.get('WSD', 0)),
        'sky': int(x.get('SKY', 1)), 'pty': int(x.get('PTY', 0)),
        'pop': int(x.get('POP', 0)), 'reh': int(x.get('REH', 50)),
        'pcp': x.get('PCP', '강수없음'),
    }
    h['feel'] = round(feels_like(h['temp'], h['wind'], h['reh'], int(ymd[4:6])))  # 화면 표시와 판단 기준을 맞추려고 정수로
    return h

def feels_like(temp, wind, reh, month):
    # 기상청 체감온도: 5~9월은 습도를 반영한 여름철 식, 10~4월은 바람을 반영한 겨울철 식
    if 5 <= month <= 9:
        tw = (temp * math.atan(0.151977 * (reh + 8.313659) ** 0.5) + math.atan(temp + reh) - math.atan(reh - 1.67633)
              + 0.00391838 * reh ** 1.5 * math.atan(0.023101 * reh) - 4.686035)  # 습구온도
        return -0.2442 + 0.55399 * tw + 0.45535 * temp - 0.0022 * tw ** 2 + 0.00278 * tw * temp + 3.0
    v = wind * 3.6
    if temp <= 10 and v >= 4.8:  # 기온 10°C 이하, 풍속 1.3m/s 이상일 때만 적용
        return 13.12 + 0.6215 * temp - 11.37 * v ** 0.16 + 0.3965 * v ** 0.16 * temp
    return temp

def sun_time(lat, lon, ymd, zenith):
    # NOAA 간이식으로 해 뜨는 쪽 시각(한국 시간, 시 단위 소수) 계산
    # zenith 90.833 = 일출, 96 = 시민박명 시작(하늘이 밝아지기 시작)
    g = 2 * math.pi / 365 * (datetime.datetime.strptime(ymd, "%Y%m%d").timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = 0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g)
    la = math.radians(lat)
    ha = math.degrees(math.acos(math.cos(math.radians(zenith)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)))
    return (720 - 4 * (lon + ha) - eqtime + 540) / 60

def light_advice(lat, lon, ymd):
    dawn, sunrise = sun_time(lat, lon, ymd, 96), sun_time(lat, lon, ymd, 90.833)
    rise = f"{int(sunrise)}시 {int(sunrise % 1 * 60):02d}분"
    if dawn > 5:
        return f"🔦 **안전**: 해 뜨는 시각이 {rise}이라 5시엔 아직 깜깜해요. **집게형 라이트**(클립 후레시)를 옷에 달고, 밝은 색 옷이나 반사띠도 착용하세요."
    return f"🔦 **안전**: 해 뜨는 시각은 {rise}이에요. 5시엔 어둑어둑하니 밝은 색 옷이나 반사띠를 착용하세요."

def sky_text(h):
    return PTY_TEXT.get(h['pty'], SKY_TEXT.get(h['sky'], "☀️ 맑음"))

# --- [기능] 스포일러 결론 ---
def exercise_advice(h, light):
    temp, wind, pty, pop, reh, feel = h['temp'], h['wind'], h['pty'], h['pop'], h['reh'], h['feel']

    # 체감온도 기준 + 새벽 5시 조깅 경험 (해 뜨기 전이라 낮보다 서늘하게 느껴짐)
    if feel >= 27:
        outfit, tip = "기능성 반팔 티셔츠와 반바지", "새벽인데도 더운 편이에요. 물을 꼭 챙기고, 평소보다 강도와 시간을 줄이세요."
    elif feel >= 20:
        outfit, tip = "반팔 티셔츠와 반바지", "땀이 많이 날 수 있으니 물 한 병 챙기세요."
    elif feel >= 15:
        outfit, tip = "반팔 티셔츠에 반바지나 얇은 트레이닝 바지", "처음엔 살짝 서늘해도 10분만 움직이면 금방 따뜻해져요."
    elif feel >= 12:
        outfit, tip = "반팔 티셔츠에 긴 트레이닝 바지, 얇은 점퍼", "출발할 땐 점퍼를 입고, 몸이 데워지면 벗어 허리에 묶으세요."
    elif feel >= 5:
        outfit = "후드티에 긴 트레이닝 바지" + (", 바람을 막는 얇은 바람막이" if wind >= 3 else "")
        tip = "뛰다 보면 더워질 수 있으니 후드티 안에 반팔을 입어 두세요."
    elif feel >= 0:
        outfit, tip = "긴팔 티셔츠 위에 바람막이, 긴 트레이닝 바지와 얇은 장갑", "근육이 굳어 있으니 준비운동을 10분 이상 충분히 하세요."
    elif feel >= -5:
        outfit, tip = "기모 트레이닝복에 장갑과 넥워머", "근육이 굳어 있으니 준비운동을 10분 이상 충분히 하세요."
    elif feel > -10:
        outfit, tip = "기모 트레이닝복에 패딩 조끼, 장갑, 넥워머, 귀마개", "몹시 추워요. 준비운동은 실내에서 충분히 하고, 운동 시간을 평소보다 줄이세요."
    else:
        outfit, tip = "그래도 나간다면 기모 트레이닝복에 패딩 조끼, 장갑, 넥워머, 귀마개", "실내 스트레칭, 계단 오르기, 실내 자전거로 대신해 보세요."

    s = []
    if feel <= -10:
        # 기상청 체감온도 단계: -10°C 이하 '주의' (오래 있으면 동상 위험)
        s.append(f"🏠 **오늘은 실내 운동 추천**: 체감온도 {feel:.0f}°C로 기상청 '주의' 단계예요. 새벽 조깅은 쉬어 가세요.")
    s.append(f"👕 **옷차림**: {outfit}")
    if temp - feel >= 2:
        s.append(f"🌡️ **체감온도**: 기온은 {temp:.0f}°C지만 바람({wind}m/s) 때문에 {feel:.0f}°C처럼 느껴져요. 옷은 체감온도에 맞췄어요.")
    elif feel - temp >= 2:
        s.append(f"🌡️ **체감온도**: 기온은 {temp:.0f}°C지만 습도({reh}%)가 높아 {feel:.0f}°C처럼 느껴져요. 옷은 체감온도에 맞췄어요.")
    else:
        s.append(f"🌡️ **기온**: {temp:.0f}°C, 습도 {reh}%")

    if pty in (3, 7) or (pty in (2, 6) and temp <= 2):
        s.append(f"❄️ **눈**: 눈 예보가 있어요({h['pcp']}). 길이 미끄러우니 실내 운동을 추천해요.")
    elif pty != 0:
        s.append(f"☔ **비**: 비 예보가 있어요({h['pcp']}). 방수 재킷을 입거나 실내 운동으로 바꿔 보세요.")
    elif pop >= 60:
        s.append(f"🌂 **비 가능성**: 강수확률 {pop}%예요. 가까운 코스로 짧게 다녀오세요.")
    else:
        s.append(f"☁️ **하늘**: {sky_text(h)}, 강수확률 {pop}%로 운동하기 좋아요.")
    if temp <= 0 and pty != 0:
        s.append("🧊 **빙판 주의**: 바닥이 얼어 있을 수 있어요. 미끄럼 방지 밑창 신발을 신으세요.")

    if wind >= 3 and temp <= 10:
        s.append(f"🌬️ **바람**: {wind}m/s예요. 달리면 맞바람이 더해져 체감온도가 더 내려가요. 맞바람 방향으로 출발하면 땀이 난 뒤 돌아올 때 덜 추워요.")
    elif wind >= 4 and temp < 20:
        s.append(f"🌬️ **바람**: {wind}m/s로 강해요. 맞바람 방향으로 출발하면 땀이 난 뒤 돌아올 때 덜 추워요.")
    if reh >= 80 and temp >= 20:
        s.append(f"💧 **습도**: {reh}%로 높아 땀이 잘 마르지 않아요. 통풍 잘 되는 기능성 옷을 입으세요.")
    elif reh <= 35:
        s.append(f"💧 **습도**: {reh}%로 건조해요. 목이 쉽게 마르니 물을 자주 마시세요.")

    s.append(light)
    s.append(f"💡 **팁**: {tip}")
    return s

def commute_outfit(temp):
    if temp >= 28: return "반팔 티셔츠나 린넨 셔츠, 얇은 면바지"
    if temp >= 23: return "반팔 티셔츠나 얇은 셔츠, 면바지"
    if temp >= 20: return "얇은 긴팔 셔츠나 블라우스, 얇은 가디건"
    if temp >= 17: return "얇은 니트나 맨투맨, 가디건"
    if temp >= 12: return "자켓이나 가디건, 긴바지"
    if temp >= 9: return "트렌치코트나 자켓, 니트"
    if temp >= 5: return "코트에 히트텍, 니트"
    return "패딩이나 두꺼운 코트, 목도리와 장갑"

def commute_advice(am, day, tmn, tmx):
    # am: 07~09시 값 목록, day: (시각, 값) 목록 (10~18시)
    avg_temp = sum(h['temp'] for h in am) / len(am)
    feel = min(h['feel'] for h in am)
    max_wind = max(h['wind'] for h in am)
    am_pop = max(h['pop'] for h in am)
    am_rain = [h for h in am if h['pty'] != 0]
    day_rain = [(hh, h) for hh, h in day if h['pty'] != 0 or h['pop'] >= 60]
    day_pop = max([h['pop'] for _, h in day], default=0)

    s = [f"👔 **옷차림**: {commute_outfit(feel)}"]
    temp_line = f"🌡️ **기온**: 출근 시간 평균 {avg_temp:.0f}°C"
    if avg_temp - feel >= 2:
        temp_line += f"(체감 {feel:.0f}°C)"
    if tmn is not None and tmx is not None:
        temp_line += f", 하루 기온은 {tmn:.0f}~{tmx:.0f}°C예요."
    elif tmx is not None:
        temp_line += f", 낮 최고 {tmx:.0f}°C예요."
    s.append(temp_line)
    if tmx is not None and tmx - avg_temp >= 8 and avg_temp < 23:
        s.append(f"🧥 **일교차**: 낮에는 {tmx:.0f}°C까지 올라요. 벗기 쉬운 겉옷을 입고 안에는 가볍게 입으세요.")
    if avg_temp >= 25 and max(h['reh'] for h in am) >= 70:
        s.append("💦 **더위**: 덥고 습해서 땀이 나기 쉬워요. 통풍 잘 되는 옷에 손수건을 챙기세요.")

    s.append(f"☁️ **하늘**: 출근길 {sky_text(am[0])}")
    if am_rain:
        snow = any(h['pty'] in (2, 3, 6, 7) for h in am_rain)
        s.append(f"☔ **우산**: 출근길에 {'눈' if snow else '비'} 예보가 있어요({am_rain[0]['pcp']}). 우산을 꼭 챙기세요!")
        s.append("👟 **신발**: 방수 신발이나 젖어도 괜찮은 신발을 신으세요." + (" 길이 미끄러우니 대중교통을 이용하세요." if snow else ""))
    elif am_pop >= 60:
        s.append(f"☔ **우산**: 출근길 강수확률이 {am_pop}%예요. 우산을 꼭 챙기세요!")
    elif day_rain:
        first = day_rain[0][0]
        first = f"오전 {first}시" if first < 12 else f"오후 {first - 12 if first > 12 else first}시"
        s.append(f"☔ **우산**: 출근길은 괜찮지만 **{first}쯤부터 비 소식**이 있어요. 퇴근길을 위해 우산을 챙기세요!")
    elif max(am_pop, day_pop) >= 30:
        s.append(f"🌂 **우산**: 강수확률이 최대 {max(am_pop, day_pop)}%예요. 접이식 우산이 있으면 든든해요.")
    else:
        s.append("😎 **우산**: 하루 종일 비 소식이 없으니 우산 없이 가뿐하게 출근하세요!")

    if max_wind >= 5:
        s.append(f"🌬️ **바람**: {max_wind}m/s로 강하게 불어요." + (" 우산이 뒤집힐 수 있으니 튼튼한 우산을 챙기세요." if am_rain or am_pop >= 60 else " 머리와 옷깃이 날릴 수 있어요."))
    return s

# --- [UI] ---
st.title("☀️ 날씨 스포일러")
lat, lon, town_name, loc_note = get_user_location()
st.caption(f"📍 위치: {town_name} ({loc_note})")

now = datetime.datetime.now(KST)
base_date, base_time = get_base_datetime(now)
items = fetch_weather(*convert_to_grid(lat, lon), base_date, base_time)

if items:
    # 같은 시각이라도 날짜가 다르면 다른 예보이므로 (날짜, 시각)으로 구분
    w = {}
    for i in items:
        key = (i['fcstDate'], i['fcstTime'])
        w.setdefault(key, {})[i['category']] = i['fcstValue']

    tab1, tab2 = st.tabs(["🏃 아침운동", "💼 출근길"])

    with tab1:
        ex_date = get_target_date(now, 5)
        st.header(f"{format_date(ex_date)} 새벽 05:00 가이드")
        t5 = w.get((ex_date, '0500'), {})
        if 'TMP' in t5:
            h5 = read_hour(t5, ex_date)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("기온", f"{h5['temp']:.0f}°C")
            c2.metric("체감온도", f"{h5['feel']:.0f}°C")
            c3.metric("풍속", f"{h5['wind']}m/s")
            c4.metric("강수확률", f"{h5['pop']}%")
            st.info(f"💡 **스포일러 결론**\n\n" + "\n\n".join(exercise_advice(h5, light_advice(lat, lon, ex_date))))
        else:
            st.warning("새벽 예보 데이터가 준비 중입니다.")

    with tab2:
        cm_date = get_target_date(now, 7)
        st.header(f"{format_date(cm_date)} 오전 07:00~09:00 가이드")
        am = [read_hour(w[(cm_date, t)], cm_date) for t in ('0700', '0800', '0900') if 'TMP' in w.get((cm_date, t), {})]
        if am:
            day = [(hh, read_hour(w[(cm_date, f"{hh:02d}00")], cm_date)) for hh in range(10, 19) if 'TMP' in w.get((cm_date, f"{hh:02d}00"), {})]
            day_vals = [v for (d, _), v in w.items() if d == cm_date]
            tmn = next((float(v['TMN']) for v in day_vals if 'TMN' in v), None)
            tmx = next((float(v['TMX']) for v in day_vals if 'TMX' in v), None)

            avg_temp = sum(h['temp'] for h in am) / len(am)
            c1, c2, c3 = st.columns(3)
            c1.metric("평균 기온", f"{avg_temp:.1f}°C")
            c2.metric("체감온도", f"{min(h['feel'] for h in am):.0f}°C")
            c3.metric("강수확률", f"{max([h['pop'] for h in am] + [h['pop'] for _, h in day])}%")
            st.success(f"💡 **스포일러 결론**\n\n" + "\n\n".join(commute_advice(am, day, tmn, tmx)))
        else:
            st.warning("출근길 예보 데이터가 준비 중입니다.")
else:
    st.error("데이터를 가져오는 중입니다. 잠시만 기다려 주세요.")

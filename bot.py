import warnings, os, json
warnings.filterwarnings("ignore")
os.environ["STREAMLIT_SERVER_SUPPRESS_NOWARNINGS"] = "true"
import streamlit as st, ccxt, time, pandas as pd, numpy as np
import streamlit.components.v1 as components
from datetime import datetime, timedelta

# [기능 추가] 데이터 영구 저장을 위한 설정
DATA_FILE = "trading_data.json"

def save_data():
    data_to_save = {
        'daily_stats': st.session_state.daily_stats,
        'trade_logs': st.session_state.trade_logs,
        'last_trade_end_time': {k: v.isoformat() for k, v in st.session_state.last_trade_end_time.items()},
        'active_virtual_positions': st.session_state.active_virtual_positions
    }
    with open(DATA_FILE, 'w') as f: json.dump(data_to_save, f)

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                st.session_state.daily_stats = data.get('daily_stats', st.session_state.daily_stats)
                st.session_state.trade_logs = data.get('trade_logs', st.session_state.trade_logs)
                saved_times = data.get('last_trade_end_time', {})
                for k, v in saved_times.items():
                    st.session_state.last_trade_end_time[k] = datetime.fromisoformat(v)
                st.session_state.active_virtual_positions = data.get('active_virtual_positions', st.session_state.active_virtual_positions)
        except: pass

# [기능 추가] 데이터 초기화 함수
def reset_data():
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    for key in ['daily_stats', 'trade_logs', 'last_trade_end_time', 'active_virtual_positions', 'any_position_active']:
        if key in st.session_state: del st.session_state[key]
    st.rerun()

def get_api_config():
    """OKX API 설정 — Streamlit Cloud secrets 또는 로컬 .streamlit/secrets.toml 사용."""
    try:
        okx = st.secrets["okx"]
        api_key = okx["apiKey"]
        secret = okx["secret"]
        password = okx["password"]
        if not api_key or not secret or not password:
            return None
        return {
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
        }
    except Exception:
        return None
SYMBOL, TAKER_FEE = 'BTC/USDT:USDT', 0.0005
ALL_TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h']
CD_CONF = {
    '5m': timedelta(minutes=20), 
    '15m': timedelta(hours=1), '30m': timedelta(hours=2), 
    '1h': timedelta(hours=4), '4h': timedelta(hours=16)
}

if 'daily_stats' not in st.session_state:
    st.session_state.daily_stats = {'total_bets':0, 'wins':0, 'losses':0, 'net_profit':0.0}
if 'trade_logs' not in st.session_state:
    st.session_state.trade_logs = []
if 'last_trade_end_time' not in st.session_state:
    st.session_state.last_trade_end_time = {tf: datetime(2000,1,1) for tf in ALL_TIMEFRAMES}
if 'active_virtual_positions' not in st.session_state:
    st.session_state.active_virtual_positions = {tf: None for tf in ALL_TIMEFRAMES}

load_data() 

st.set_page_config(page_title="OKX 지능형 제어 시스템", layout="wide")
st.title("🤖 OKX 멀티 타임프레임 자율매매 및 트레이딩뷰 통합 시스템")

if 'any_position_active' not in st.session_state:
    st.session_state['any_position_active'] = False

st.sidebar.header("🎛️ 시스템 컨트롤 패널")
is_running = st.sidebar.toggle("⚡ 자율매매 자동 연산 시작", value=False)
st.sidebar.markdown("---")
# [기능 추가] 초기화 버튼
if st.sidebar.button("⚠️ 모든 데이터 초기화"):
    reset_data()
st.sidebar.markdown("---")
TARGET_TF = st.sidebar.selectbox("롱/숏 포지션 진입 타겟 시간대 선택", ALL_TIMEFRAMES, index=3)
st.sidebar.markdown("---")
구동모드 = st.sidebar.radio("🔄 구동 모드", ('가상모드 (모의투자)', '실제모드 (라이브 거래)'))
is_test = (구동모드 == '가상모드 (모의투자)')
MARGIN_MODE = st.sidebar.radio("🛡️ 마진 모드", ('isolated (격리)', 'cross (교차)')).split()[0]
LEVERAGE = st.sidebar.number_input("🚀 레버리지 배수", min_value=1, max_value=100, value=3)
SL_INPUT = st.sidebar.number_input("📉 손절 기준 (%)", min_value=0.1, value=2.0, step=0.5)
TP_INPUT = st.sidebar.number_input("📈 익절 기준 (%)", min_value=0.1, value=5.0, step=0.5)
TEST_BAL = st.sidebar.number_input("🧪 가상 초기 자산", value=5000.0)
MIN_MATCH = st.sidebar.slider("⚙️ 최소 기법 일치 개수", min_value=1, max_value=12, value=3)
INVS_RATIO = st.sidebar.slider("💰 1회당 자산 투자 비율 (%)", min_value=1, max_value=100, value=10) / 100

exchange = ccxt.okx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
if not is_test:
    api_config = get_api_config()
    if api_config is None:
        st.error("실제모드에는 OKX API 키가 필요합니다. Streamlit Cloud Secrets 또는 `.streamlit/secrets.toml`에 `[okx]` 섹션을 설정하세요.")
        st.stop()
    try:
        exchange = ccxt.okx(api_config)
        exchange.set_margin_mode(MARGIN_MODE.upper(), SYMBOL)
        exchange.set_leverage(int(LEVERAGE), SYMBOL)
    except Exception as e:
        st.error(f"거래소 연동 실패: {e}")

def render_tradingview_chart(tf_str):
    tv_tf = "5" if tf_str == "5m" else "15" if tf_str == "15m" else "30" if tf_str == "30m" else "60" if tf_str == "1h" else "240"
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:550px;width:100%;">
      <div id="tradingview_chart"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{"autosize": true, "symbol": "OKX:BTCUSDT.P", "interval": "{tv_tf}", "timezone": "Asia/Seoul", "theme": "dark", "style": "1", "locale": "ko", "toolbar_bg": "#f1f3f6", "enable_publishing": false, "hide_side_toolbar": false, "allow_symbol_change": true, "container_id": "tradingview_chart", "studies": ["MASimple@tv-basicstudies"]}});
      </script>
    </div>
    """
    components.html(tv_html, height=560)

def execute_order(tf, side, amount, curr_price, matched_reasons):
    if st.session_state['any_position_active']: return
    st.session_state['any_position_active'] = True
    entry_time = datetime.now()
    tp = curr_price * (1 + (TP_INPUT/100) + (TAKER_FEE * 2)) if side == 'buy' else curr_price * (1 - (TP_INPUT/100) - (TAKER_FEE * 2))
    sl = curr_price * (1 - (SL_INPUT/100) - (TAKER_FEE * 2)) if side == 'buy' else curr_price * (1 + (SL_INPUT/100) + (TAKER_FEE * 2))
    st.session_state.trade_logs.insert(0, f"[{entry_time.strftime('%H:%M:%S.%f')[:-3]}] {tf} {side.upper()} 진입 ({len(matched_reasons)}개 일치): {', '.join(matched_reasons)}")
    st.session_state.daily_stats['total_bets'] += 1
    if is_test: st.session_state.active_virtual_positions[tf] = {'side': side, 'entry_price': curr_price, 'amount': amount, 'tp': tp, 'sl': sl, 'reasons': matched_reasons, 'entry_time': entry_time.isoformat()}
    else:
        try:
            exchange.create_market_order(SYMBOL, side, amount)
            exchange.create_order(SYMBOL, 'market', 'sell' if side == 'buy' else 'buy', amount, params={'triggerPrice': exchange.price_to_precision(SYMBOL, tp), 'reduceOnly': True})
            exchange.create_order(SYMBOL, 'market', 'sell' if side == 'buy' else 'buy', amount, params={'triggerPrice': exchange.price_to_precision(SYMBOL, sl), 'reduceOnly': True})
        except Exception as e: 
            st.error(f"주문 실패: {e}"); st.session_state['any_position_active'] = False
    save_data()

def check_virtual_pos(tf, current_price):
    pos = st.session_state.active_virtual_positions[tf]
    if not pos: return
    sd, et, am, tp, sl, entry_time = pos['side'], pos['entry_price'], pos['amount'], pos['tp'], pos['sl'], datetime.fromisoformat(pos['entry_time'])
    cleared, win, pnl = False, False, 0.0
    if sd == 'buy':
        if current_price >= tp: cleared, win, pnl = True, True, (tp - et) * am
        elif current_price <= sl: cleared, win, pnl = True, False, (sl - et) * am
    else:
        if current_price <= tp: cleared, win, pnl = True, True, (et - tp) * am
        elif current_price >= sl: cleared, win, pnl = True, False, (sl - et) * am
    if cleared:
        exit_time = datetime.now()
        duration = exit_time - entry_time
        st.session_state.trade_logs.insert(0, f"[{exit_time.strftime('%H:%M:%S.%f')[:-3]}] {tf} {'WIN' if win else 'LOSE'} 포지션 종료 (소요시간: {duration.total_seconds():.1f}초)")
        st.session_state.daily_stats['net_profit'] += pnl
        if win: st.session_state.daily_stats['wins'] += 1; st.balloons()
        else: st.session_state.daily_stats['losses'] += 1
        st.session_state.active_virtual_positions[tf], st.session_state.last_trade_end_time[tf] = None, exit_time
        st.session_state['any_position_active'] = False
        save_data()

def plot_profit_loss(tf, entry_price, tp, sl, current_price):
    target_sl = (sl - entry_price) / entry_price * 100
    target_tp = (tp - entry_price) / entry_price * 100
    current_profit = (current_price - entry_price) / entry_price * 100
    data = pd.DataFrame({'지표': ['손절액', '익절액', '현재 손익'], '손익 (%)': [target_sl, target_tp, current_profit]})
    st.bar_chart(data, x='지표', y='손익 (%)')

def get_market_data():
    try:
        trades, w_buy, w_sell, vol = exchange.fetch_trades(SYMBOL, limit=100), 0.0, 0.0, 0.0
        for t in trades:
            v = t['price'] * t['amount']; vol += t['amount']
            if v >= 50000:
                if t['side'] == 'buy': w_buy += v
                else: w_sell += v
        ratio = float(exchange.publicGetPublicLongShortPositionRatio({'instId': SYMBOL.replace('/USDT:USDT', '-USDT-SWAP'), 'period': '5m'})['data'][0]['ratio']) * 100
        return w_buy, w_sell, ratio, 100.0 - ratio, vol
    except: return 50000, 50000, 50.0, 50.0, 10.0

def get_indicators(tf):
    try:
        ohlcv = exchange.fetch_ohlcv(SYMBOL, tf, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['SMA_5'], df['SMA_20'], df['SMA_60'] = df['close'].rolling(5).mean(), df['close'].rolling(20).mean(), df['close'].rolling(60).mean()
        df['Vol_MA20'] = df['volume'].rolling(20).mean()
        dt = df['close'].diff()
        gn, ls = dt.where(dt > 0, 0).rolling(14).mean(), (-dt.where(dt < 0, 0)).rolling(14).mean()
        df['RSI'] = 100 - (100 / (1 + (gn / (ls + 1e-5))))
        e1, e2 = df['close'].ewm(span=12, adjust=False).mean(), df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = e1 - e2
        df['MACD_sig'] = df['MACD'].ewm(span=9, adjust=False).mean()
        sd = df['close'].rolling(20).std()
        df['BBU'], df['BBL'] = df['SMA_20'] + (sd * 2), df['SMA_20'] - (sd * 2)
        return df
    except: return None

col1, col2, col3 = st.columns(3)
if is_test:
    cur_bal = TEST_BAL + st.session_state.daily_stats['net_profit']
    col1.metric("💰 자산 (실시간 변동)", f"{cur_bal:.2f} USDT", f"{st.session_state.daily_stats['net_profit']:+.2f} USDT")
else:
    try: col1.metric("💰 자산 (실전)", f"{exchange.fetch_balance()['total']['USDT']:.2f} USDT")
    except: col1.metric("💰 자산 (실전)", "대기중...")
col2.metric("📈 배팅 횟수", f"{st.session_state.daily_stats['total_bets']} 회")
col3.metric("🏆 실시간 승률", f"{st.session_state.daily_stats['wins']}승 / {st.session_state.daily_stats['losses']}패")

st.markdown("---")
active_pos_any = False
for tf in ALL_TIMEFRAMES:
    if st.session_state.active_virtual_positions[tf]:
        pos = st.session_state.active_virtual_positions[tf]
        side_label = "🟢 [롱 포지션]" if pos['side'] == 'buy' else "🔴 [숏 포지션]"
        st.subheader(f"🚀 실시간 배팅 중인 포지션 정보 [{tf}] {side_label}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("진입 시장가", f"{pos['entry_price']:.1f} USDT")
        c2.metric("배팅 금액", f"{pos['amount'] * pos['entry_price']:.2f} USDT")
        c3.metric("손절가(SL)", f"{pos['sl']:.1f} USDT")
        c4.metric("익절가(TP)", f"{pos['tp']:.1f} USDT")
        active_pos_any = True
if not active_pos_any: st.info("현재 활성화된 포지션이 없습니다.")

st.markdown("---")
tabs = st.tabs([f"⏱️ {tf} 분석실" + (" ★타겟★" if tf == TARGET_TF else "") for tf in ALL_TIMEFRAMES])
now = datetime.now()
w_buy, w_sell, l_ratio, s_ratio, live_vol = get_market_data()

for idx, tf in enumerate(ALL_TIMEFRAMES):
    with tabs[idx]:
        df = get_indicators(tf)
        if df is None or df['SMA_20'].isna().iloc[-1]: continue
        cp = df['close'].iloc[-1]
        if is_test and st.session_state.active_virtual_positions[tf]:
            pos = st.session_state.active_virtual_positions[tf]
            plot_profit_loss(tf, pos['entry_price'], pos['tp'], pos['sl'], cp)
        st.write(f"**현재 {tf} 종가:** `{cp:.1f} USDT`")
        if now - st.session_state.last_trade_end_time[tf] < CD_CONF[tf]:
            st.error("🔒 포지션 종료 후 쿨다운 대기 제어 중"); continue
        breas, sreas = [], []
        b_sc, s_sc = 0, 0
        rsi_cur = df['RSI'].iloc[-1]
        sma5, sma20 = df['SMA_5'].iloc[-1], df['SMA_20'].iloc[-1]
        macd_cur, macd_sig = df['MACD'].iloc[-1], df['MACD_sig'].iloc[-1]
        macd_prev, macd_sig_prev = df['MACD'].iloc[-2], df['MACD_sig'].iloc[-2]
        bbu, bbl = df['BBU'].iloc[-1], df['BBL'].iloc[-1]

        if rsi_cur < 30: breas.append("RSI 과매도"); b_sc += 3
        elif rsi_cur > 70: sreas.append("RSI 과매수"); s_sc += 3

        if sma5 > sma20 and cp > sma20: breas.append("SMA 상승 정렬"); b_sc += 2
        elif sma5 < sma20 and cp < sma20: sreas.append("SMA 하락 정렬"); s_sc += 2

        if macd_cur > macd_sig and macd_prev <= macd_sig_prev: breas.append("MACD 골든 크로스"); b_sc += 2
        elif macd_cur < macd_sig and macd_prev >= macd_sig_prev: sreas.append("MACD 데드 크로스"); s_sc += 2
        elif macd_cur > macd_sig: breas.append("MACD 상승 모멘텀"); b_sc += 2
        elif macd_cur < macd_sig: sreas.append("MACD 하락 모멘텀"); s_sc += 2

        if cp <= bbl: breas.append("BB 하단 터치"); b_sc += 2
        elif cp >= bbu: sreas.append("BB 상단 터치"); s_sc += 2

        bm, sm, sig, m_reas = len(breas), len(sreas), "HOLD", []
        if b_sc >= 5 and bm >= MIN_MATCH: sig, m_reas = "BUY", breas
        elif s_sc >= 5 and sm >= MIN_MATCH: sig, m_reas = "SELL", sreas
        if is_test and st.session_state.active_virtual_positions[tf]:
            check_virtual_pos(tf, cp)
            if st.session_state.active_virtual_positions[tf]: st.warning("📦 현재 포지션 유지 관리 중"); continue
        st.write(f"🟢 롱 매칭: **{bm}개** ({b_sc}점) | 🔴 숏 매칭: **{sm}개** ({s_sc}점)")
        if "BUY" in sig or "SELL" in sig:
            st.success(f"🔥 포지션 진입 조건 충족: {sig}")
            if st.session_state['any_position_active']: st.warning("🔒 다른 타임프레임에서 포지션이 이미 진입되어 대기 중입니다.")
            elif is_running: execute_order(tf, 'buy' if sig=="BUY" else 'sell', (TEST_BAL if is_test else exchange.fetch_balance()['total']['USDT'])*INVS_RATIO*LEVERAGE/cp, cp, m_reas)
        else: st.info("💤 조건 미달로 진입 대기 중")

st.markdown("---")
st.subheader(f"🖥️ 메인 모니터링 및 진입 타겟 차트: 【 {TARGET_TF} 】")
main_col_left, main_col_right = st.columns([3, 1])
with main_col_left: render_tradingview_chart(TARGET_TF)
with main_col_right:
    main_df = get_indicators(TARGET_TF)
    if main_df is not None:
        st.metric("현재 타겟 시장가", f"{main_df['close'].iloc[-1]:.1f} USDT")

cl, cr = st.columns(2)
with cl:
    st.subheader("📊 실시간 고래 및 포지션 쏠림")
    st.progress(w_buy / (w_buy + w_sell + 1e-5), text=f"🟢 매수고래:{w_buy/1000:.1f}K | 🔴 매도고래:{w_sell/1000:.1f}K")
with cr:
    st.subheader("📜 실시간 시스템 매매 타임라인 기록")
    if st.session_state.trade_logs:
        for log in st.session_state.trade_logs[:3]: st.info(log)
time.sleep(10)
st.rerun()
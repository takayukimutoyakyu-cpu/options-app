import streamlit as st
import yfinance as yf
import pandas as pd
import anthropic
from datetime import datetime, timedelta
import time
import os
import numpy as np
import json

try:
    from streamlit_local_storage import LocalStorage
    _local_storage_available = True
except ImportError:
    _local_storage_available = False

ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))

# ========== プロフィール設定 ==========
DEFAULT_PROFILE = {
    "name": "",
    "age_group": "30代",
    "gender": "答えない",
    "experience": "未経験",
    "risk_tolerance": "バランス重視",
    "investment_goal": "副収入を得たい",
    "default_capital": 5000,
    "default_capital_currency": "USD",
    "broker": "サクソバンク証券",
    "setup_done": False,
}

@st.cache_data(ttl=3600)
def get_fx_rate():
    """USD/JPY レートを取得（失敗時は150を返す）"""
    try:
        fx = yf.Ticker("USDJPY=X")
        rate = fx.fast_info.get("lastPrice") or fx.history(period="1d")['Close'].iloc[-1]
        return float(rate)
    except Exception:
        return 150.0

def usd_to_jpy(usd_amount, rate):
    return int(usd_amount * rate)

def jpy_to_usd(jpy_amount, rate):
    return jpy_amount / rate

def capital_input_with_currency(label, default_usd, key_prefix, rate):
    """円/ドル切り替え対応の軍資金入力UI。戻り値は常にUSD（float）"""
    cur_col, amt_col = st.columns([1, 3])
    with cur_col:
        currency = st.selectbox("通貨", ["USD（ドル）", "JPY（円）"],
                                key=f"{key_prefix}_currency", label_visibility="collapsed")
    with amt_col:
        if "JPY" in currency:
            default_jpy = usd_to_jpy(default_usd, rate)
            # 1万円単位で丸める
            default_jpy = max(10000, (default_jpy // 10000) * 10000)
            jpy_val = st.number_input(label, value=default_jpy, step=10000,
                                      min_value=10000, key=f"{key_prefix}_amount",
                                      format="%d")
            usd_val = jpy_to_usd(jpy_val, rate)
            st.caption(f"≈ ${usd_val:,.0f}　（1ドル＝{rate:.1f}円）")
        else:
            usd_val = st.number_input(label, value=default_usd, step=500,
                                      min_value=200, key=f"{key_prefix}_amount",
                                      format="%d")
            jpy_val = usd_to_jpy(usd_val, rate)
            st.caption(f"≈ {jpy_val:,}円　（1ドル＝{rate:.1f}円）")
    return float(usd_val), currency

def get_personality_type(profile):
    """プロフィールから投資パーソナリティを判定"""
    risk = profile.get("risk_tolerance", "バランス重視")
    exp = profile.get("experience", "未経験")
    age = profile.get("age_group", "30代")
    goal = profile.get("investment_goal", "副収入を得たい")
    if risk == "低リスク重視" or age in ["60代以上"] or exp == "未経験" or goal == "資産を守りたい":
        return "conservative"
    elif risk == "高リターン重視" and exp in ["1〜3年", "3年以上"]:
        return "aggressive"
    else:
        return "balanced"

PERSONALITY_LABELS = {
    "conservative": ("🛡️ 保守型", "#276749", "#f0fff4"),
    "balanced":     ("⚖️ バランス型", "#2b6cb0", "#ebf8ff"),
    "aggressive":   ("🚀 積極型", "#c53030", "#fff5f5"),
}

PERSONALITY_STRATEGY_HINT = {
    "conservative": "リスクを抑えながら安定的にプレミアムを受け取る売り戦略（カバードコール・プット売り）が向いています。",
    "balanced":     "状況に応じて売り・買い両方を使い分けるバランス型の戦略が向いています。",
    "aggressive":   "方向性に賭けてリターンを最大化するコール/プット買いが向いています。少額から積極的に動けます。",
}

def load_profile(local_storage):
    """localStorageからプロフィールを読み込む"""
    if not _local_storage_available or local_storage is None:
        return dict(DEFAULT_PROFILE)
    try:
        raw = local_storage.getItem("user_profile")
        if raw and isinstance(raw, dict):
            merged = dict(DEFAULT_PROFILE)
            merged.update(raw)
            return merged
        if raw and isinstance(raw, str):
            parsed = json.loads(raw)
            merged = dict(DEFAULT_PROFILE)
            merged.update(parsed)
            return merged
    except Exception:
        pass
    return dict(DEFAULT_PROFILE)

def save_profile(local_storage, profile):
    """localStorageにプロフィールを保存する"""
    if not _local_storage_available or local_storage is None:
        return
    try:
        local_storage.setItem("user_profile", profile)
    except Exception:
        pass

# ========== 定数 ==========
QQQ_TOP30 = [
    "MSFT", "AAPL", "NVDA", "AMZN", "META",
    "TSLA", "GOOGL", "GOOG", "AVGO", "COST",
    "NFLX", "AMD", "ADBE", "QCOM", "INTC",
    "INTU", "CSCO", "PEP", "AMAT", "TXN",
    "SBUX", "ISRG", "MU", "LRCX", "KLAC",
    "MRVL", "PANW", "SNPS", "CDNS", "ASML"
]

SP500_TOP30 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "TSLA", "BRK-B", "JPM", "V", "UNH",
    "XOM", "MA", "JNJ", "PG", "HD",
    "GOOGL", "CVX", "MRK", "ABBV", "PEP",
    "KO", "BAC", "WMT", "LLY", "COST",
    "TMO", "MCD", "CRM", "ACN", "ORCL"
]

CAPITAL_TIERS = {
    "超少額（$500〜$2,000）": {"min": 500, "max": 2000},
    "少額（$2,000〜$5,000）": {"min": 2000, "max": 5000},
    "中額（$5,000〜$15,000）": {"min": 5000, "max": 15000},
    "標準（$15,000〜$30,000）": {"min": 15000, "max": 30000},
    "大口（$30,000〜）": {"min": 30000, "max": 9999999},
}

TICKER_MAP = {
    "アップル": "AAPL", "apple": "AAPL",
    "テスラ": "TSLA", "tesla": "TSLA",
    "エヌビディア": "NVDA", "nvidia": "NVDA",
    "マイクロソフト": "MSFT", "microsoft": "MSFT",
    "アマゾン": "AMZN", "amazon": "AMZN",
    "グーグル": "GOOGL", "google": "GOOGL",
    "メタ": "META", "meta": "META",
    "スパイ": "SPY", "spy": "SPY",
    "qqq": "QQQ", "インテル": "INTC", "intel": "INTC",
    "エーエムディー": "AMD", "amd": "AMD",
    "コストコ": "COST", "costco": "COST",
}

GLOSSARY = {
    "IV（インプライドボラティリティ）": "オプションの値段に織り込まれた『将来の価格変動予測』。高いほどオプションが割高。",
    "HV（ヒストリカルボラティリティ）": "過去30日の実際の株価変動の大きさ。IVと比較して割安・割高を判断する基準。",
    "CSP（キャッシュセキュアードプット）": "『この株を〇〇ドルで買う権利を売る』戦略。株価が下がらなければプレミアムがそのまま利益になる。",
    "デビットスプレッド": "2つのオプションを組み合わせて、少ない資金で方向性に賭ける戦略。最大損失が決まっているので安心。",
    "クレジットスプレッド": "2つのオプションを売買してプレミアムを受け取る戦略。相場がある程度動かなければ利益になる。",
    "プレミアム": "オプションの値段のこと。売り戦略では受け取り、買い戦略では支払う。",
    "ストライク価格": "オプションで決めた『約束の株価』。例：$380のストライク＝株価が$380になった時に権利が発生。",
    "満期日": "オプションの有効期限。この日までに株価がどう動くかで損益が決まる。",
    "ATM（アット・ザ・マネー）": "現在の株価に最も近いストライク価格のこと。",
}

# ========== ページ設定 ==========
st.set_page_config(
    page_title="オプションAIナビ | 米国株オプション取引支援",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ========== LocalStorage 初期化 ==========
_ls = None
if _local_storage_available:
    try:
        _ls = LocalStorage()
    except Exception:
        _ls = None

# セッション内プロフィールキャッシュ（再描画ごとに読み直さないように）
if "profile" not in st.session_state:
    st.session_state.profile = load_profile(_ls)

profile = st.session_state.profile
personality = get_personality_type(profile)

# ========== カスタムCSS ==========
st.markdown("""
<style>
/* フォント・背景 */
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700;900&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans JP', sans-serif; }

/* ヒーローセクション */
.hero {
    background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
    border-radius: 20px;
    padding: 48px 40px;
    text-align: center;
    margin-bottom: 32px;
}
.hero h1 {
    color: #ffffff;
    font-size: 2.6rem;
    font-weight: 900;
    margin-bottom: 12px;
    letter-spacing: -0.5px;
}
.hero p {
    color: #b0c4d8;
    font-size: 1.1rem;
    margin-bottom: 0;
    line-height: 1.8;
}
.hero .badge {
    display: inline-block;
    background: rgba(255,255,255,0.15);
    color: #fff;
    border-radius: 20px;
    padding: 4px 16px;
    font-size: 0.8rem;
    margin-bottom: 16px;
    letter-spacing: 1px;
}

/* 機能カード */
.feature-card {
    background: #f8faff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 24px;
    text-align: center;
    height: 100%;
}
.feature-card .icon { font-size: 2.2rem; margin-bottom: 10px; }
.feature-card h3 { font-size: 1rem; font-weight: 700; color: #1a202c; margin-bottom: 8px; }
.feature-card p { font-size: 0.85rem; color: #718096; line-height: 1.6; margin: 0; }

/* チャンスカード */
.chance-card {
    background: #ffffff;
    border: 2px solid #e2e8f0;
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 16px;
    transition: box-shadow 0.2s;
}
.chance-card:hover { box-shadow: 0 8px 24px rgba(0,0,0,0.08); }
.chance-card.sell { border-left: 5px solid #e53e3e; }
.chance-card.buy  { border-left: 5px solid #38a169; }
.chance-card.wait { border-left: 5px solid #d69e2e; }

/* No.1バッジ */
.rank-badge {
    display: inline-block;
    background: linear-gradient(135deg, #f6d365, #fda085);
    color: #fff;
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 8px;
}

/* シグナルバッジ */
.signal-sell { background:#fff5f5; color:#c53030; border:1px solid #fc8181; border-radius:8px; padding:4px 12px; font-size:0.85rem; font-weight:700; }
.signal-buy  { background:#f0fff4; color:#276749; border:1px solid #68d391; border-radius:8px; padding:4px 12px; font-size:0.85rem; font-weight:700; }
.signal-wait { background:#fffff0; color:#744210; border:1px solid #f6e05e; border-radius:8px; padding:4px 12px; font-size:0.85rem; font-weight:700; }

/* メトリクス */
.metric-box {
    background: #f7fafc;
    border-radius: 12px;
    padding: 16px;
    text-align: center;
}
.metric-box .label { font-size: 0.75rem; color: #718096; margin-bottom: 4px; }
.metric-box .value { font-size: 1.4rem; font-weight: 700; color: #1a202c; }

/* セクションタイトル */
.section-title {
    font-size: 1.3rem;
    font-weight: 700;
    color: #1a202c;
    border-left: 4px solid #4299e1;
    padding-left: 12px;
    margin: 28px 0 16px 0;
}

/* ステップバッジ */
.step { display:inline-block; background:#ebf8ff; color:#2b6cb0; border-radius:50%; width:28px; height:28px; line-height:28px; text-align:center; font-weight:700; font-size:0.85rem; margin-right:8px; }

/* ボタン上書き */
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #4299e1, #3182ce);
    border: none;
    border-radius: 12px;
    font-size: 1rem;
    font-weight: 700;
    padding: 12px 24px;
    color: white;
    transition: opacity 0.2s;
}
div.stButton > button[kind="primary"]:hover { opacity: 0.9; }

/* タブ */
button[data-baseweb="tab"] {
    font-size: 1rem !important;
    font-weight: 600 !important;
    padding: 12px 24px !important;
}

/* フッター非表示 */
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ========== ヘルパー関数 ==========
def calc_min_capital(price):
    if price < 30:    return 150
    elif price < 60:  return 300
    elif price < 100: return 500
    elif price < 200: return 800
    elif price < 400: return 1500
    elif price < 800: return 3000
    else:             return 5000

def calc_csp_capital(price):
    return int(price * 100)

def get_capital_label(min_cap):
    if min_cap <= 300:    return "💚 超少額OK"
    elif min_cap <= 800:  return "🟡 少額OK"
    elif min_cap <= 1500: return "🟠 中額向け"
    else:                 return "🔴 大口向け"

def get_strategy_for_capital(capital, price, signal):
    min_cap = calc_min_capital(price)
    csp_cap = calc_csp_capital(price)
    if capital < min_cap:
        return "資金不足（対象外）", None
    if "売り" in signal:
        if capital >= csp_cap and price < 100:
            return "CSP（現金確保プット）", csp_cap
        elif capital >= min_cap * 2:
            return "クレジットプットスプレッド", min_cap
        else:
            return "クレジットプットスプレッド（狭め）", min_cap
    else:
        if capital >= min_cap * 3:
            return "デビットコールスプレッド（余裕あり）", min_cap
        else:
            return "デビットコールスプレッド", min_cap

# 初心者向け5戦略マッピング
BEGINNER_STRATEGIES = {
    "covered_call": {
        "name": "コール売り（カバードコール）",
        "emoji": "📤",
        "tag": "安定収入型",
        "desc": "すでに100株持っている方向け。株を持ちながら「上値の権利」を売って毎月コツコツプレミアムを受け取る戦略。",
        "risk": "株価が権利行使価格を超えると利益が上限になる",
        "required": "対象銘柄の株を100株保有していること",
    },
    "csp": {
        "name": "プット売り（100株購入あり・CSP）",
        "emoji": "💵",
        "tag": "株を安く買いたい方向け",
        "desc": "「この株を〇〇ドルで買います」と約束してプレミアムを先に受け取る戦略。株価が下がらなければそのまま利益。下がっても買いたい株ならOK。",
        "risk": "株価が大幅下落すると100株を高値で買わされる",
        "required": "100株分の購入資金（株価×100ドル）",
    },
    "otm_put_sell": {
        "name": "プット売り（100株購入なし・OTM遠め）",
        "emoji": "🎯",
        "tag": "プレミアムだけ受け取る戦略",
        "desc": "現在の株価から大きく離れた（10〜20%下の）ストライクのプットを売る。株が多少下がってもOKな余裕のある場所を狙い、プレミアムを受け取る。プレミアムが半分になった時点で反対売買（買い戻し）して利確。100株購入は不要。",
        "risk": "株が急落してストライクを大きく下回ると損失が膨らむ（損切りルール厳守）",
        "required": "証拠金（ブローカーによる。数千ドル程度）",
    },
    "call_buy": {
        "name": "コール買い（爆益戦略 その1）🚀",
        "emoji": "🚀",
        "tag": "上昇を狙う・ハイリスクハイリターン",
        "desc": "株が上がると予想したときに、少ない資金で大きな利益を狙う戦略。RSI・移動平均が上昇トレンドを示しているときに有効。当たれば数倍になることも。",
        "risk": "株が上がらなければ投資額がゼロになる（買ったプレミアム全額損失）",
        "required": "数百〜数千ドル（プレミアム×100）",
    },
    "put_buy": {
        "name": "プット買い（爆益戦略 その2）📉",
        "emoji": "📉",
        "tag": "下落を狙う・ハイリスクハイリターン",
        "desc": "株が下がると予想したときに使う戦略。RSI・移動平均が下落トレンドを示しているときに有効。暴落局面では数倍〜数十倍になることも。",
        "risk": "株が下がらなければ投資額がゼロになる（買ったプレミアム全額損失）",
        "required": "数百〜数千ドル（プレミアム×100）",
    },
}

def calc_technical_direction(hist):
    """RSI・移動平均線から方向性を判定する（上昇/下落/中立）"""
    if hist is None or len(hist) < 20:
        return "neutral", 50, None, None

    close = hist['Close']

    # 移動平均
    ma5  = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    current = close.iloc[-1]

    # RSI（14日）
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, 1e-10)
    rsi   = float(100 - 100 / (1 + rs.iloc[-1]))

    # 直近5日のモメンタム（%）
    momentum = float((current - close.iloc[-5]) / close.iloc[-5] * 100) if len(close) >= 5 else 0

    # 判定
    bullish_score = 0
    if current > ma5:   bullish_score += 1
    if ma5 > ma20:      bullish_score += 1
    if rsi > 55:        bullish_score += 1
    if momentum > 1:    bullish_score += 1

    bearish_score = 0
    if current < ma5:   bearish_score += 1
    if ma5 < ma20:      bearish_score += 1
    if rsi < 45:        bearish_score += 1
    if momentum < -1:   bearish_score += 1

    if bullish_score >= 3:
        direction = "bullish"
    elif bearish_score >= 3:
        direction = "bearish"
    else:
        direction = "neutral"

    return direction, round(rsi, 1), round(float(ma5), 2), round(float(ma20), 2)

def get_beginner_strategy(signal, owns_stock, wants_100_shares, direction="neutral"):
    """初心者モード用：5戦略から最適なものを返す"""
    if "売り" in signal:
        if owns_stock:
            return "covered_call"
        elif wants_100_shares:
            return "csp"
        else:
            return "otm_put_sell"
    elif "買い" in signal or "様子見" in signal:
        # 方向性で分岐
        if direction == "bearish":
            return "put_buy"
        else:
            return "call_buy"
    else:
        return "call_buy"

def build_broker_steps(ticker, expiry, price, broker_is_saxo, is_beginner_mode):
    if broker_is_saxo:
        steps = f"""
### 🏦 サクソバンク証券での注文手順

**【ステップ1】** サクソバンクにログイン（PC: saxotrader.com / スマホ: SaxoTraderGOアプリ）

**【ステップ2】** 検索バーに **{ticker}** と入力 → 「オプション」タブを選択

**【ステップ3】** 満期日 **{expiry}** を選択 → 現在株価 **${price:.2f}** 付近のストライクを探す

**【ステップ4】** 注文入力（数量: 1枚から）→ 確認 → 送信
"""
        if is_beginner_mode:
            steps += "\n> 💡 **初心者メモ**: サクソバンクは「オプション取引」の申請が必要な場合があります。"
    else:
        steps = f"""
### 📱 moomoo証券での注文手順

**【ステップ1】** moomooアプリを起動

**【ステップ2】** 下のメニュー「マーケット」→ 検索に **{ticker}** と入力

**【ステップ3】** 銘柄ページ上部「オプション」タップ → 満期日 **{expiry}** → 現在株価 **${price:.2f}** 付近のストライクを選択

**【ステップ4】** 数量入力（1枚から）→ 注文確認 → 送信
"""
        if is_beginner_mode:
            steps += "\n> 💡 **初心者メモ**: moomooは「高度な取引」設定をONにしないとオプションが表示されない場合があります。"
    return steps

@st.cache_data(ttl=3600)
def scan_ticker(ticker):
    errors = []
    for attempt in range(3):
        try:
            stock = yf.Ticker(ticker)
            try:
                fi = stock.fast_info
                price = fi.get('lastPrice') or fi.get('regularMarketPrice')
            except Exception:
                price = None
            if not price:
                try:
                    info = stock.info
                    price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
                    name = info.get('shortName', ticker)
                except Exception:
                    price = None; name = ticker
            else:
                try: name = stock.info.get('shortName', ticker)
                except: name = ticker

            hist = stock.history(period='30d')
            if hist.empty:
                errors.append(f"{ticker}: 株価履歴なし"); time.sleep(1); continue
            if not price:
                price = float(hist['Close'].iloc[-1])
            returns = hist['Close'].pct_change().dropna()
            if len(returns) < 5:
                errors.append(f"{ticker}: データ不足"); continue
            hv = float(returns.std() * (252 ** 0.5))

            # テクニカル指標
            direction, rsi, ma5, ma20 = calc_technical_direction(hist)

            try: expirations = stock.options
            except Exception as e:
                errors.append(f"{ticker}: オプション取得失敗"); time.sleep(1); continue
            if not expirations:
                errors.append(f"{ticker}: オプション満期日なし"); continue

            target_exp = None
            preferred_min_days = 20
            for exp in expirations:
                days = (datetime.strptime(exp, '%Y-%m-%d') - datetime.now()).days
                if days >= preferred_min_days:
                    target_exp = exp; break
            if not target_exp:
                errors.append(f"{ticker}: 20日以上先の満期日なし"); continue

            # 複数満期日のプレミアムを取得（30/60/90/180日）
            expiry_premiums = {}
            for exp in expirations:
                days = (datetime.strptime(exp, '%Y-%m-%d') - datetime.now()).days
                for label, lo, hi in [("30日",20,45),("60日",46,75),("90日",76,120),("180日",121,200)]:
                    if lo <= days <= hi and label not in expiry_premiums:
                        try:
                            oc = stock.option_chain(exp)
                            if not oc.calls.empty and not oc.puts.empty:
                                oc.calls['distance'] = abs(oc.calls['strike'] - price)
                                oc.puts['distance']  = abs(oc.puts['strike']  - price)
                                c_atm = oc.calls.nsmallest(1,'distance').iloc[0]
                                p_atm = oc.puts.nsmallest(1,'distance').iloc[0]
                                expiry_premiums[label] = {
                                    'expiry': exp,
                                    'days': days,
                                    'call_premium': float(c_atm['lastPrice']),
                                    'put_premium':  float(p_atm['lastPrice']),
                                    'strike':       float(c_atm['strike']),
                                }
                        except Exception:
                            pass

            opt = stock.option_chain(target_exp)
            puts, calls = opt.puts, opt.calls
            if puts.empty or 'impliedVolatility' not in puts.columns:
                errors.append(f"{ticker}: プットデータなし"); continue

            puts['distance'] = abs(puts['strike'] - price)
            atm_puts = puts.nsmallest(3, 'distance')
            iv = float(atm_puts['impliedVolatility'].mean())

            atm_call_premium = None
            if not calls.empty:
                calls['distance'] = abs(calls['strike'] - price)
                atm_calls = calls.nsmallest(3, 'distance')
                atm_call_premium = float(atm_calls.iloc[0]['lastPrice']) if len(atm_calls) > 0 else None

            iv_hv_ratio = iv / hv if hv > 0 else 1.0
            if iv_hv_ratio > 1.3 and iv > 0.25:
                signal = "売りチャンス🔥"; strategy = "CSP or クレジットスプレッド"; score = iv_hv_ratio * iv * 100
            elif iv_hv_ratio < 0.8 and hv > 0.25:
                signal = "買いチャンス💡"; strategy = "デビットスプレッド"; score = (1 / iv_hv_ratio) * hv * 100
            elif iv > 0.35:
                signal = "売りチャンス🔥"; strategy = "アイアンコンドル"; score = iv * 80
            else:
                signal = "様子見👀"; strategy = "エントリー見送り"; score = 10

            min_cap = calc_min_capital(price)
            return {
                'ticker': ticker, 'name': name, 'price': price,
                'iv': iv, 'hv': hv, 'iv_hv_ratio': iv_hv_ratio,
                'signal': signal, 'strategy': strategy, 'score': score,
                'expiry': target_exp,
                'atm_put_strike': float(atm_puts.iloc[0]['strike']) if len(atm_puts) > 0 else None,
                'atm_put_premium': float(atm_puts.iloc[0]['lastPrice']) if len(atm_puts) > 0 else None,
                'atm_call_premium': atm_call_premium,
                'min_capital': min_cap, 'csp_capital': calc_csp_capital(price),
                'capital_label': get_capital_label(min_cap),
                'direction': direction, 'rsi': rsi, 'ma5': ma5, 'ma20': ma20,
                'expiry_premiums': expiry_premiums,
            }
        except Exception as e:
            errors.append(f"{ticker}: {type(e).__name__}: {e}"); time.sleep(1 + attempt)
    return {'_error': True, 'ticker': ticker, 'reason': ' | '.join(errors)}

@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        result = {
            'price': info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose'),
            'company_name': info.get('shortName', ticker),
            'sector': info.get('sector', '不明'),
            'week52_high': info.get('fiftyTwoWeekHigh'),
            'week52_low': info.get('fiftyTwoWeekLow'),
            'iv': None, 'historical_volatility': None,
        }
        hist = stock.history(period='30d')
        if not hist.empty:
            returns = hist['Close'].pct_change().dropna()
            result['historical_volatility'] = returns.std() * (252 ** 0.5)
            if not result['price']:
                result['price'] = float(hist['Close'].iloc[-1])
            direction, rsi, ma5, ma20 = calc_technical_direction(hist)
            result['direction'] = direction
            result['rsi'] = rsi
            result['ma5'] = ma5
            result['ma20'] = ma20

        expirations = stock.options
        result['expirations'] = list(expirations[:8]) if expirations else []
        best_expiry = None
        for exp in expirations:
            if datetime.strptime(exp, '%Y-%m-%d') > datetime.now() + timedelta(days=20):
                best_expiry = exp; break

        if best_expiry:
            result['target_expiry'] = best_expiry
            opt = stock.option_chain(best_expiry)
            puts, calls = opt.puts, opt.calls
            if not puts.empty and 'impliedVolatility' in puts.columns and result['price']:
                puts['distance'] = abs(puts['strike'] - result['price'])
                atm_puts = puts.nsmallest(10, 'distance')
                result['puts_sample'] = atm_puts[['strike','lastPrice','impliedVolatility','volume','openInterest']].to_string()
                result['put_iv_avg'] = atm_puts['impliedVolatility'].mean()
                result['put_iv_atm'] = atm_puts.iloc[0]['impliedVolatility'] if len(atm_puts) > 0 else None
            if not calls.empty and 'impliedVolatility' in calls.columns and result['price']:
                calls['distance'] = abs(calls['strike'] - result['price'])
                atm_calls = calls.nsmallest(10, 'distance')
                result['calls_sample'] = atm_calls[['strike','lastPrice','impliedVolatility','volume','openInterest']].to_string()
                result['call_iv_avg'] = atm_calls['impliedVolatility'].mean()
            if result.get('put_iv_avg') and result.get('call_iv_avg'):
                result['iv'] = (result['put_iv_avg'] + result['call_iv_avg']) / 2
        result['status'] = '成功'
        return result, None
    except Exception as e:
        return None, str(e)

# ========== ヒーローセクション ==========
st.markdown(f"""
<div class="hero">
    <div class="badge">AI POWERED · REAL TIME</div>
    <h1>📈 オプションAIナビ</h1>
    <p>米国株オプション取引を、AIがリアルタイムで分析。<br>
    今日どの銘柄を・どんな戦略で・いくらで入るかを自動で提案します。</p>
</div>
""", unsafe_allow_html=True)

# ========== 機能説明カード ==========
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("""
    <div class="feature-card">
        <div class="icon">🔍</div>
        <h3>チャンス銘柄スキャナー</h3>
        <p>QQQ・S&P500の30銘柄を一括スキャン。<br>今日のチャンス銘柄を自動で発見します。</p>
    </div>
    """, unsafe_allow_html=True)
with c2:
    st.markdown("""
    <div class="feature-card">
        <div class="icon">📊</div>
        <h3>作戦ナビ（個別分析）</h3>
        <p>気になる銘柄を入力するだけ。<br>具体的な注文内容をAIが提案します。</p>
    </div>
    """, unsafe_allow_html=True)
with c3:
    st.markdown("""
    <div class="feature-card">
        <div class="icon">🤖</div>
        <h3>Claude AI 分析レポート</h3>
        <p>初心者にもわかりやすく解説。<br>軍資金・証券会社に合わせた提案をします。</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ========== よくある質問（FAQ） ==========
st.markdown("""
<div style="background:#f7fafc;border-radius:16px;padding:28px 32px;margin-bottom:24px;">
    <div style="font-size:1.15rem;font-weight:700;color:#2d3748;margin-bottom:20px;">❓ 初心者がよく聞く質問</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;">
        <div style="background:#ffffff;border-radius:12px;padding:18px 20px;border:1px solid #e2e8f0;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
            <div style="font-weight:700;color:#2b6cb0;margin-bottom:8px;">💰 いくら必要ですか？</div>
            <div style="font-size:0.88rem;color:#4a5568;line-height:1.7;">
                <strong>コール/プット買い</strong>なら <strong style="color:#2b6cb0;">$200〜$500</strong> から始められます（プレミアム代のみ）。<br><br>
                <strong>プット売り（CSP）</strong>は株価×100株分の担保が必要なので、例えばAPPLなら約 <strong style="color:#e53e3e;">$18,000〜</strong>。<br><br>
                まずは <strong>コール/プット買いで小額からスタート</strong> するのが初心者向けです。
            </div>
        </div>
        <div style="background:#ffffff;border-radius:12px;padding:18px 20px;border:1px solid #e2e8f0;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
            <div style="font-weight:700;color:#276749;margin-bottom:8px;">🌱 少額でもできますか？</div>
            <div style="font-size:0.88rem;color:#4a5568;line-height:1.7;">
                <strong>はい、できます！</strong><br><br>
                <strong style="color:#276749;">$200〜$500</strong> あれば「コール買い」「プット買い」が可能です。<br><br>
                安い株（例：インテルなど）のオプションなら <strong>$50〜$100</strong> 程度のプレミアムもあります。下のスキャナーで実際の金額を確認してください。
            </div>
        </div>
        <div style="background:#ffffff;border-radius:12px;padding:18px 20px;border:1px solid #e2e8f0;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
            <div style="font-weight:700;color:#744210;margin-bottom:8px;">📚 株をやったことなくても大丈夫？</div>
            <div style="font-size:0.88rem;color:#4a5568;line-height:1.7;">
                <strong>大丈夫です！</strong><br><br>
                このアプリの <strong>🔰 初心者モード</strong> を使えば、AIが「どの銘柄を・どんな戦略で・いくらで入るか」を具体的に提案します。<br><br>
                まずは <strong>少額のコール/プット買い</strong> から体験してみましょう。
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ========== プロフィールバナー（設定済みの場合のみ表示） ==========
if profile.get("setup_done"):
    p_label, p_color, p_bg = PERSONALITY_LABELS[personality]
    p_name = profile.get("name", "")
    p_greeting = f"こんにちは、{p_name}さん！" if p_name else "プロフィール設定済み"
    st.markdown(f"""
    <div style="background:{p_bg};border:1.5px solid {p_color};border-radius:12px;padding:12px 20px;margin-bottom:16px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
        <div style="font-size:1.1rem;font-weight:700;color:{p_color};">{p_label}</div>
        <div style="color:#4a5568;font-size:0.9rem;">{p_greeting}　|　{PERSONALITY_STRATEGY_HINT[personality]}</div>
        <div style="margin-left:auto;font-size:0.8rem;color:#718096;">✏️ プロフィール変更は「👤 マイプロフィール」タブから</div>
    </div>
    """, unsafe_allow_html=True)

# ========== タブ ==========
tab1, tab2, tab3 = st.tabs(["　🔍 チャンス銘柄スキャナー　", "　📊 作戦ナビ（個別銘柄）　", "　👤 マイプロフィール　"])

# ==================== TAB 1: スキャナー ====================
with tab1:

    # 設定パネル
    st.markdown('<div class="section-title">⚙️ スキャン設定</div>', unsafe_allow_html=True)
    col_mode, col_broker = st.columns(2)
    with col_mode:
        mode = st.radio("表示モード", ["🔰 初心者モード", "📊 上級者モード"], horizontal=True, key="scan_mode")
    with col_broker:
        broker = st.radio("証券会社", ["🏦 サクソバンク証券", "📱 moomoo証券"], horizontal=True, key="scan_broker")

    is_beginner = "初心者" in mode
    is_saxo = "サクソバンク" in broker

    col1, col3 = st.columns([2, 1])
    with col1:
        universe = st.selectbox("対象ユニバース", ["QQQ上位30銘柄", "S&P500代表30銘柄"])
    with col3:
        top_n = st.number_input("表示する上位銘柄数", value=5, min_value=3, max_value=10)

    fx_rate = get_fx_rate()
    scan_default_usd = int(st.session_state.profile.get("default_capital", 5000))
    st.markdown("**💰 軍資金**")
    capital, scan_currency = capital_input_with_currency("軍資金", scan_default_usd, "scan_capital", fx_rate)
    capital = int(capital)

    # 軍資金ガイド
    tier_label = next((n for n, t in CAPITAL_TIERS.items() if t["min"] <= capital < t["max"]), "")
    if tier_label:
        st.info(f"💼 **{tier_label}** の軍資金で使える戦略のみ表示します")

    # 初心者モード：戦略の追加質問
    owns_stock = False
    wants_100_shares = False
    if is_beginner:
        st.markdown('<div class="section-title">📋 あなたに合った戦略を選びます</div>', unsafe_allow_html=True)

        # 4戦略の説明カード
        s = BEGINNER_STRATEGIES
        st.markdown(f"""
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
            <div style="background:#fff5f5;border:1px solid #fed7d7;border-radius:12px;padding:16px;">
                <div style="font-weight:700;color:#c53030;">{s['covered_call']['emoji']} {s['covered_call']['name']}</div>
                <div style="font-size:0.8rem;color:#718096;margin-top:4px;">{s['covered_call']['desc']}</div>
            </div>
            <div style="background:#fff5f5;border:1px solid #fed7d7;border-radius:12px;padding:16px;">
                <div style="font-weight:700;color:#c53030;">{s['csp']['emoji']} {s['csp']['name']}</div>
                <div style="font-size:0.8rem;color:#718096;margin-top:4px;">{s['csp']['desc']}</div>
            </div>
            <div style="background:#fff5f5;border:1px solid #fed7d7;border-radius:12px;padding:16px;">
                <div style="font-weight:700;color:#c53030;">{s['otm_put_sell']['emoji']} {s['otm_put_sell']['name']}</div>
                <div style="font-size:0.8rem;color:#718096;margin-top:4px;">{s['otm_put_sell']['desc']}</div>
            </div>
            <div style="background:#f0fff4;border:1px solid #c6f6d5;border-radius:12px;padding:16px;">
                <div style="font-weight:700;color:#276749;">{s['call_buy']['emoji']} {s['call_buy']['name']}</div>
                <div style="font-size:0.8rem;color:#718096;margin-top:4px;">{s['call_buy']['desc']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        q1 = st.radio(
            "対象銘柄の株を100株すでに持っていますか？",
            ["いいえ（持っていない）", "はい（持っている）"],
            horizontal=True, key="owns_stock"
        )
        owns_stock = "はい" in q1

        if not owns_stock:
            q2 = st.radio(
                "プット売りの場合、100株を購入してもよいですか？（資金が株価×100ドル必要です）",
                ["いいえ（100株は購入したくない / できない）", "はい（100株を購入してもよい）"],
                horizontal=True, key="wants_100"
            )
            wants_100_shares = "はい" in q2

        exp_window = st.select_slider(
            "📅 満期日の目安（何日後を狙う？）",
            options=["30日", "60日", "90日", "180日"],
            value="60日",
            key="exp_window_scan"
        )
        st.caption("短い満期日ほど動きが速くハイリスク・ハイリターン。長い満期日ほど余裕があり初心者向けです。")
    else:
        exp_window = "60日"

    st.markdown("<br>", unsafe_allow_html=True)
    scan_btn = st.button("🔍 今日のチャンス銘柄をスキャンする", type="primary", use_container_width=True)

    if scan_btn:
        tickers = QQQ_TOP30 if "QQQ" in universe else SP500_TOP30
        st.markdown('<div class="section-title">📡 スキャン中...</div>', unsafe_allow_html=True)
        progress = st.progress(0)
        status = st.empty()

        results, errors = [], []
        for i, ticker in enumerate(tickers):
            status.text(f"分析中: {ticker}  ({i+1}/{len(tickers)})")
            r = scan_ticker(ticker)
            if r and not r.get('_error'):
                results.append(r)
            elif r and r.get('_error'):
                errors.append(f"{r['ticker']}: {r['reason']}")
            progress.progress((i + 1) / len(tickers))
            time.sleep(0.3)

        progress.empty()
        status.empty()

        if not results:
            st.error("データを取得できませんでした。しばらく待ってから再スキャンしてください。")
            if errors:
                with st.expander("詳細エラー情報"):
                    for e in errors[:10]: st.write(e)
            st.stop()

        df = pd.DataFrame(results).sort_values('score', ascending=False)
        df_affordable = df[df['min_capital'] <= capital].copy()
        df_toomuch = df[df['min_capital'] > capital].copy()

        # 完了サマリー
        st.success(f"✅ スキャン完了！ {len(results)}銘柄を分析 → 軍資金 ${capital:,} で **{len(df_affordable)}銘柄** が対象")

        # ========== No.1 ハイライト ==========
        st.markdown('<div class="section-title">🏆 今日の最注目銘柄</div>', unsafe_allow_html=True)
        top_df = df_affordable[~df_affordable['signal'].str.contains('様子見')] if not df_affordable.empty else df
        if not top_df.empty:
            top = top_df.iloc[0]
            signal_class = "sell" if "売り" in top['signal'] else ("buy" if "買い" in top['signal'] else "wait")
            signal_html = f'<span class="signal-sell">{top["signal"]}</span>' if "売り" in top['signal'] else (f'<span class="signal-buy">{top["signal"]}</span>' if "買い" in top['signal'] else f'<span class="signal-wait">{top["signal"]}</span>')
            if is_beginner:
                top_dir = top.get('direction', 'neutral')
                bkey = get_beginner_strategy(top['signal'], owns_stock, wants_100_shares, top_dir)
                bstrat = BEGINNER_STRATEGIES[bkey]
                strategy_name = f"{bstrat['emoji']} {bstrat['name']}"
                dir_label = {"bullish":"📈 上昇トレンド","bearish":"📉 下落トレンド","neutral":"➡️ 方向感なし"}.get(top_dir,"")
                rsi_val = top.get('rsi', '')
                # プレミアム表示
                ep = top.get('expiry_premiums', {})
                ep_data = ep.get(exp_window, {})
                is_buy = bkey in ("call_buy", "put_buy")
                if ep_data:
                    prem_val = ep_data.get('call_premium' if bkey in ('covered_call','call_buy') else 'put_premium', 0)
                    prem_per_contract = prem_val * 100
                    prem_html = f'<div><div style="font-size:0.75rem;color:#718096;">{"支払う" if is_buy else "受け取る"}プレミアム（1枚）</div><strong style="font-size:1.3rem;color:{"#2b6cb0" if is_buy else "#276749"};">${prem_per_contract:,.0f}</strong><span style="font-size:0.75rem;color:#718096;">（満期{exp_window}）</span></div>'
                    exp_show = ep_data.get('expiry', top['expiry'])
                    strike_html = f'<div><div style="font-size:0.75rem;color:#718096;">ATMストライク</div><strong style="font-size:1.1rem;">${ep_data.get("strike",0):.1f}</strong></div>'
                else:
                    prem_html = ""
                    exp_show = top['expiry']
                    strike_html = ""
                strategy_note = f'<div style="font-size:0.82rem;color:#555;margin-top:8px;background:#f7fafc;border-radius:8px;padding:8px 12px;">📌 {bstrat["desc"]}<br>⚠️ リスク: {bstrat["risk"]}<br>🔎 テクニカル: {dir_label}{"（RSI: "+str(rsi_val)+"）" if rsi_val else ""}</div>'
            else:
                strategy_name, _ = get_strategy_for_capital(capital, top['price'], top['signal'])
                strategy_note = ""
                prem_html = ""
                exp_show = top['expiry']
                strike_html = ""
            st.markdown(f"""
            <div class="chance-card {signal_class}">
                <div class="rank-badge">🥇 本日 No.1 チャンス銘柄</div><br>
                <strong style="font-size:1.5rem;">{top['ticker']}</strong>
                <span style="color:#718096; margin-left:8px;">{top['name']}</span>
                &nbsp;&nbsp;{signal_html}
                <hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0;">
                <div style="display:flex;gap:32px;flex-wrap:wrap;">
                    <div><div style="font-size:0.75rem;color:#718096;">株価</div><strong style="font-size:1.3rem;">${top['price']:.2f}</strong></div>
                    {prem_html if is_beginner else f'<div><div style="font-size:0.75rem;color:#718096;">IV</div><strong style="font-size:1.3rem;">{top["iv"]:.1%}</strong></div><div><div style="font-size:0.75rem;color:#718096;">HV</div><strong style="font-size:1.3rem;">{top["hv"]:.1%}</strong></div>'}
                    {strike_html if is_beginner else ""}
                    <div><div style="font-size:0.75rem;color:#718096;">推奨戦略</div><strong style="font-size:1.1rem;">{strategy_name}</strong></div>
                    <div><div style="font-size:0.75rem;color:#718096;">満期日</div><strong style="font-size:1.1rem;">{exp_show}</strong></div>
                    <div><div style="font-size:0.75rem;color:#718096;">必要資金</div><strong style="font-size:1.1rem;">${top['min_capital']:,}〜</strong></div>
                </div>
                {strategy_note}
            </div>
            """, unsafe_allow_html=True)

        # ========== チャンス銘柄一覧 ==========
        st.markdown(f'<div class="section-title">💰 軍資金 ${capital:,} で入れる銘柄 TOP{top_n}</div>', unsafe_allow_html=True)

        if df_affordable.empty:
            st.warning("現在の軍資金では対象銘柄がありません。軍資金を増やすか、ユニバースを変更してください。")
        else:
            show_df = df_affordable[~df_affordable['signal'].str.contains('様子見')].head(top_n)
            if show_df.empty:
                show_df = df_affordable.head(top_n)

            for i, (_, row) in enumerate(show_df.iterrows()):
                if is_beginner:
                    row_dir = row.get('direction', 'neutral')
                    bkey = get_beginner_strategy(row['signal'], owns_stock, wants_100_shares, row_dir)
                    bstrat = BEGINNER_STRATEGIES[bkey]
                    strategy_name = f"{bstrat['emoji']} {bstrat['name']}"
                    dir_label = {"bullish":"📈 上昇トレンド","bearish":"📉 下落トレンド","neutral":"➡️ 方向感なし"}.get(row_dir,"")
                    rsi_v = row.get('rsi','')
                    b_note = f'<div style="font-size:0.82rem;color:#555;margin-top:8px;background:#f7fafc;border-radius:8px;padding:8px 12px;">📌 {bstrat["desc"]}<br>⚠️ リスク: {bstrat["risk"]}<br>💰 必要: {bstrat["required"]}<br>🔎 テクニカル: {dir_label}{"（RSI: "+str(rsi_v)+"）" if rsi_v else ""}</div>'
                    # プレミアム表示（初心者モード）
                    r_ep = row.get('expiry_premiums', {})
                    r_ep_data = r_ep.get(exp_window, {}) if isinstance(r_ep, dict) else {}
                    r_is_buy = bkey in ("call_buy", "put_buy")
                    if r_ep_data:
                        r_prem = r_ep_data.get('call_premium' if bkey in ('covered_call','call_buy') else 'put_premium', 0)
                        r_prem_contract = r_prem * 100
                        r_exp = r_ep_data.get('expiry', row['expiry'])
                        r_strike = r_ep_data.get('strike', 0)
                        prem_cols = f'<div><span style="color:#718096;font-size:0.8rem;">{"支払う" if r_is_buy else "受け取る"}プレミアム（1枚）</span> <strong style="color:{"#2b6cb0" if r_is_buy else "#276749"};">${r_prem_contract:,.0f}</strong></div><div><span style="color:#718096;font-size:0.8rem;">満期日</span> <strong>{r_exp}</strong></div><div><span style="color:#718096;font-size:0.8rem;">ストライク</span> <strong>${r_strike:.1f}</strong></div>'
                    else:
                        prem_cols = f'<div><span style="color:#718096;font-size:0.8rem;">満期日</span> <strong>{row["expiry"]}</strong></div>'
                else:
                    strategy_name, _ = get_strategy_for_capital(capital, row['price'], row['signal'])
                    b_note = ""
                    prem_cols = f'<div><span style="color:#718096;font-size:0.8rem;">満期日</span> <strong>{row["expiry"]}</strong></div>'
                signal_class = "sell" if "売り" in row['signal'] else ("buy" if "買い" in row['signal'] else "wait")
                signal_html = f'<span class="signal-sell">{row["signal"]}</span>' if "売り" in row['signal'] else (f'<span class="signal-buy">{row["signal"]}</span>' if "買い" in row['signal'] else f'<span class="signal-wait">{row["signal"]}</span>')
                iv_hv_cols = "" if is_beginner else f'<div><span style="color:#718096;font-size:0.8rem;">IV</span> <strong>{row["iv"]:.1%}</strong></div><div><span style="color:#718096;font-size:0.8rem;">HV</span> <strong>{row["hv"]:.1%}</strong></div>'

                st.markdown(f"""
                <div class="chance-card {signal_class}">
                    <strong style="font-size:1.1rem;">{i+2}位　{row['ticker']}</strong>
                    <span style="color:#718096; font-size:0.9rem; margin-left:8px;">{row['name']}</span>
                    &nbsp;&nbsp;{signal_html}
                    <div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:12px;">
                        <div><span style="color:#718096;font-size:0.8rem;">株価</span> <strong>${row['price']:.2f}</strong></div>
                        {iv_hv_cols}
                        <div><span style="color:#718096;font-size:0.8rem;">戦略</span> <strong>{strategy_name}</strong></div>
                        {prem_cols}
                        <div><span style="color:#718096;font-size:0.8rem;">必要資金</span> <strong>${row['min_capital']:,}〜</strong></div>
                    </div>
                    {b_note}
                </div>
                """, unsafe_allow_html=True)

        # ========== 全銘柄表 ==========
        with st.expander("📋 全銘柄スキャン結果を見る"):
            show_cols = ['ticker','name','price','iv','hv','iv_hv_ratio','capital_label','min_capital','signal','strategy']
            disp = df[show_cols].head(20).copy()
            disp['price'] = disp['price'].apply(lambda x: f"${x:.2f}")
            disp['iv']    = disp['iv'].apply(lambda x: f"{x:.1%}")
            disp['hv']    = disp['hv'].apply(lambda x: f"{x:.1%}")
            disp['iv_hv_ratio'] = disp['iv_hv_ratio'].apply(lambda x: f"{x:.2f}")
            disp['min_capital'] = disp['min_capital'].apply(lambda x: f"${x:,}")
            disp.columns = ['ティッカー','会社名','株価','IV','HV','IV/HV比','資金目安','最低必要資金','シグナル','推奨戦略']
            st.dataframe(disp, use_container_width=True)

        if not df_toomuch.empty:
            with st.expander(f"⚠️ 資金不足で対象外の銘柄（{len(df_toomuch)}銘柄）"):
                for _, row in df_toomuch.head(5).iterrows():
                    st.write(f"**{row['ticker']}** ({row['name']}) — 株価: ${row['price']:.2f} | 最低必要: ${row['min_capital']:,} | {row['signal']}")

        # ========== AI分析レポート ==========
        st.markdown('<div class="section-title">🤖 Claude AI 総合分析レポート</div>', unsafe_allow_html=True)
        with st.spinner("AIが分析中です。少々お待ちください..."):
            top5 = df_affordable.head(5) if not df_affordable.empty else df.head(5)
            scan_summary = top5[['ticker','price','iv','hv','iv_hv_ratio','signal','strategy','min_capital']].to_string()
            broker_name = "サクソバンク証券" if is_saxo else "moomoo証券"
            # プロフィール情報をプロンプトに追加
            scan_profile = st.session_state.profile
            scan_personality = get_personality_type(scan_profile)
            profile_note = ""
            if scan_profile.get("setup_done"):
                p_name_s = scan_profile.get("name","")
                profile_note = f"""
【ユーザープロフィール】
名前: {p_name_s if p_name_s else "未設定"}
年齢層: {scan_profile.get("age_group","")}
投資経験: {scan_profile.get("experience","")}
リスクスタンス: {scan_profile.get("risk_tolerance","")}
投資目的: {scan_profile.get("investment_goal","")}
パーソナリティタイプ: {PERSONALITY_LABELS[scan_personality][0]}

このプロフィールに合わせて、戦略推薦と説明のトーンを調整してください。
保守型の場合は安定・安心を強調。積極型の場合はリターンの可能性を強調。バランス型は両面を説明。"""
            if is_beginner:
                bkey = get_beginner_strategy("売りチャンス🔥", owns_stock, wants_100_shares)
                bstrat = BEGINNER_STRATEGIES[bkey]
                level_note = f"""初心者向けに書いてください。専門用語にはカッコで解説を付け、小学生でもわかる言葉で書いてください。
推奨戦略はこの4つの中から選んでください：
1. コール売り（カバードコール）: 100株保有者向け・安定収入型
2. プット売り（100株購入あり / CSP）: 100株買ってもよい方向け
3. プット売り（100株購入なし / スプレッド）: 少額でできる売り戦略
4. コール買い（爆益戦略その1）/ プット買い（爆益戦略その2）: ハイリスクハイリターン

このユーザーの条件: {'100株保有あり' if owns_stock else ('100株購入OK' if wants_100_shares else '100株購入しない')}
→ 売りシグナルの場合は「{bstrat['name']}」を優先推奨してください。
買いシグナルの場合は「コール買い（爆益戦略その1）」を推奨してください。"""
            else:
                level_note = "上級者向けに、専門用語・ギリシャ文字・数値を積極的に使って分析してください。"

            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            prompt = f"""あなたは米国株オプション取引の専門家です。
{universe}のスキャン結果を基に分析してください。
軍資金: ${capital:,} / 証券会社: {broker_name} / 日付: {datetime.now().strftime('%Y年%m月%d日')}
{profile_note}
{level_note}

【スキャン結果】
{scan_summary}

以下のフォーマットで日本語で分析してください：

## 📈 今日の市場環境まとめ
（IV水準から見た全体環境、軍資金${capital:,}にとってどんな状況か）

## 🏆 最優先で狙うべき銘柄 TOP3（軍資金${capital:,}向け）
各銘柄：なぜ今日チャンスか・推奨戦略・ストライク目安・プレミアム・最大損失・リスク

## ⚠️ 今日避けるべきこと

## 💡 {broker_name}ユーザーへのアドバイス
"""
            msg = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            st.markdown(msg.content[0].text)

# ==================== TAB 2: 作戦ナビ ====================
with tab2:

    st.markdown('<div class="section-title">⚙️ 設定</div>', unsafe_allow_html=True)
    col_mode2, col_broker2 = st.columns(2)
    with col_mode2:
        mode2 = st.radio("表示モード", ["🔰 初心者モード", "📊 上級者モード"], horizontal=True, key="nav_mode")
    with col_broker2:
        broker2 = st.radio("証券会社", ["🏦 サクソバンク証券", "📱 moomoo証券"], horizontal=True, key="nav_broker")

    is_beginner2 = "初心者" in mode2
    is_saxo2 = "サクソバンク" in broker2

    if is_beginner2:
        with st.expander("📖 用語がわからない方はここを確認"):
            for term, desc in GLOSSARY.items():
                st.markdown(f"**{term}**：{desc}")

        st.markdown('<div class="section-title">📋 あなたに合った戦略を教えてください</div>', unsafe_allow_html=True)
        q1_nav = st.radio(
            "対象銘柄の株を100株すでに持っていますか？",
            ["いいえ（持っていない）", "はい（持っている）"],
            horizontal=True, key="owns_stock_nav"
        )
        owns_stock2 = "はい" in q1_nav
        wants_100_shares2 = False
        if not owns_stock2:
            q2_nav = st.radio(
                "プット売りの場合、100株を購入してもよいですか？（資金が株価×100ドル必要です）",
                ["いいえ（100株は購入したくない / できない）", "はい（100株を購入してもよい）"],
                horizontal=True, key="wants_100_nav"
            )
            wants_100_shares2 = "はい" in q2_nav
    else:
        owns_stock2 = False
        wants_100_shares2 = False

    st.markdown('<div class="section-title">🔎 銘柄を入力して作戦を立てる</div>', unsafe_allow_html=True)

    # 使い方ガイド
    st.markdown("""
    <div style="background:#ebf8ff;border-radius:12px;padding:16px 20px;margin-bottom:16px;">
        <span class="step">1</span>企業名を入力
        <span class="step">2</span>軍資金を入力
        <span class="step">3</span>ボタンを押す　→　AIが今日の作戦を提案！
    </div>
    """, unsafe_allow_html=True)

    company = st.text_input(
        "企業名またはティッカーシンボルを入力",
        placeholder="例：テスラ、アップル、NVDA、META、エヌビディア..."
    )
    fx_rate2 = get_fx_rate()
    nav_default_usd = int(st.session_state.profile.get("default_capital", 5000))
    st.markdown("**💰 軍資金**")
    capital2_raw, nav_currency = capital_input_with_currency("軍資金", nav_default_usd, "nav_capital", fx_rate2)
    capital2 = int(capital2_raw)
    go = st.button("今日の作戦を見る 🚀", type="primary", use_container_width=True)

    if not go:
        st.markdown("""
        <div style="text-align:center;padding:48px;color:#a0aec0;">
            <div style="font-size:3rem;">📊</div>
            <div style="font-size:1rem;margin-top:8px;">企業名を入力してボタンを押すと、AIが作戦を提案します</div>
            <div style="font-size:0.85rem;margin-top:8px;">対応例：🍎 アップル　🚗 テスラ　🤖 エヌビディア　📦 アマゾン　🪟 マイクロソフト</div>
        </div>
        """, unsafe_allow_html=True)

    elif go and not company:
        st.warning("企業名またはティッカーを入力してください")

    elif go and company:
        ticker = TICKER_MAP.get(company.lower(), company.upper())

        with st.spinner(f"{ticker} のリアルタイムデータを取得中..."):
            ydata, yerr = get_yahoo_data(ticker)

        if ydata:
            price = ydata.get('price', 0) or 0
            iv = ydata.get('iv')
            hv = ydata.get('historical_volatility')
            expiry = ydata.get('target_expiry', '---')

            # 今日のアクション（大きく表示）
            if iv and hv:
                if iv > hv * 1.3:
                    action = "💰 今日は「売り戦略」のチャンス！プレミアムを受け取ろう"
                    st.markdown(f'<div style="background:linear-gradient(135deg,#fed7d7,#fff5f5);border-radius:16px;padding:24px;text-align:center;font-size:1.3rem;font-weight:700;color:#c53030;margin-bottom:16px;">{action}</div>', unsafe_allow_html=True)
                elif iv < hv * 0.8:
                    action = "📈 今日は「買い戦略」のチャンス！上昇に乗ろう"
                    st.markdown(f'<div style="background:linear-gradient(135deg,#c6f6d5,#f0fff4);border-radius:16px;padding:24px;text-align:center;font-size:1.3rem;font-weight:700;color:#276749;margin-bottom:16px;">{action}</div>', unsafe_allow_html=True)
                else:
                    action = "👀 今日は様子見が無難。急いで入らなくてOK"
                    st.markdown(f'<div style="background:linear-gradient(135deg,#fefcbf,#fffff0);border-radius:16px;padding:24px;text-align:center;font-size:1.3rem;font-weight:700;color:#744210;margin-bottom:16px;">{action}</div>', unsafe_allow_html=True)

            # データ表示
            with st.expander("📊 リアルタイムデータの詳細を確認する"):
                c1, c2, c3 = st.columns(3)
                c1.metric("現在株価", f"${price:.2f}" if price else "---")
                iv_val = ydata.get('iv')
                c2.metric("IV（割高感）", f"{iv_val:.1%}" if iv_val else "---",
                         help="高いほどオプションが割高 → 売り有利")
                hv_val = ydata.get('historical_volatility')
                c3.metric("HV（実際の変動）", f"{hv_val:.1%}" if hv_val else "---",
                         help="過去30日の実際の価格変動の大きさ")
                d = ydata.get('direction','neutral')
                d_label = {"bullish":"📈 上昇トレンド","bearish":"📉 下落トレンド","neutral":"➡️ 方向感なし"}.get(d,"")
                rsi_disp = ydata.get('rsi','')
                st.write(f"**{ydata.get('company_name')}**　|　セクター: {ydata.get('sector')}　|　52週高値: ${ydata.get('week52_high')}　/　安値: ${ydata.get('week52_low')}　|　満期日: {expiry}")
                st.info(f"🔎 テクニカル分析: **{d_label}**　RSI: **{rsi_disp}**　MA5: ${ydata.get('ma5','')}　MA20: ${ydata.get('ma20','')}")

        # AI分析
        st.markdown('<div class="section-title">🤖 Claude AI 作戦レポート</div>', unsafe_allow_html=True)
        # デフォルト値（ydata が None の場合に備えて）
        nav_direction = "neutral"
        nav_rsi = ""
        nav_ma5 = ""
        nav_ma20 = ""
        dir_jp = "方向感なし"
        market_data = "データ取得できませんでした"
        with st.spinner("AIが最適な作戦を分析中..."):
            if ydata:
                iv = ydata.get('iv')
                hv = ydata.get('historical_volatility')
                iv_str = f"{iv:.1%}" if iv else '不明'
                hv_str = f"{hv:.1%}" if hv else '不明'
                # テクニカル分析
                nav_direction = ydata.get('direction', 'neutral')
                nav_rsi = ydata.get('rsi', '')
                nav_ma5 = ydata.get('ma5', '')
                nav_ma20 = ydata.get('ma20', '')
                dir_jp = {"bullish":"上昇トレンド","bearish":"下落トレンド","neutral":"方向感なし"}.get(nav_direction,"不明")

                if iv and hv:
                    if iv > hv * 1.3: iv_comment = "IVがHVより30%以上高い → 売り戦略が有利"
                    elif iv < hv * 0.8: iv_comment = "IVがHVより低い → 買い戦略が有利"
                    else: iv_comment = "IVとHVが近い → どちらの戦略も検討可"
                else: iv_comment = "データ不足"
                market_data = f"""
現在株価: ${ydata.get('price')} / 会社名: {ydata.get('company_name')}
IV: {iv_str} / HV: {hv_str} / IV判定: {iv_comment}
テクニカル: {dir_jp} / RSI: {nav_rsi} / MA5: {nav_ma5} / MA20: {nav_ma20}
推奨満期日: {ydata.get('target_expiry','不明')}
52週高値: ${ydata.get('week52_high')} / 安値: ${ydata.get('week52_low')}
ATM Put: {ydata.get('puts_sample','データなし')[:300]}
"""
            else:
                market_data = f"データ取得エラー: {yerr}"
                nav_direction = "neutral"

            if is_beginner2:
                bkey2 = get_beginner_strategy("売りチャンス🔥", owns_stock2, wants_100_shares2, nav_direction)
                bstrat2 = BEGINNER_STRATEGIES[bkey2]
                # 買い戦略の場合はテクニカルで分岐
                if nav_direction == "bearish":
                    buy_rec = "プット買い（爆益戦略その2）"
                else:
                    buy_rec = "コール買い（爆益戦略その1）"
                level_inst = f"""初心者向けに書いてください。専門用語にはカッコで解説を付け、小学生でもわかる言葉で書いてください。
推奨戦略は以下の5つの中から選んでください：
1. コール売り（カバードコール）: 100株保有者向け・安定収入型
2. プット売り（100株購入あり・CSP）: 100株買ってもよい方向け
3. プット売り（100株購入なし・OTM遠め）: 株価から10〜20%離れた場所を売り、プレミアムが半分になったら買い戻して利確
4. コール買い（爆益戦略その1）: 上昇トレンド時に有効
5. プット買い（爆益戦略その2）: 下落トレンド時に有効

このユーザーの条件: {'100株保有あり' if owns_stock2 else ('100株購入OK' if wants_100_shares2 else '100株購入しない')}
テクニカル分析結果: {dir_jp}（RSI: {nav_rsi}）
→ 売りシグナルの場合は「{bstrat2['name']}」を優先推奨してください。
→ 買いシグナルの場合はテクニカルに基づき「{buy_rec}」を推奨してください。
→ プット売り（OTM遠め）を推奨する場合は、株価から10〜20%下のストライクを具体的に示し、「プレミアムが50%減ったら買い戻して利確」という出口戦略も必ず記載してください。"""
            else:
                level_inst = "上級者向けにギリシャ文字・数値を積極的に使って分析してください。"
            broker_inst = "サクソバンク証券" if is_saxo2 else "moomoo証券"
            comp_name = ydata.get('company_name', ticker) if ydata else ticker
            # 作戦ナビのプロフィールノート
            nav_profile = st.session_state.profile
            nav_personality = get_personality_type(nav_profile)
            nav_profile_note = ""
            if nav_profile.get("setup_done"):
                nav_name = nav_profile.get("name","")
                nav_profile_note = f"""
【ユーザープロフィール】
名前: {nav_name if nav_name else "未設定"} / 年齢層: {nav_profile.get("age_group","")} / 経験: {nav_profile.get("experience","")}
リスクスタンス: {nav_profile.get("risk_tolerance","")} / 投資目的: {nav_profile.get("investment_goal","")}
パーソナリティ: {PERSONALITY_LABELS[nav_personality][0]}
このプロフィールに合わせた説明と戦略推薦をしてください。"""

            prompt = f"""あなたは米国株オプション取引の専門家です。
【銘柄】{ticker}（{comp_name}） / 【軍資金】${capital2:,} / 【証券会社】{broker_inst}
{market_data}
{nav_profile_note}
{level_inst}

以下のフォーマットで日本語で回答してください：

## {ticker}（{comp_name}）の今日の作戦

### 🎯 おすすめ戦略：[戦略名]
**選んだ理由：** IV・HV・資金効率・相場ポジションの根拠を具体的に

### 📋 注文の内容（具体的な数字）
| 項目 | 内容 |
|------|------|
| 戦略 | |
| 満期日 | |
| ストライク | |
| 受け取り/支払いプレミアム | |
| 最大利益 | |
| 最大損失 | |
| 必要資金 | |

### 💰 ${capital2:,}での運用シミュレーション
（何枚入れるか・最大いくら稼げるか・最悪いくら失うか）

### ⚠️ 損切りルール
（具体的な撤退ラインを明記）

### 💡 今の相場環境コメント
"""
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            advice = msg.content[0].text

        st.markdown(advice)

        # 証券会社別注文手順
        if ydata:
            st.markdown('<div class="section-title">📋 実際の注文手順</div>', unsafe_allow_html=True)
            broker_steps = build_broker_steps(
                ticker=ticker, expiry=ydata.get('target_expiry','---'),
                price=ydata.get('price', 0) or 0,
                broker_is_saxo=is_saxo2, is_beginner_mode=is_beginner2
            )
            st.markdown(broker_steps)

        # サマリー
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("分析銘柄", ticker)
        c2.metric("軍資金", f"${capital2:,}")
        c3.metric("証券会社", "サクソバンク" if is_saxo2 else "moomoo")

# ==================== TAB 3: マイプロフィール ====================
with tab3:
    st.markdown('<div class="section-title">👤 マイプロフィール設定</div>', unsafe_allow_html=True)

    if not _local_storage_available:
        st.warning("⚠️ プロフィール保存機能は現在ご利用のブラウザでは使えません。セッション中のみ有効です。")

    # 現在のプロフィール確認
    current_profile = st.session_state.profile
    is_setup_done = current_profile.get("setup_done", False)

    if is_setup_done:
        p_label, p_color, p_bg = PERSONALITY_LABELS[personality]
        st.markdown(f"""
        <div style="background:{p_bg};border:2px solid {p_color};border-radius:16px;padding:20px 24px;margin-bottom:24px;">
            <div style="font-size:1.3rem;font-weight:800;color:{p_color};margin-bottom:8px;">{p_label} として登録済みです</div>
            <div style="color:#4a5568;font-size:0.95rem;line-height:1.7;">{PERSONALITY_STRATEGY_HINT[personality]}</div>
        </div>
        """, unsafe_allow_html=True)

        col_info1, col_info2, col_info3, col_info4 = st.columns(4)
        with col_info1:
            st.info(f"👤 {current_profile.get('name','未設定') or '未設定'}")
        with col_info2:
            st.info(f"🎂 {current_profile.get('age_group','')}")
        with col_info3:
            st.info(f"💼 経験 {current_profile.get('experience','')}")
        with col_info4:
            _cap_usd = current_profile.get("default_capital", 5000)
            _cap_cur = current_profile.get("default_capital_currency", "USD")
            _fx_disp = get_fx_rate()
            if _cap_cur == "JPY":
                st.info(f"💰 {usd_to_jpy(_cap_usd, _fx_disp):,}円 (≈${_cap_usd:,})")
            else:
                st.info(f"💰 ${_cap_usd:,} (≈{usd_to_jpy(_cap_usd, _fx_disp):,}円)")

        col_inf2a, col_inf2b = st.columns(2)
        with col_inf2a:
            st.info(f"📊 リスク: {current_profile.get('risk_tolerance','')}")
        with col_inf2b:
            st.info(f"🎯 目標: {current_profile.get('investment_goal','')}")

        st.markdown("<br>", unsafe_allow_html=True)
        if not st.toggle("✏️ プロフィールを編集する", key="edit_profile_toggle"):
            st.stop()

    # ===== プロフィール入力フォーム =====
    st.markdown("""
    <div style="background:#f7fafc;border-radius:12px;padding:20px 24px;margin-bottom:20px;font-size:0.92rem;color:#4a5568;">
    入力した情報はあなたのブラウザにのみ保存されます。サーバーには送信されません。<br>
    一度設定すれば、次回からは自動で読み込まれます。
    </div>
    """, unsafe_allow_html=True)

    with st.form("profile_form"):
        st.markdown("#### 基本情報")
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            f_name = st.text_input(
                "お名前（ニックネームOK）",
                value=current_profile.get("name", ""),
                placeholder="例: 田中 / たなか / Tanaka"
            )
        with col_f2:
            f_age = st.selectbox(
                "年齢層",
                ["20代", "30代", "40代", "50代", "60代以上"],
                index=["20代","30代","40代","50代","60代以上"].index(current_profile.get("age_group","30代"))
            )
        with col_f3:
            f_gender = st.selectbox(
                "性別",
                ["男性", "女性", "答えない"],
                index=["男性","女性","答えない"].index(current_profile.get("gender","答えない"))
            )

        st.markdown("#### 投資に関して")
        col_f4, col_f5 = st.columns(2)
        with col_f4:
            f_exp = st.selectbox(
                "投資経験",
                ["未経験（株・オプション共に）", "株は経験あり・オプションは未経験", "オプション経験1年未満", "オプション経験1〜3年", "オプション経験3年以上"],
                index=["未経験（株・オプション共に）","株は経験あり・オプションは未経験","オプション経験1年未満","オプション経験1〜3年","オプション経験3年以上"].index(
                    current_profile.get("experience","未経験（株・オプション共に）")
                    if current_profile.get("experience","") in ["未経験（株・オプション共に）","株は経験あり・オプションは未経験","オプション経験1年未満","オプション経験1〜3年","オプション経験3年以上"]
                    else "未経験（株・オプション共に）"
                )
            )
        with col_f5:
            f_risk = st.selectbox(
                "リスクに対するスタンス",
                ["低リスク重視（損するのが怖い）", "バランス重視（リスクとリターンのバランスをとりたい）", "高リターン重視（リスクをとってでも大きく稼ぎたい）"],
                index=["低リスク重視（損するのが怖い）","バランス重視（リスクとリターンのバランスをとりたい）","高リターン重視（リスクをとってでも大きく稼ぎたい）"].index(
                    current_profile.get("risk_tolerance","バランス重視（リスクとリターンのバランスをとりたい）")
                    if current_profile.get("risk_tolerance","") in ["低リスク重視（損するのが怖い）","バランス重視（リスクとリターンのバランスをとりたい）","高リターン重視（リスクをとってでも大きく稼ぎたい）"]
                    else "バランス重視（リスクとリターンのバランスをとりたい）"
                )
            )

        f_goal = st.selectbox(
            "オプション投資の目的",
            ["毎月の副収入を安定的に得たい", "資産をじっくり守りながら増やしたい", "短期で大きなリターンを狙いたい", "まずは少額で体験・学習したい"],
            index=["毎月の副収入を安定的に得たい","資産をじっくり守りながら増やしたい","短期で大きなリターンを狙いたい","まずは少額で体験・学習したい"].index(
                current_profile.get("investment_goal","毎月の副収入を安定的に得たい")
                if current_profile.get("investment_goal","") in ["毎月の副収入を安定的に得たい","資産をじっくり守りながら増やしたい","短期で大きなリターンを狙いたい","まずは少額で体験・学習したい"]
                else "毎月の副収入を安定的に得たい"
            )
        )

        st.markdown("#### デフォルト設定")
        col_f6, col_f7 = st.columns(2)
        with col_f6:
            prof_fx = get_fx_rate()
            saved_cur = current_profile.get("default_capital_currency", "USD")
            saved_usd = int(current_profile.get("default_capital", 5000))
            f_currency = st.selectbox(
                "通貨",
                ["USD（ドル）", "JPY（円）"],
                index=0 if "USD" in saved_cur else 1,
                key="profile_currency_sel"
            )
            if "JPY" in f_currency:
                default_jpy_p = max(10000, (usd_to_jpy(saved_usd, prof_fx) // 10000) * 10000)
                f_capital_raw = st.number_input(
                    "よく使う軍資金（円）",
                    value=default_jpy_p, min_value=10000, step=10000, format="%d"
                )
                f_capital = int(jpy_to_usd(f_capital_raw, prof_fx))
                st.caption(f"≈ ${f_capital:,}　（1ドル＝{prof_fx:.1f}円）")
            else:
                f_capital = st.number_input(
                    "よく使う軍資金（ドル）",
                    value=saved_usd, min_value=200, step=500, format="%d"
                )
                st.caption(f"≈ {usd_to_jpy(f_capital, prof_fx):,}円　（1ドル＝{prof_fx:.1f}円）")
        with col_f7:
            f_broker = st.selectbox(
                "証券会社",
                ["サクソバンク証券", "moomoo証券"],
                index=["サクソバンク証券","moomoo証券"].index(
                    current_profile.get("broker","サクソバンク証券")
                    if current_profile.get("broker","") in ["サクソバンク証券","moomoo証券"]
                    else "サクソバンク証券"
                )
            )

        submitted = st.form_submit_button("💾 プロフィールを保存する", type="primary", use_container_width=True)

    if submitted:
        # risk_toleranceを短縮キーに変換（内部判定用）
        risk_map = {
            "低リスク重視（損するのが怖い）": "低リスク重視",
            "バランス重視（リスクとリターンのバランスをとりたい）": "バランス重視",
            "高リターン重視（リスクをとってでも大きく稼ぎたい）": "高リターン重視",
        }
        exp_map = {
            "未経験（株・オプション共に）": "未経験",
            "株は経験あり・オプションは未経験": "未経験",
            "オプション経験1年未満": "1年未満",
            "オプション経験1〜3年": "1〜3年",
            "オプション経験3年以上": "3年以上",
        }
        goal_map = {
            "毎月の副収入を安定的に得たい": "副収入を得たい",
            "資産をじっくり守りながら増やしたい": "資産を守りたい",
            "短期で大きなリターンを狙いたい": "大きく増やしたい",
            "まずは少額で体験・学習したい": "副収入を得たい",
        }
        new_profile = {
            "name": f_name.strip(),
            "age_group": f_age,
            "gender": f_gender,
            "experience": exp_map.get(f_exp, "未経験"),
            "risk_tolerance": risk_map.get(f_risk, "バランス重視"),
            "investment_goal": goal_map.get(f_goal, "副収入を得たい"),
            "default_capital": int(f_capital),
            "default_capital_currency": "JPY" if "JPY" in f_currency else "USD",
            "broker": f_broker,
            "setup_done": True,
        }
        save_profile(_ls, new_profile)
        st.session_state.profile = new_profile
        ptype = get_personality_type(new_profile)
        p_label_new, p_color_new, p_bg_new = PERSONALITY_LABELS[ptype]
        st.success(f"✅ プロフィールを保存しました！")
        st.markdown(f"""
        <div style="background:{p_bg_new};border:2px solid {p_color_new};border-radius:16px;padding:20px 24px;margin-top:16px;">
            <div style="font-size:1.2rem;font-weight:800;color:{p_color_new};">あなたのタイプ: {p_label_new}</div>
            <div style="color:#4a5568;font-size:0.95rem;margin-top:8px;">{PERSONALITY_STRATEGY_HINT[ptype]}</div>
            <div style="margin-top:12px;font-size:0.85rem;color:#718096;">次回からは自動でプロフィールが読み込まれます。「チャンス銘柄スキャナー」タブに移動して分析を始めましょう！</div>
        </div>
        """, unsafe_allow_html=True)
        st.balloons()

    # プロフィール削除
    if is_setup_done:
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("🗑️ プロフィールを削除する"):
            st.warning("削除すると保存済みのプロフィールが消えます。次回アクセス時に再入力が必要になります。")
            if st.button("プロフィールを削除する", key="delete_profile"):
                if _ls:
                    try:
                        _ls.deleteItem("user_profile")
                    except Exception:
                        pass
                st.session_state.profile = dict(DEFAULT_PROFILE)
                st.success("プロフィールを削除しました。")
                st.rerun()

import streamlit as st
import yfinance as yf
import pandas as pd
import anthropic
from datetime import datetime, timedelta
import time
import os
import numpy as np

ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))

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

            try: expirations = stock.options
            except Exception as e:
                errors.append(f"{ticker}: オプション取得失敗"); time.sleep(1); continue
            if not expirations:
                errors.append(f"{ticker}: オプション満期日なし"); continue

            target_exp = None
            for exp in expirations:
                if datetime.strptime(exp, '%Y-%m-%d') > datetime.now() + timedelta(days=20):
                    target_exp = exp; break
            if not target_exp:
                errors.append(f"{ticker}: 20日以上先の満期日なし"); continue

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

# ========== タブ ==========
tab1, tab2 = st.tabs(["　🔍 チャンス銘柄スキャナー　", "　📊 作戦ナビ（個別銘柄）　"])

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

    col1, col2, col3 = st.columns(3)
    with col1:
        universe = st.selectbox("対象ユニバース", ["QQQ上位30銘柄", "S&P500代表30銘柄"])
    with col2:
        capital = st.number_input("💰 軍資金（ドル）", value=5000, step=1000, min_value=500, key="scan_capital")
    with col3:
        top_n = st.number_input("表示する上位銘柄数", value=5, min_value=3, max_value=10)

    # 軍資金ガイド
    tier_label = next((n for n, t in CAPITAL_TIERS.items() if t["min"] <= capital < t["max"]), "")
    if tier_label:
        st.info(f"💼 **{tier_label}** の軍資金で使える戦略のみ表示します")

    if is_beginner:
        with st.expander("📖 軍資金別 使える戦略ガイド（初心者の方はここを確認）"):
            st.markdown("""
            | 軍資金 | 使える戦略 | 目安銘柄 |
            |--------|-----------|---------|
            | $500〜$2,000 | デビットスプレッド（格安銘柄のみ） | $30以下 |
            | $2,000〜$5,000 | デビットスプレッド・クレジットスプレッド | $200以下 |
            | $5,000〜$15,000 | スプレッド全般・CSP（安い株のみ） | $400以下 |
            | $15,000〜$30,000 | CSP・カバードコール・スプレッド | ほぼ全銘柄 |
            | $30,000〜 | 全戦略（IC・CSP・CC含む） | 全銘柄 |
            """)

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
            strategy_name, _ = get_strategy_for_capital(capital, top['price'], top['signal'])
            st.markdown(f"""
            <div class="chance-card {signal_class}">
                <div class="rank-badge">🥇 本日 No.1 チャンス銘柄</div><br>
                <strong style="font-size:1.5rem;">{top['ticker']}</strong>
                <span style="color:#718096; margin-left:8px;">{top['name']}</span>
                &nbsp;&nbsp;{signal_html}
                <hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0;">
                <div style="display:flex;gap:32px;flex-wrap:wrap;">
                    <div><div style="font-size:0.75rem;color:#718096;">株価</div><strong style="font-size:1.3rem;">${top['price']:.2f}</strong></div>
                    <div><div style="font-size:0.75rem;color:#718096;">IV（オプション割高感）</div><strong style="font-size:1.3rem;">{top['iv']:.1%}</strong></div>
                    <div><div style="font-size:0.75rem;color:#718096;">HV（実際の変動）</div><strong style="font-size:1.3rem;">{top['hv']:.1%}</strong></div>
                    <div><div style="font-size:0.75rem;color:#718096;">推奨戦略</div><strong style="font-size:1.1rem;">{strategy_name}</strong></div>
                    <div><div style="font-size:0.75rem;color:#718096;">満期日</div><strong style="font-size:1.1rem;">{top['expiry']}</strong></div>
                    <div><div style="font-size:0.75rem;color:#718096;">必要資金</div><strong style="font-size:1.1rem;">${top['min_capital']:,}〜</strong></div>
                </div>
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
                strategy_name, _ = get_strategy_for_capital(capital, row['price'], row['signal'])
                signal_class = "sell" if "売り" in row['signal'] else ("buy" if "買い" in row['signal'] else "wait")
                signal_html = f'<span class="signal-sell">{row["signal"]}</span>' if "売り" in row['signal'] else (f'<span class="signal-buy">{row["signal"]}</span>' if "買い" in row['signal'] else f'<span class="signal-wait">{row["signal"]}</span>')
                put_txt = f"Putプレミアム: <strong>${row['atm_put_premium']:.2f}</strong>" if row.get('atm_put_premium') else ""
                call_txt = f"Callプレミアム: <strong>${row['atm_call_premium']:.2f}</strong>" if row.get('atm_call_premium') else ""

                st.markdown(f"""
                <div class="chance-card {signal_class}">
                    <strong style="font-size:1.1rem;">{i+2}位　{row['ticker']}</strong>
                    <span style="color:#718096; font-size:0.9rem; margin-left:8px;">{row['name']}</span>
                    &nbsp;&nbsp;{signal_html}
                    <div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:12px;">
                        <div><span style="color:#718096;font-size:0.8rem;">株価</span> <strong>${row['price']:.2f}</strong></div>
                        <div><span style="color:#718096;font-size:0.8rem;">IV</span> <strong>{row['iv']:.1%}</strong></div>
                        <div><span style="color:#718096;font-size:0.8rem;">HV</span> <strong>{row['hv']:.1%}</strong></div>
                        <div><span style="color:#718096;font-size:0.8rem;">戦略</span> <strong>{strategy_name}</strong></div>
                        <div><span style="color:#718096;font-size:0.8rem;">満期日</span> <strong>{row['expiry']}</strong></div>
                        <div><span style="color:#718096;font-size:0.8rem;">必要資金</span> <strong>${row['min_capital']:,}〜</strong></div>
                        {f'<div>{put_txt}</div>' if put_txt else ''}
                        {f'<div>{call_txt}</div>' if call_txt else ''}
                    </div>
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
            level_note = "初心者向けに、専門用語にはカッコで解説を付け、小学生でもわかる言葉で書いてください。" if is_beginner else "上級者向けに、専門用語・ギリシャ文字・数値を積極的に使って分析してください。"

            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            prompt = f"""あなたは米国株オプション取引の専門家です。
{universe}のスキャン結果を基に分析してください。
軍資金: ${capital:,} / 証券会社: {broker_name} / 日付: {datetime.now().strftime('%Y年%m月%d日')}
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
    capital2 = st.number_input("💰 軍資金（ドル）", value=5000, step=1000, min_value=500, key="nav_capital")
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
                st.write(f"**{ydata.get('company_name')}**　|　セクター: {ydata.get('sector')}　|　52週高値: ${ydata.get('week52_high')}　/　安値: ${ydata.get('week52_low')}　|　推奨満期日: {expiry}")

        # AI分析
        st.markdown('<div class="section-title">🤖 Claude AI 作戦レポート</div>', unsafe_allow_html=True)
        with st.spinner("AIが最適な作戦を分析中..."):
            if ydata:
                iv = ydata.get('iv')
                hv = ydata.get('historical_volatility')
                iv_str = f"{iv:.1%}" if iv else '不明'
                hv_str = f"{hv:.1%}" if hv else '不明'
                if iv and hv:
                    if iv > hv * 1.3: iv_comment = "IVがHVより30%以上高い → 売り戦略が有利"
                    elif iv < hv * 0.8: iv_comment = "IVがHVより低い → 買い戦略が有利"
                    else: iv_comment = "IVとHVが近い → どちらの戦略も検討可"
                else: iv_comment = "データ不足"
                market_data = f"""
現在株価: ${ydata.get('price')} / 会社名: {ydata.get('company_name')}
IV: {iv_str} / HV: {hv_str} / 判定: {iv_comment}
推奨満期日: {ydata.get('target_expiry','不明')}
52週高値: ${ydata.get('week52_high')} / 安値: ${ydata.get('week52_low')}
ATM Put: {ydata.get('puts_sample','データなし')[:300]}
"""
            else:
                market_data = f"データ取得エラー: {yerr}"

            level_inst = "初心者向けに専門用語をカッコで解説し、小学5年生でもわかる言葉で書いてください。" if is_beginner2 else "上級者向けにギリシャ文字・数値を積極的に使って分析してください。"
            broker_inst = "サクソバンク証券" if is_saxo2 else "moomoo証券"
            comp_name = ydata.get('company_name', ticker) if ydata else ticker

            prompt = f"""あなたは米国株オプション取引の専門家です。
【銘柄】{ticker}（{comp_name}） / 【軍資金】${capital2:,} / 【証券会社】{broker_inst}
{market_data}
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

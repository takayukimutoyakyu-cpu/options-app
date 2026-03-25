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

# ========== ヘルパー関数 ==========
def calc_min_capital(price):
    if price < 30:   return 150
    elif price < 60:  return 300
    elif price < 100: return 500
    elif price < 200: return 800
    elif price < 400: return 1500
    elif price < 800: return 3000
    else:             return 5000

def calc_csp_capital(price):
    return int(price * 100)

def get_capital_label(min_cap):
    if min_cap <= 300:   return "💚 超少額OK"
    elif min_cap <= 800: return "🟡 少額OK"
    elif min_cap <= 1500: return "🟠 中額向け"
    else:                return "🔴 大口向け"

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

**【ステップ1】サクソバンクにログイン**
- PC: saxotrader.com にアクセス → ログイン
- スマホ: SaxoTraderGO アプリを開く

**【ステップ2】銘柄を検索**
- 検索バーに **{ticker}** と入力 → 「オプション」タブを選択

**【ステップ3】満期日・ストライクを選択**
- 満期日 **{expiry}** を選択
- 現在株価 **${price:.2f}** 付近のストライクを探す

**【ステップ4】注文入力 → 確認 → 送信**
- 数量: 1枚（1契約 = 株100株分）から開始
"""
        if is_beginner_mode:
            steps += "\n> 💡 **初心者メモ**: サクソバンクは「オプション取引」の申請が必要な場合があります。"
    else:
        steps = f"""
### 📱 moomoo証券での注文手順

**【ステップ1】moomooアプリを開く**

**【ステップ2】銘柄を検索**
- 下のメニュー「マーケット」→ 検索に **{ticker}** と入力

**【ステップ3】オプション画面に移動**
- 銘柄ページの上部タブ「オプション」をタップ
- 満期日 **{expiry}** を選択 → 現在株価 **${price:.2f}** 付近のストライクを選択

**【ステップ4】注文 → 確認 → 送信**
- 数量: 1枚から開始
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
                    price = None
                    name = ticker
            else:
                try:
                    name = stock.info.get('shortName', ticker)
                except Exception:
                    name = ticker

            hist = stock.history(period='30d')
            if hist.empty:
                errors.append(f"{ticker}: 株価履歴なし")
                time.sleep(1)
                continue
            if not price:
                price = float(hist['Close'].iloc[-1])

            returns = hist['Close'].pct_change().dropna()
            if len(returns) < 5:
                errors.append(f"{ticker}: データ不足")
                continue
            hv = float(returns.std() * (252 ** 0.5))

            try:
                expirations = stock.options
            except Exception as e:
                errors.append(f"{ticker}: オプション取得失敗 {e}")
                time.sleep(1)
                continue
            if not expirations:
                errors.append(f"{ticker}: オプション満期日なし")
                continue

            target_exp = None
            for exp in expirations:
                exp_dt = datetime.strptime(exp, '%Y-%m-%d')
                if exp_dt > datetime.now() + timedelta(days=20):
                    target_exp = exp
                    break
            if not target_exp:
                errors.append(f"{ticker}: 20日以上先の満期日なし")
                continue

            opt = stock.option_chain(target_exp)
            puts = opt.puts
            calls = opt.calls
            if puts.empty or 'impliedVolatility' not in puts.columns:
                errors.append(f"{ticker}: プットデータなし")
                continue

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
                signal = "売りチャンス🔥"
                strategy = "CSP or クレジットスプレッド"
                score = iv_hv_ratio * iv * 100
            elif iv_hv_ratio < 0.8 and hv > 0.25:
                signal = "買いチャンス💡"
                strategy = "デビットスプレッド"
                score = (1 / iv_hv_ratio) * hv * 100
            elif iv > 0.35:
                signal = "売りチャンス🔥"
                strategy = "アイアンコンドル"
                score = iv * 80
            else:
                signal = "様子見👀"
                strategy = "エントリー見送り"
                score = 10

            min_cap = calc_min_capital(price)
            csp_cap = calc_csp_capital(price)
            cap_label = get_capital_label(min_cap)

            return {
                'ticker': ticker, 'name': name, 'price': price,
                'iv': iv, 'hv': hv, 'iv_hv_ratio': iv_hv_ratio,
                'signal': signal, 'strategy': strategy, 'score': score,
                'expiry': target_exp,
                'atm_put_strike': float(atm_puts.iloc[0]['strike']) if len(atm_puts) > 0 else None,
                'atm_put_premium': float(atm_puts.iloc[0]['lastPrice']) if len(atm_puts) > 0 else None,
                'atm_call_premium': atm_call_premium,
                'min_capital': min_cap, 'csp_capital': csp_cap, 'capital_label': cap_label,
            }
        except Exception as e:
            errors.append(f"{ticker}: 例外 {type(e).__name__}: {e}")
            time.sleep(1 + attempt)
    return {'_error': True, 'ticker': ticker, 'reason': ' | '.join(errors)}

@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        result = {}
        result['price'] = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        result['company_name'] = info.get('shortName', ticker)
        result['sector'] = info.get('sector', '不明')
        result['week52_high'] = info.get('fiftyTwoWeekHigh')
        result['week52_low'] = info.get('fiftyTwoWeekLow')
        result['iv'] = None
        result['historical_volatility'] = None

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
            exp_dt = datetime.strptime(exp, '%Y-%m-%d')
            if exp_dt > datetime.now() + timedelta(days=20):
                best_expiry = exp
                break

        if best_expiry:
            result['target_expiry'] = best_expiry
            opt = stock.option_chain(best_expiry)
            puts = opt.puts
            calls = opt.calls

            if not puts.empty and 'impliedVolatility' in puts.columns and result['price']:
                puts['distance'] = abs(puts['strike'] - result['price'])
                atm_puts = puts.nsmallest(10, 'distance')
                result['puts_sample'] = atm_puts[['strike', 'lastPrice', 'impliedVolatility', 'volume', 'openInterest']].to_string()
                result['put_iv_avg'] = atm_puts['impliedVolatility'].mean()
                result['put_iv_atm'] = atm_puts.iloc[0]['impliedVolatility'] if len(atm_puts) > 0 else None

            if not calls.empty and 'impliedVolatility' in calls.columns and result['price']:
                calls['distance'] = abs(calls['strike'] - result['price'])
                atm_calls = calls.nsmallest(10, 'distance')
                result['calls_sample'] = atm_calls[['strike', 'lastPrice', 'impliedVolatility', 'volume', 'openInterest']].to_string()
                result['call_iv_avg'] = atm_calls['impliedVolatility'].mean()

            if result.get('put_iv_avg') and result.get('call_iv_avg'):
                result['iv'] = (result['put_iv_avg'] + result['call_iv_avg']) / 2

        result['status'] = '成功'
        return result, None
    except Exception as e:
        return None, str(e)

# ========== ページ設定 ==========
st.set_page_config(page_title="米国株オプション ツール", page_icon="📈", layout="wide")
st.title("📈 米国株オプション取引ツール")

# ========== タブ ==========
tab1, tab2 = st.tabs(["🔍 チャンス銘柄スキャナー", "📊 作戦ナビ（個別銘柄）"])

# ==================== TAB 1: スキャナー ====================
with tab1:
    st.subheader("🔍 オプションチャンス スキャナー")
    st.caption("QQQ・S&P500の構成銘柄から今日のチャンスを自動発見")

    col_mode, col_broker = st.columns(2)
    with col_mode:
        mode = st.radio("表示モード", ["🔰 初心者モード", "📊 上級者モード"], horizontal=True, key="scan_mode")
    with col_broker:
        broker = st.radio("使っている証券会社", ["🏦 サクソバンク証券", "📱 moomoo証券"], horizontal=True, key="scan_broker")

    is_beginner = "初心者" in mode
    is_saxo = "サクソバンク" in broker

    if is_beginner:
        st.info("🔰 **初心者モード**：むずかしい用語はわかりやすく表示します")

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        universe = st.selectbox("対象ユニバース", ["QQQ上位30銘柄", "S&P500代表30銘柄"])
    with col2:
        capital = st.number_input("💰 軍資金（ドル）", value=5000, step=1000, min_value=500, key="scan_capital")
    with col3:
        top_n = st.number_input("上位何銘柄を表示", value=5, min_value=3, max_value=10)

    tier_label = ""
    for name, tier in CAPITAL_TIERS.items():
        if tier["min"] <= capital < tier["max"]:
            tier_label = name
            break
    if tier_label:
        st.info(f"💼 あなたの軍資金: **{tier_label}** → この資金でできる戦略のみ表示します")

    with st.expander("📖 軍資金別 使える戦略ガイド"):
        st.markdown("""
        | 軍資金 | 使える戦略 | 対象銘柄の目安 |
        |--------|-----------|--------------|
        | $500〜$2,000 | デビットスプレッド（格安銘柄のみ） | $30以下の銘柄 |
        | $2,000〜$5,000 | デビットスプレッド・クレジットスプレッド | $200以下の銘柄 |
        | $5,000〜$15,000 | スプレッド全般・CSP（安い株のみ） | $400以下の銘柄 |
        | $15,000〜$30,000 | CSP・カバードコール・スプレッド | ほぼ全銘柄 |
        | $30,000〜 | 全戦略（IC・CSP・CC含む） | 全銘柄 |
        """)

    scan_btn = st.button("🔍 今日のチャンス銘柄をスキャン", type="primary", use_container_width=True)

    if scan_btn:
        tickers = QQQ_TOP30 if "QQQ" in universe else SP500_TOP30
        st.info(f"🔄 {len(tickers)}銘柄をスキャン中... 約1〜2分かかります")
        progress = st.progress(0)
        status = st.empty()

        results = []
        errors = []
        for i, ticker in enumerate(tickers):
            status.text(f"スキャン中: {ticker} ({i+1}/{len(tickers)})")
            r = scan_ticker(ticker)
            if r and not r.get('_error'):
                results.append(r)
            elif r and r.get('_error'):
                errors.append(f"**{r['ticker']}**: {r['reason']}")
            progress.progress((i + 1) / len(tickers))
            time.sleep(0.3)

        progress.empty()
        status.empty()

        if not results:
            st.error("データを取得できませんでした。しばらく待ってから再スキャンしてください。")
            if errors:
                with st.expander("🔍 詳細エラー情報"):
                    for e in errors[:10]:
                        st.write(e)
            st.stop()

        df = pd.DataFrame(results).sort_values('score', ascending=False)
        df_affordable = df[df['min_capital'] <= capital].copy()
        df_toomuch = df[df['min_capital'] > capital].copy()

        st.success(f"✅ スキャン完了！{len(results)}銘柄を分析 → あなたの軍資金（${capital:,}）で**{len(df_affordable)}銘柄**が対象")

        st.subheader(f"💰 軍資金 ${capital:,} で今すぐできる銘柄")
        if df_affordable.empty:
            st.warning("現在の軍資金では対象銘柄がありません。もう少し資金を増やすか、スキャン対象を変更してください。")
        else:
            affordable_ops = df_affordable[~df_affordable['signal'].str.contains('様子見')].head(top_n)
            if affordable_ops.empty:
                affordable_ops = df_affordable.head(top_n)

            for _, row in affordable_ops.iterrows():
                strategy_name, req_cap = get_strategy_for_capital(capital, row['price'], row['signal'])
                with st.container(border=True):
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("銘柄", row['ticker'])
                    c2.metric("株価", f"${row['price']:.2f}")
                    c3.metric("IV", f"{row['iv']:.1%}")
                    c4.metric("HV", f"{row['hv']:.1%}")
                    c5.metric("シグナル", row['signal'].replace('🔥','').replace('💡','').strip())
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        st.write(f"**{row['capital_label']}**")
                        st.write(f"最低必要資金: **${row['min_capital']:,}**")
                    with col_b:
                        st.write(f"**おすすめ戦略:** {strategy_name}")
                        st.write(f"**満期日:** {row['expiry']}")
                    with col_c:
                        if row.get('atm_put_premium'):
                            st.write(f"**ATM Putプレミアム:** ${row['atm_put_premium']:.2f}")
                        if row.get('atm_call_premium'):
                            st.write(f"**ATM Callプレミアム:** ${row['atm_call_premium']:.2f}")

        st.subheader("📊 全銘柄スキャン結果")
        summary_cols = ['ticker', 'name', 'price', 'iv', 'hv', 'iv_hv_ratio', 'capital_label', 'min_capital', 'signal', 'strategy']
        display_df = df[summary_cols].head(20).copy()
        display_df['price'] = display_df['price'].apply(lambda x: f"${x:.2f}")
        display_df['iv'] = display_df['iv'].apply(lambda x: f"{x:.1%}")
        display_df['hv'] = display_df['hv'].apply(lambda x: f"{x:.1%}")
        display_df['iv_hv_ratio'] = display_df['iv_hv_ratio'].apply(lambda x: f"{x:.2f}")
        display_df['min_capital'] = display_df['min_capital'].apply(lambda x: f"${x:,}")
        display_df.columns = ['ティッカー', '会社名', '株価', 'IV', 'HV', 'IV/HV比', '資金目安', '最低必要資金', 'シグナル', '推奨戦略']
        st.dataframe(display_df, use_container_width=True)

        if not df_toomuch.empty:
            with st.expander(f"⚠️ 資金不足で今回対象外の銘柄（{len(df_toomuch)}銘柄）"):
                for _, row in df_toomuch.head(5).iterrows():
                    st.write(f"**{row['ticker']}** ({row['name']}) - 株価: ${row['price']:.2f} | 最低必要: ${row['min_capital']:,} | {row['signal']}")

        st.subheader("🤖 Claude AI 総合分析レポート")
        with st.spinner("AIが軍資金に合わせた戦略を分析中..."):
            top5 = df_affordable.head(5) if not df_affordable.empty else df.head(5)
            scan_summary = top5[['ticker', 'price', 'iv', 'hv', 'iv_hv_ratio', 'signal', 'strategy', 'min_capital']].to_string()
            broker_name = "サクソバンク証券" if is_saxo else "moomoo証券"
            level_note = "初心者向けに、専門用語にはカッコで説明を付け、小学生でもわかる言葉で書いてください。" if is_beginner else "上級者向けに、専門用語・ギリシャ文字・数値を積極的に使って分析してください。"

            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            prompt = f"""あなたは米国株オプション取引の専門家です。
以下は{universe}のスキャン結果です。
**軍資金: ${capital:,}** / **証券会社: {broker_name}** / 本日: {datetime.now().strftime('%Y年%m月%d日')}
{level_note}

【軍資金 ${capital:,} で対象の銘柄】
{scan_summary}

この軍資金（${capital:,}）に合わせて日本語で分析してください：

## 📈 今日の市場環境まとめ
## 🏆 最優先で狙うべき銘柄 TOP3（軍資金${capital:,}向け）
各銘柄：戦略・ストライク目安・プレミアム・最大損失・リスク
## ⚠️ 今日避けるべきこと
## 💡 初心者へのアドバイス（{broker_name}向け）
"""
            msg = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            st.markdown(msg.content[0].text)

# ==================== TAB 2: 作戦ナビ ====================
with tab2:
    st.subheader("📊 作戦ナビ（個別銘柄アドバイザー）")
    st.caption("企業名を入れるだけで、今日やることがわかる")

    col_mode2, col_broker2 = st.columns(2)
    with col_mode2:
        mode2 = st.radio("表示モード", ["🔰 初心者モード", "📊 上級者モード"], horizontal=True, key="nav_mode")
    with col_broker2:
        broker2 = st.radio("使っている証券会社", ["🏦 サクソバンク証券", "📱 moomoo証券"], horizontal=True, key="nav_broker")

    is_beginner2 = "初心者" in mode2
    is_saxo2 = "サクソバンク" in broker2

    if is_beginner2:
        st.info("🔰 **初心者モード**：難しい用語はわかりやすく説明します。")
        with st.expander("📖 わからない用語はここで確認！"):
            for term, desc in GLOSSARY.items():
                st.markdown(f"**{term}**")
                st.caption(desc)
                st.divider()

    st.divider()

    company = st.text_input("企業名またはティッカーを入力", placeholder="例：テスラ、アップル、NVDA、META...")
    capital2 = st.number_input("💰 軍資金（ドル）", value=5000, step=1000, min_value=500, key="nav_capital")
    go = st.button("今日の作戦を見る 🚀", type="primary", use_container_width=True)

    if go and company:
        ticker = TICKER_MAP.get(company.lower(), company.upper())

        with st.spinner(f"{ticker} のリアルタイムデータを取得中..."):
            ydata, yerr = get_yahoo_data(ticker)

        if ydata:
            price = ydata.get('price', 0)
            iv = ydata.get('iv')
            hv = ydata.get('historical_volatility')
            expiry = ydata.get('target_expiry', '---')

            if iv and hv:
                if iv > hv * 1.3:
                    action = "💰 今日は「売り戦略」のチャンス！プレミアムを受け取ろう"
                    st.success(f"### {action}")
                elif iv < hv * 0.8:
                    action = "📈 今日は「買い戦略」のチャンス！上昇に乗ろう"
                    st.info(f"### {action}")
                else:
                    action = "👀 今日は様子見が無難。急いで入らなくてOK"
                    st.warning(f"### {action}")
            else:
                st.info("### 📊 データ分析中...")

            with st.expander("📊 リアルタイムデータを確認する"):
                c1, c2, c3 = st.columns(3)
                c1.metric("現在株価", f"${price:.2f}" if price else "---")
                iv_val = ydata.get('iv')
                c2.metric("IV（オプションの割高感）", f"{iv_val:.1%}" if iv_val else "---")
                hv_val = ydata.get('historical_volatility')
                c3.metric("HV（実際の価格変動）", f"{hv_val:.1%}" if hv_val else "---")
                st.write(f"**会社名:** {ydata.get('company_name')}　|　**セクター:** {ydata.get('sector')}")
                st.write(f"**52週高値:** ${ydata.get('week52_high')}　/　**52週安値:** ${ydata.get('week52_low')}")
                st.write(f"**推奨満期日:** {expiry}")

        # AI分析
        with st.spinner("Claude AIが最適な作戦を考えています..."):
            if ydata:
                iv = ydata.get('iv')
                hv = ydata.get('historical_volatility')
                iv_str = f"{iv:.1%}" if iv else '不明'
                hv_str = f"{hv:.1%}" if hv else '不明'
                if iv and hv:
                    if iv > hv * 1.3: iv_comment = "IVがHVより30%以上高い → 売り戦略が有利"
                    elif iv < hv * 0.8: iv_comment = "IVがHVより低い → 買い戦略が有利"
                    else: iv_comment = "IVとHVが近い → どちらの戦略も検討可"
                else:
                    iv_comment = "データ不足"
                market_data = f"""
現在株価: ${ydata.get('price')} / 会社名: {ydata.get('company_name')}
IV: {iv_str} / HV: {hv_str} / IV分析: {iv_comment}
推奨満期日: {ydata.get('target_expiry', '不明')}
52週高値: ${ydata.get('week52_high')} / 安値: ${ydata.get('week52_low')}
ATM付近Put: {ydata.get('puts_sample', 'データなし')[:300]}
"""
            else:
                market_data = f"データ取得エラー: {yerr}"

            level_inst = "初心者向けに専門用語をカッコで解説し、小学5年生でもわかる言葉で書いてください。" if is_beginner2 else "上級者向けにギリシャ文字・数値を積極的に使って分析してください。"
            broker_inst = "サクソバンク証券" if is_saxo2 else "moomoo証券"

            prompt = f"""あなたは米国株オプション取引の専門家です。
【銘柄】{ticker} / 【軍資金】${capital2:,} / 【証券会社】{broker_inst}
{market_data}
{level_inst}

以下のフォーマットで日本語で答えてください：

## {ticker} の今日の作戦

### 🎯 おすすめ戦略：[戦略名]
**選んだ理由：** IV・HV・資金効率・相場ポジションの根拠

### 📋 注文の内容（具体的な数字）
| 項目 | 内容 |
|------|------|
| 戦略 | |満期日 | |ストライク | |プレミアム | |最大利益 | |最大損失 | |必要資金 | |

### 💰 お金のシミュレーション
${capital2:,}で何枚入れるか、いくら稼げるか、最悪いくら失うか

### ⚠️ 損切りルール

### 💡 今の相場環境コメント
"""
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            advice = msg.content[0].text

        st.success(f"✅ {ticker} の作戦ができました！")
        st.markdown(advice)

        if ydata:
            st.divider()
            broker_steps = build_broker_steps(
                ticker=ticker, expiry=ydata.get('target_expiry', '---'),
                price=ydata.get('price', 0), broker_is_saxo=is_saxo2, is_beginner_mode=is_beginner2
            )
            st.markdown(broker_steps)

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("銘柄", ticker)
        c2.metric("軍資金", f"${capital2:,}")
        c3.metric("証券会社", "サクソバンク" if is_saxo2 else "moomoo")

    elif go and not company:
        st.warning("企業名を入力してください")
    else:
        st.markdown("""
        ### 使い方
        1. 上の**モード**と**証券会社**を選ぶ
        2. **企業名**を入力（日本語でもOK）
        3. **軍資金**を入力
        4. **「今日の作戦を見る」**ボタンを押す

        ### 対応している企業（例）
        🍎 アップル　🚗 テスラ　🤖 エヌビディア
        📦 アマゾン　🪟 マイクロソフト　🔍 グーグル　📘 メタ
        """)

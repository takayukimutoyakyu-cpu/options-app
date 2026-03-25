import streamlit as st
import yfinance as yf
import pandas as pd
import anthropic
from datetime import datetime, timedelta
import time

ANTHROPIC_API_KEY = "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"

# QQQ上位30銘柄
QQQ_TOP30 = [
    "MSFT", "AAPL", "NVDA", "AMZN", "META",
    "TSLA", "GOOGL", "GOOG", "AVGO", "COST",
    "NFLX", "AMD", "ADBE", "QCOM", "INTC",
    "INTU", "CSCO", "PEP", "AMAT", "TXN",
    "SBUX", "ISRG", "MU", "LRCX", "KLAC",
    "MRVL", "PANW", "SNPS", "CDNS", "ASML"
]

# SP500有名銘柄30
SP500_TOP30 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "TSLA", "BRK-B", "JPM", "V", "UNH",
    "XOM", "MA", "JNJ", "PG", "HD",
    "GOOGL", "CVX", "MRK", "ABBV", "PEP",
    "KO", "BAC", "WMT", "LLY", "COST",
    "TMO", "MCD", "CRM", "ACN", "ORCL"
]

# 軍資金ティア定義
CAPITAL_TIERS = {
    "超少額（$500〜$2,000）": {"min": 500, "max": 2000},
    "少額（$2,000〜$5,000）": {"min": 2000, "max": 5000},
    "中額（$5,000〜$15,000）": {"min": 5000, "max": 15000},
    "標準（$15,000〜$30,000）": {"min": 15000, "max": 30000},
    "大口（$30,000〜）": {"min": 30000, "max": 9999999},
}

def calc_min_capital(price):
    """最低必要資金を計算（スプレッド戦略ベース）"""
    if price < 30:
        return 150    # $1.5幅スプレッド × 100株
    elif price < 60:
        return 300    # $3幅スプレッド
    elif price < 100:
        return 500    # $5幅スプレッド
    elif price < 200:
        return 800    # $8幅スプレッド
    elif price < 400:
        return 1500   # $15幅スプレッド
    elif price < 800:
        return 3000   # $30幅スプレッド
    else:
        return 5000   # $50幅スプレッド

def calc_csp_capital(price):
    """CSP（現金確保プット）の必要資金"""
    return int(price * 100)

def get_capital_label(min_cap):
    """軍資金ラベルを返す"""
    if min_cap <= 300:
        return "💚 超少額OK"
    elif min_cap <= 800:
        return "🟡 少額OK"
    elif min_cap <= 1500:
        return "🟠 中額向け"
    else:
        return "🔴 大口向け"

def get_strategy_for_capital(capital, price, signal):
    """軍資金に応じた最適戦略を返す"""
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
    else:  # 買いチャンス
        if capital >= min_cap * 3:
            return "デビットコールスプレッド（余裕あり）", min_cap
        else:
            return "デビットコールスプレッド", min_cap

st.set_page_config(page_title="オプションチャンス スキャナー", page_icon="🔍", layout="wide")
st.title("🔍 オプションチャンス スキャナー")
st.caption("QQQ・S&P500の構成銘柄から今日のチャンスを自動発見")

# ========== モード・証券会社選択 ==========
col_mode, col_broker = st.columns(2)
with col_mode:
    mode = st.radio("表示モード", ["🔰 初心者モード", "📊 上級者モード"], horizontal=True)
with col_broker:
    broker = st.radio("使っている証券会社", ["🏦 サクソバンク証券", "📱 moomoo証券"], horizontal=True)

is_beginner = "初心者" in mode
is_saxo = "サクソバンク" in broker

if is_beginner:
    st.info("🔰 **初心者モード**：むずかしい用語はわかりやすく表示します")

st.divider()

# ========== 設定パネル ==========
col1, col2, col3 = st.columns(3)
with col1:
    universe = st.selectbox("対象ユニバース", ["QQQ上位30銘柄", "S&P500代表30銘柄"])
with col2:
    capital = st.number_input("💰 軍資金（ドル）", value=5000, step=1000, min_value=500)
with col3:
    top_n = st.number_input("上位何銘柄を表示", value=5, min_value=3, max_value=10)

# 軍資金ガイド表示
tier_label = ""
for name, tier in CAPITAL_TIERS.items():
    if tier["min"] <= capital < tier["max"]:
        tier_label = name
        break

if tier_label:
    st.info(f"💼 あなたの軍資金: **{tier_label}** → この資金でできる戦略のみ表示します")

# 軍資金別の戦略説明
with st.expander("📖 軍資金別 使える戦略ガイド"):
    st.markdown("""
    | 軍資金 | 使える戦略 | 対象銘柄の目安 |
    |--------|-----------|--------------|
    | $500〜$2,000 | デビットスプレッド（格安銘柄のみ） | $30以下の銘柄 |
    | $2,000〜$5,000 | デビットスプレッド・クレジットスプレッド | $200以下の銘柄 |
    | $5,000〜$15,000 | スプレッド全般・CSP（安い株のみ） | $400以下の銘柄 |
    | $15,000〜$30,000 | CSP・カバードコール・スプレッド | ほぼ全銘柄 |
    | $30,000〜 | 全戦略（IC・CSP・CC含む） | 全銘柄 |

    **💡 スプレッドとは？**
    2つのオプションを同時に売買することでリスクを限定する戦略。
    少ない資金でも始められるため、軍資金が少ない方の基本戦略です。
    """)

scan_btn = st.button("🔍 今日のチャンス銘柄をスキャン", type="primary", use_container_width=True)

def scan_ticker(ticker):
    """1銘柄のスキャン"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        name = info.get('shortName', ticker)

        # HV計算（30日）
        hist = stock.history(period='30d')
        if hist.empty or price is None:
            return None
        import numpy as np
        returns = hist['Close'].pct_change().dropna()
        hv = float(returns.std() * (252 ** 0.5))

        # IV取得（最短オプション）
        expirations = stock.options
        if not expirations:
            return None

        # 20日以上先の満期日を選ぶ
        target_exp = None
        for exp in expirations:
            exp_dt = datetime.strptime(exp, '%Y-%m-%d')
            if exp_dt > datetime.now() + timedelta(days=20):
                target_exp = exp
                break
        if not target_exp:
            return None

        opt = stock.option_chain(target_exp)
        puts = opt.puts
        calls = opt.calls
        if puts.empty or 'impliedVolatility' not in puts.columns:
            return None

        puts['distance'] = abs(puts['strike'] - price)
        atm_puts = puts.nsmallest(3, 'distance')
        iv = float(atm_puts['impliedVolatility'].mean())

        # ATMプレミアム（コール）
        atm_call_premium = None
        if not calls.empty:
            calls['distance'] = abs(calls['strike'] - price)
            atm_calls = calls.nsmallest(3, 'distance')
            atm_call_premium = float(atm_calls.iloc[0]['lastPrice']) if len(atm_calls) > 0 else None

        # スコアリング
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

        # 軍資金関連
        min_cap = calc_min_capital(price)
        csp_cap = calc_csp_capital(price)
        cap_label = get_capital_label(min_cap)

        return {
            'ticker': ticker,
            'name': name,
            'price': price,
            'iv': iv,
            'hv': hv,
            'iv_hv_ratio': iv_hv_ratio,
            'signal': signal,
            'strategy': strategy,
            'score': score,
            'expiry': target_exp,
            'atm_put_strike': float(atm_puts.iloc[0]['strike']) if len(atm_puts) > 0 else None,
            'atm_put_premium': float(atm_puts.iloc[0]['lastPrice']) if len(atm_puts) > 0 else None,
            'atm_call_premium': atm_call_premium,
            'min_capital': min_cap,
            'csp_capital': csp_cap,
            'capital_label': cap_label,
        }
    except Exception as e:
        return None

if scan_btn:
    tickers = QQQ_TOP30 if "QQQ" in universe else SP500_TOP30

    st.info(f"🔄 {len(tickers)}銘柄をスキャン中... 約1〜2分かかります")
    progress = st.progress(0)
    status = st.empty()

    results = []
    for i, ticker in enumerate(tickers):
        status.text(f"スキャン中: {ticker} ({i+1}/{len(tickers)})")
        r = scan_ticker(ticker)
        if r:
            results.append(r)
        progress.progress((i + 1) / len(tickers))
        time.sleep(0.3)

    progress.empty()
    status.empty()

    if not results:
        st.error("データを取得できませんでした")
        st.stop()

    df = pd.DataFrame(results).sort_values('score', ascending=False)

    # ========== 軍資金フィルター適用 ==========
    df_affordable = df[df['min_capital'] <= capital].copy()
    df_toomuch = df[df['min_capital'] > capital].copy()

    st.success(f"✅ スキャン完了！{len(results)}銘柄を分析 → あなたの軍資金（${capital:,}）で**{len(df_affordable)}銘柄**が対象")

    # ========== あなたの軍資金でできる銘柄（メイン） ==========
    st.subheader(f"💰 軍資金 ${capital:,} で今すぐできる銘柄")

    if df_affordable.empty:
        st.warning("現在の軍資金では対象銘柄がありません。もう少し資金を増やすか、スキャン対象を変更してください。")
    else:
        # チャンス銘柄を絞る
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

    # ========== 全銘柄サマリー表 ==========
    st.subheader("📊 全銘柄スキャン結果")
    summary_cols = ['ticker', 'name', 'price', 'iv', 'hv', 'iv_hv_ratio', 'capital_label', 'min_capital', 'signal', 'strategy']
    display_df = df[summary_cols].head(20).copy()
    display_df['price'] = display_df['price'].apply(lambda x: f"${x:.2f}")
    display_df['iv'] = display_df['iv'].apply(lambda x: f"{x:.1%}")
    display_df['hv'] = display_df['hv'].apply(lambda x: f"{x:.1%}")
    display_df['iv_hv_ratio'] = display_df['iv_hv_ratio'].apply(lambda x: f"{x:.2f}")
    display_df['min_capital'] = display_df['min_capital'].apply(lambda x: f"${x:,}")

    # 資金不足の行をグレーアウト（背景色）
    display_df.columns = ['ティッカー', '会社名', '株価', 'IV', 'HV', 'IV/HV比', '資金目安', '最低必要資金', 'シグナル', '推奨戦略']
    st.dataframe(display_df, use_container_width=True)

    # ========== 資金が足りない銘柄（参考） ==========
    if not df_toomuch.empty:
        with st.expander(f"⚠️ 資金不足で今回対象外の銘柄（{len(df_toomuch)}銘柄）"):
            st.caption("これらは今の軍資金では難しいですが、資金を増やせばチャレンジできます")
            for _, row in df_toomuch.head(5).iterrows():
                st.write(f"**{row['ticker']}** ({row['name']}) - 株価: ${row['price']:.2f} | 最低必要: ${row['min_capital']:,} | {row['signal']}")

    # ========== AI総合分析 ==========
    st.subheader("🤖 Claude AI 総合分析レポート")
    with st.spinner("AIが軍資金に合わせた戦略を分析中..."):
        top5 = df_affordable.head(5) if not df_affordable.empty else df.head(5)
        scan_summary = top5[['ticker', 'price', 'iv', 'hv', 'iv_hv_ratio', 'signal', 'strategy', 'min_capital']].to_string()

        broker_name = "サクソバンク証券" if is_saxo else "moomoo証券"
        level_note = "初心者向けに、専門用語にはカッコで説明を付け、小学生でもわかる言葉で書いてください。" if is_beginner else "上級者向けに、専門用語・ギリシャ文字・数値を積極的に使って分析してください。"

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = f"""あなたは米国株オプション取引の専門家です。

以下は{universe}のスキャン結果です。
**軍資金（運用資金）: ${capital:,}**
**使用証券会社: {broker_name}**
本日: {datetime.now().strftime('%Y年%m月%d日')}
{level_note}

【軍資金 ${capital:,} で対象の銘柄】
{scan_summary}

この軍資金（${capital:,}）に合わせて、以下を日本語で分析してください：

## 📈 今日の市場環境まとめ

[全体的なIV水準から見た市場環境。軍資金${capital:,}にとってどんな環境か]

## 🏆 最優先で狙うべき銘柄 TOP3（軍資金${capital:,}向け）

各銘柄について：
### 1位: [ティッカー]（[会社名]）
- **なぜ今日チャンスか：** [IVとHVのデータ根拠]
- **推奨戦略：** [軍資金${capital:,}に最適な具体的戦略]
- **ストライク目安：** 現在株価$〇〇の約〇%[上/下]
- **スプレッド幅：** $〇〇（必要資金: $〇〇）
- **満期日：** [日付]
- **目安プレミアム：** $〇〇〜$〇〇（手取り/支払い）
- **最大損失：** $〇〇
- **リスク：** [一言]

### 2位: [ティッカー]
[同様]

### 3位: [ティッカー]
[同様]

## ⚠️ 今日避けるべき銘柄・状況

[注意事項]

## 💼 ${capital:,}での資金配分アドバイス

[どの銘柄にいくら配分するか。具体的な金額で]
"""
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        st.markdown(msg.content[0].text)

    st.caption(f"スキャン完了: {datetime.now().strftime('%Y/%m/%d %H:%M')} | データソース: Yahoo Finance")

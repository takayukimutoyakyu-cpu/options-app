import streamlit as st
from futu import *
import anthropic
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

ANTHROPIC_API_KEY = "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"

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

# ========== 用語解説（初心者モード用） ==========
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

st.set_page_config(page_title="オプション作戦ナビ", page_icon="📈", layout="centered")
st.title("📈 オプション作戦ナビ")
st.caption("企業名を入れるだけで、今日やることがわかる")

# ========== モード・証券会社選択 ==========
col_mode, col_broker = st.columns(2)
with col_mode:
    mode = st.radio("表示モード", ["🔰 初心者モード", "📊 上級者モード"], horizontal=True)
with col_broker:
    broker = st.radio("使っている証券会社", ["🏦 サクソバンク証券", "📱 moomoo証券"], horizontal=True)

is_beginner = "初心者" in mode
is_saxo = "サクソバンク" in broker

if is_beginner:
    st.info("🔰 **初心者モード**：難しい用語はわかりやすく説明します。オプション初心者の方はこちら。")

# 初心者向け用語辞典
if is_beginner:
    with st.expander("📖 わからない用語はここで確認！"):
        for term, desc in GLOSSARY.items():
            st.markdown(f"**{term}**")
            st.caption(desc)
            st.divider()

st.divider()

# ========== 入力欄 ==========
company = st.text_input(
    "企業名またはティッカーを入力",
    placeholder="例：テスラ、アップル、NVDA、META..."
)
capital = st.number_input("💰 軍資金（ドル）", value=5000, step=1000, min_value=500)
go = st.button("今日の作戦を見る 🚀", type="primary", use_container_width=True)

def get_yahoo_data(ticker):
    result = {}
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        result['price'] = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        result['company_name'] = info.get('shortName', ticker)
        result['sector'] = info.get('sector', '不明')
        result['iv'] = None
        result['historical_volatility'] = None
        result['week52_high'] = info.get('fiftyTwoWeekHigh')
        result['week52_low'] = info.get('fiftyTwoWeekLow')

        hist = stock.history(period='30d')
        if not hist.empty:
            import numpy as np
            returns = hist['Close'].pct_change().dropna()
            hv = returns.std() * (252 ** 0.5)
            result['historical_volatility'] = hv

        expirations = stock.options
        result['expirations'] = list(expirations[:8]) if expirations else []

        target_date = datetime.now() + timedelta(days=35)
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
            if not puts.empty and 'impliedVolatility' in puts.columns:
                if result['price']:
                    puts['distance'] = abs(puts['strike'] - result['price'])
                    atm_puts = puts.nsmallest(10, 'distance')
                    result['puts_sample'] = atm_puts[['strike', 'lastPrice', 'impliedVolatility', 'volume', 'openInterest']].to_string()
                    result['put_iv_avg'] = atm_puts['impliedVolatility'].mean()
                    result['put_iv_atm'] = atm_puts.iloc[0]['impliedVolatility'] if len(atm_puts) > 0 else None

            calls = opt.calls
            if not calls.empty and 'impliedVolatility' in calls.columns:
                if result['price']:
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

def get_moomoo_expiry(ticker):
    try:
        quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        ret, expiry_data = quote_ctx.get_option_expiration_date(code=f'US.{ticker}')
        quote_ctx.close()
        if ret == RET_OK:
            return expiry_data['strike_time'].tolist()[:8]
    except:
        pass
    return []

def build_broker_steps(ticker, strategy_hint, expiry, price, broker_is_saxo, is_beginner_mode):
    """証券会社別の注文手順を生成"""
    if broker_is_saxo:
        steps = f"""
### 🏦 サクソバンク証券での注文手順

**【ステップ1】サクソバンクにログイン**
- PC: [saxotrader.com](https://www.home.saxo/ja-jp) にアクセス → ログイン
- スマホ: SaxoTraderGO アプリを開く

**【ステップ2】銘柄を検索**
- 検索バーに **{ticker}** と入力
- 「オプション」タブを選択

**【ステップ3】オプション画面を開く**
- 満期日 **{expiry}** を選択
- 現在株価 **${price:.2f}** 付近のストライクを探す

**【ステップ4】注文を入力**
- 戦略に応じた買い/売りを選択
- 数量: 1枚（1契約 = 株100株分）から開始

**【ステップ5】注文確認・送信**
- 注文内容を確認（ストライク・満期・枚数・指値/成行）
- 「注文確定」ボタンを押す
"""
        if is_beginner_mode:
            steps += """
> 💡 **初心者メモ**: サクソバンクは「オプション取引」の申請が必要な場合があります。まだの方はサポートに連絡してください。
"""
    else:
        steps = f"""
### 📱 moomoo証券での注文手順

**【ステップ1】moomooアプリを開く**
- スマホのmoomooアプリを起動

**【ステップ2】銘柄を検索**
- 下のメニュー「マーケット」→ 検索に **{ticker}** と入力

**【ステップ3】オプション画面に移動**
- 銘柄ページの上部タブ「オプション」をタップ
- 満期日 **{expiry}** を選択

**【ステップ4】注文を入力**
- 現在株価 **${price:.2f}** 付近のストライクを選択
- 「買い」または「売り」を選択
- 数量を入力（1枚から）

**【ステップ5】注文確認・送信**
- 「注文確認」→「送信」
"""
        if is_beginner_mode:
            steps += """
> 💡 **初心者メモ**: moomooは「高度な取引」設定をONにしないとオプションが表示されない場合があります。設定→取引設定から確認しましょう。
"""
    return steps

if go and company:
    ticker = TICKER_MAP.get(company.lower(), company.upper())

    with st.spinner(f"{ticker} のリアルタイムデータを取得中..."):
        ydata, yerr = get_yahoo_data(ticker)
        moomoo_expiry = get_moomoo_expiry(ticker)

    # ========== データ表示 ==========
    if ydata:
        price = ydata.get('price', 0)
        iv = ydata.get('iv')
        hv = ydata.get('historical_volatility')
        expiry = ydata.get('target_expiry', '---')

        # 今日やること（大きく1行）
        if iv and hv:
            if iv > hv * 1.3:
                action = "💰 今日は「売り戦略」のチャンス！プレミアムを受け取ろう"
                action_color = "success"
            elif iv < hv * 0.8:
                action = "📈 今日は「買い戦略」のチャンス！上昇に乗ろう"
                action_color = "info"
            else:
                action = "👀 今日は様子見が無難。急いで入らなくてOK"
                action_color = "warning"
        else:
            action = "📊 データ取得中..."
            action_color = "info"

        if action_color == "success":
            st.success(f"### {action}")
        elif action_color == "info":
            st.info(f"### {action}")
        else:
            st.warning(f"### {action}")

        # データ表示
        with st.expander("📊 リアルタイムデータを確認する"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("現在株価", f"${price:.2f}" if price else "---")
            with c2:
                iv_val = ydata.get('iv')
                st.metric("IV（オプションの割高感）", f"{iv_val:.1%}" if iv_val else "---")
                if is_beginner and iv_val:
                    if iv_val > 0.4:
                        st.caption("📌 高め → オプションが割高 → 売り有利")
                    elif iv_val < 0.2:
                        st.caption("📌 低め → オプションが割安 → 買い有利")
                    else:
                        st.caption("📌 普通水準")
            with c3:
                hv_val = ydata.get('historical_volatility')
                st.metric("HV（実際の価格変動）", f"{hv_val:.1%}" if hv_val else "---")

            st.write(f"**会社名:** {ydata.get('company_name')}　|　**セクター:** {ydata.get('sector')}")
            st.write(f"**52週高値:** ${ydata.get('week52_high', '---')}　/　**52週安値:** ${ydata.get('week52_low', '---')}")
            st.write(f"**推奨満期日:** {expiry}")

            if not is_beginner:
                if ydata.get('puts_sample'):
                    st.write("**ATM付近のPutオプション:**")
                    st.code(ydata['puts_sample'])
                if ydata.get('calls_sample'):
                    st.write("**ATM付近のCallオプション:**")
                    st.code(ydata['calls_sample'])

    # AIデータ構築
    if ydata:
        iv = ydata.get('iv')
        hv = ydata.get('historical_volatility')
        iv_str = f"{iv:.1%}" if iv else '不明'
        hv_str = f"{hv:.1%}" if hv else '不明'
        iv_rank_comment = ""
        if iv and hv:
            if iv > hv * 1.3:
                iv_rank_comment = "IVがHVより30%以上高い → オプション売り戦略が有利"
            elif iv < hv * 0.8:
                iv_rank_comment = "IVがHVより低い → オプション買い戦略が有利"
            else:
                iv_rank_comment = "IVとHVが近い → どちらの戦略も検討可"

        market_data = f"""
現在株価: ${ydata.get('price')}
会社名: {ydata.get('company_name')}
IV: {iv_str} / HV: {hv_str}
IV分析: {iv_rank_comment}
Put ATM IV: {f"{ydata['put_iv_atm']:.1%}" if ydata.get('put_iv_atm') else '不明'}
推奨満期日: {ydata.get('target_expiry', '不明')}
52週高値: ${ydata.get('week52_high')} / 安値: ${ydata.get('week52_low')}
--- ATM付近Putオプション ---
{ydata.get('puts_sample', 'データなし')}
--- ATM付近Callオプション ---
{ydata.get('calls_sample', 'データなし')}
"""
    else:
        market_data = f"データ取得エラー: {yerr}"

    # AI分析
    with st.spinner("Claude AIが最適な作戦を考えています..."):
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        level_instruction = """
初心者向けに説明してください：
- 専門用語には必ずカッコで簡単な説明を付ける（例：IV（オプションの割高感）、HV（実際の変動の大きさ））
- 小学5年生でもわかる言葉で戦略を説明する
- 「なぜこの戦略か」を具体的に説明する
""" if is_beginner else """
上級者向けに説明してください：
- ギリシャ文字（デルタ・ベガ等）や専門用語は略さず使う
- IVパーセンタイルやRVとの比較コメントも含める
"""

        broker_instruction = "サクソバンク証券" if is_saxo else "moomoo証券"

        prompt = f"""あなたは米国株オプション取引の専門家です。

【銘柄】{ticker}
【運用資金】${capital:,}
【使用証券会社】{broker_instruction}

{market_data}

{level_instruction}

戦略選択基準：
- IV > 30% かつ IV > HV → 売り戦略（CSP・CC・IC・クレジットスプレッド）
- IV < 20% または IV < HV → 買い戦略（デビットスプレッド）
- 資金 < $5,000 → スプレッド必須（CSPは資金不足になる可能性大）
- 資金 $5,000〜$15,000 → CSP（安い銘柄のみ）またはスプレッド
- 資金 > $15,000 → IC・CSP・CC選択可

以下のフォーマットで日本語で答えてください：

## {ticker}（{ydata.get('company_name', ticker) if ydata else ticker}）の今日の作戦

### 🎯 おすすめ戦略：[戦略名]

**選んだ理由：**
- 現在株価：$[実際の値]
- IV：[実際の値]% → [高い/低い] → [売り/買い]戦略が有利
- HV比較：[コメント]
- 資金効率：[${capital:,}に対するコメント]
- 相場ポジション：[52週高値・安値との比較]

[戦略の説明（初心者モードの場合は小学生向けに2〜3行）]

---

### 📋 注文の内容（具体的な数字）

| 項目 | 内容 |
|------|------|
| 戦略 | [戦略名] |
| 銘柄 | {ticker} |
| 満期日 | {ydata.get('target_expiry', '確認') if ydata else '確認'} |
| ストライク | $[具体的な値] |
| 受け取れるプレミアム | $[値]〜$[値] |
| 最大利益 | $[値] |
| 最大損失 | $[値] |
| 必要資金 | $[値] |

---

### 💰 お金のシミュレーション

[${capital:,}で何枚入れるか、いくら稼げる可能性があるか、最悪いくら失うか]

---

### ⚠️ こうなったら注意！

損切りルール：[具体的なルール]

---

### 📅 スケジュール

| イベント | 日付 |
|---------|------|
| 注文する日 | 今日 |
| 満期日 | {ydata.get('target_expiry', '確認') if ydata else '確認'} |
| 利確の目安 | プレミアムが50%減少した時点 |

---

### 💡 今の相場環境コメント

[IVとHVの実データを使ったコメント]
"""

        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        advice = message.content[0].text

    st.success(f"✅ {ticker} の作戦ができました！")
    st.markdown(advice)

    # 証券会社別の注文手順
    st.divider()
    if ydata:
        broker_steps = build_broker_steps(
            ticker=ticker,
            strategy_hint=advice[:100],
            expiry=ydata.get('target_expiry', '---'),
            price=ydata.get('price', 0),
            broker_is_saxo=is_saxo,
            is_beginner_mode=is_beginner
        )
        st.markdown(broker_steps)

    # サマリー
    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("銘柄", ticker)
    with c2:
        st.metric("軍資金", f"${capital:,}")
    with c3:
        st.metric("証券会社", "サクソバンク" if is_saxo else "moomoo")

elif go and not company:
    st.warning("企業名を入力してください")
else:
    broker_name = "サクソバンク証券" if "サクソバンク" in str(st.session_state.get("broker", "")) else "moomoo証券"
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

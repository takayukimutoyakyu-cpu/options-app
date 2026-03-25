import streamlit as st
import anthropic

ANTHROPIC_API_KEY = "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"

st.set_page_config(page_title="オプション戦略ガイド", page_icon="📚", layout="wide")
st.title("📚 オプション戦略ガイド")
st.caption("相場環境を選ぶだけで、最適な戦略と組み方がわかる")

# ============================
# 戦略データベース
# ============================
STRATEGIES = {
    ("上昇", "高い"): [
        {
            "name": "ブル・プット・スプレッド（Bull Put Spread）",
            "nickname": "下に保険つき プット売り",
            "description": "株が上がると思うとき、下に保険をかけながらプレミアムをもらう戦略",
            "legs": [
                {"action": "売り（Sell）", "type": "Put", "strike": "現在株価の約5〜10%下", "example": "株価$400なら → P$380を売る"},
                {"action": "買い（Buy）", "type": "Put", "strike": "売りより$10〜20下", "example": "P$360を買う（保険）"},
            ],
            "profit": "受取プレミアム全額",
            "loss": "スプレッド幅 − プレミアム",
            "win_rate": "70〜80%",
            "best_iv": "IVが高いほど有利",
            "example_trade": "株価$400 / P$380売り + P$360買い / プレミアム$3受取 / 最大利益$300 / 最大損失$1,700",
            "emoji": "📈"
        },
        {
            "name": "キャッシュセキュアードプット（Cash Secured Put）",
            "nickname": "安く買いたい人のプット売り",
            "description": "株を安く買いたいとき、プットを売ってプレミアムをもらいながら待つ戦略",
            "legs": [
                {"action": "売り（Sell）", "type": "Put", "strike": "買いたい価格", "example": "株価$400 / 買いたい価格$370 → P$370を売る"},
            ],
            "profit": "受取プレミアム全額",
            "loss": "ストライク − プレミアム（株を買わされた場合）",
            "win_rate": "70〜80%",
            "best_iv": "IVが高いほどプレミアムが大きい",
            "example_trade": "株価$400 / P$370売り / プレミアム$5受取 / 実質取得価格$365 / 必要資金$37,000",
            "emoji": "💰"
        },
        {
            "name": "ブル・コール・スプレッド（Bull Call Spread）",
            "nickname": "上昇限定の コール買い",
            "description": "株が上がると思うとき、コストを抑えながら上昇の利益を狙う戦略",
            "legs": [
                {"action": "買い（Buy）", "type": "Call", "strike": "現在株価付近（ATM）", "example": "株価$400 → C$400を買う"},
                {"action": "売り（Sell）", "type": "Call", "strike": "目標株価付近", "example": "C$430を売る（コスト削減）"},
            ],
            "profit": "スプレッド幅 − 支払プレミアム",
            "loss": "支払プレミアム全額",
            "win_rate": "40〜55%",
            "best_iv": "IVが低いほど有利（安く買える）",
            "example_trade": "株価$400 / C$400買い + C$430売り / 支払$8 / 最大利益$2,200 / 最大損失$800",
            "emoji": "🚀"
        },
    ],
    ("上昇", "低い"): [
        {
            "name": "ブル・コール・スプレッド（Bull Call Spread）",
            "nickname": "上昇限定の コール買い",
            "description": "IVが低いとき、コールを安く買えるチャンス。株の上昇で利益を狙う",
            "legs": [
                {"action": "買い（Buy）", "type": "Call", "strike": "現在株価付近（ATM）", "example": "株価$400 → C$400を買う"},
                {"action": "売り（Sell）", "type": "Call", "strike": "目標株価付近", "example": "C$430を売る（コスト削減）"},
            ],
            "profit": "スプレッド幅 − 支払プレミアム",
            "loss": "支払プレミアム全額",
            "win_rate": "40〜55%",
            "best_iv": "IVが低いとき特に有利",
            "example_trade": "株価$400 / C$400買い + C$430売り / 支払$6 / 最大利益$2,400 / 最大損失$600",
            "emoji": "🚀"
        },
        {
            "name": "カバードコール（Covered Call）",
            "nickname": "持ち株で おこづかい稼ぎ",
            "description": "すでに株を持っているとき、コールを売ってプレミアムをもらう戦略",
            "legs": [
                {"action": "保有", "type": "株（100株）", "strike": "―", "example": "AAPL 100株保有"},
                {"action": "売り（Sell）", "type": "Call", "strike": "現在株価の5〜10%上", "example": "株価$400 → C$430を売る"},
            ],
            "profit": "受取プレミアム（株が上がりすぎると機会損失）",
            "loss": "株価下落分（プレミアム分は相殺）",
            "win_rate": "70〜80%",
            "best_iv": "IVが高いほどプレミアムが大きい",
            "example_trade": "AAPL 100株保有 / C$430売り / プレミアム$4受取（$400/月） / 年利換算約12%",
            "emoji": "🏦"
        },
    ],
    ("横ばい", "高い"): [
        {
            "name": "アイアンコンドル（Iron Condor）",
            "nickname": "上にも下にも動かない 最強戦略",
            "description": "株が大きく動かないと思うとき、上下両方にプレミアムをもらう戦略",
            "legs": [
                {"action": "売り（Sell）", "type": "Put", "strike": "現在株価の10%下", "example": "株価$400 → P$360を売る"},
                {"action": "買い（Buy）", "type": "Put", "strike": "売りより$20下", "example": "P$340を買う（保険）"},
                {"action": "売り（Sell）", "type": "Call", "strike": "現在株価の10%上", "example": "C$440を売る"},
                {"action": "買い（Buy）", "type": "Call", "strike": "売りより$20上", "example": "C$460を買う（保険）"},
            ],
            "profit": "両側から受取プレミアム合計",
            "loss": "スプレッド幅 − 受取プレミアム合計",
            "win_rate": "70〜85%",
            "best_iv": "IVが高いとき最強（プレミアムが大きい）",
            "example_trade": "株価$400 / P$360-$340 + C$440-$460 / プレミアム計$8受取 / 最大利益$800 / 最大損失$1,200",
            "emoji": "🦅"
        },
        {
            "name": "ショートストラングル（Short Strangle）",
            "nickname": "保険なしの 強気コンドル",
            "description": "IVが極めて高いとき、保険なしでプットとコールを両方売る（上級者向け）",
            "legs": [
                {"action": "売り（Sell）", "type": "Put", "strike": "現在株価の10〜15%下", "example": "株価$400 → P$340を売る"},
                {"action": "売り（Sell）", "type": "Call", "strike": "現在株価の10〜15%上", "example": "C$460を売る"},
            ],
            "profit": "受取プレミアム全額（大きい）",
            "loss": "理論上無限大（必ず損切りルール必要）",
            "win_rate": "75〜85%",
            "best_iv": "IVが非常に高いとき限定",
            "example_trade": "株価$400 / P$340売り + C$460売り / プレミアム計$15受取 / ⚠️上級者向け",
            "emoji": "⚡"
        },
    ],
    ("横ばい", "低い"): [
        {
            "name": "カレンダースプレッド（Calendar Spread）",
            "nickname": "時間を利用する 時間差戦略",
            "description": "株が横ばいで、IVが低いとき。近い満期と遠い満期の時間差を利用する",
            "legs": [
                {"action": "売り（Sell）", "type": "Call（近い満期）", "strike": "現在株価付近（ATM）", "example": "株価$400 → C$400（来月満期）を売る"},
                {"action": "買い（Buy）", "type": "Call（遠い満期）", "strike": "同じストライク", "example": "C$400（3ヶ月後満期）を買う"},
            ],
            "profit": "近い満期のプレミアム収入（毎月繰り返す）",
            "loss": "支払プレミアム差額",
            "win_rate": "50〜65%",
            "best_iv": "IVが低いとき、将来のIV上昇を期待",
            "example_trade": "株価$400 / C$400 近い売り$5 + 遠い買い$10 / 差額$5支払 / 毎月ロールで利益積み上げ",
            "emoji": "📅"
        },
    ],
    ("下落", "高い"): [
        {
            "name": "ベア・コール・スプレッド（Bear Call Spread）",
            "nickname": "上に保険つき コール売り",
            "description": "株が下がると思うとき、コールを売ってプレミアムをもらう戦略",
            "legs": [
                {"action": "売り（Sell）", "type": "Call", "strike": "現在株価の5〜10%上", "example": "株価$400 → C$430を売る"},
                {"action": "買い（Buy）", "type": "Call", "strike": "売りより$20上", "example": "C$450を買う（保険）"},
            ],
            "profit": "受取プレミアム全額",
            "loss": "スプレッド幅 − プレミアム",
            "win_rate": "65〜75%",
            "best_iv": "IVが高いほど有利",
            "example_trade": "株価$400 / C$430売り + C$450買い / プレミアム$4受取 / 最大利益$400 / 最大損失$1,600",
            "emoji": "📉"
        },
        {
            "name": "ロング・プット（Long Put）",
            "nickname": "下落で 大きく稼ぐ",
            "description": "株が大きく下がると確信しているとき、プットを買って下落で利益を狙う",
            "legs": [
                {"action": "買い（Buy）", "type": "Put", "strike": "現在株価付近（ATM）", "example": "株価$400 → P$400を買う"},
            ],
            "profit": "ストライク − 株価 − プレミアム（大きな下落で大利益）",
            "loss": "支払プレミアム全額",
            "win_rate": "30〜45%",
            "best_iv": "IVが低いとき（安く買える）",
            "example_trade": "株価$400 / P$400買い / プレミアム$15支払 / 株価$350なら利益$3,500",
            "emoji": "🔻"
        },
    ],
    ("下落", "低い"): [
        {
            "name": "ベア・プット・スプレッド（Bear Put Spread）",
            "nickname": "下落限定の プット買い",
            "description": "株が下がると思うとき、コストを抑えながら下落の利益を狙う",
            "legs": [
                {"action": "買い（Buy）", "type": "Put", "strike": "現在株価付近（ATM）", "example": "株価$400 → P$400を買う"},
                {"action": "売り（Sell）", "type": "Put", "strike": "目標株価付近", "example": "P$370を売る（コスト削減）"},
            ],
            "profit": "スプレッド幅 − 支払プレミアム",
            "loss": "支払プレミアム全額",
            "win_rate": "40〜55%",
            "best_iv": "IVが低いとき（安く買える）",
            "example_trade": "株価$400 / P$400買い + P$370売り / 支払$7 / 最大利益$2,300 / 最大損失$700",
            "emoji": "📊"
        },
    ],
}

# ============================
# UI
# ============================
st.subheader("① 相場環境を選んでください")
col1, col2 = st.columns(2)
with col1:
    outlook = st.radio("株価の方向感", ["上昇", "横ばい", "下落"],
        captions=["上がると思う", "あまり動かないと思う", "下がると思う"])
with col2:
    iv_level = st.radio("IVの水準",["高い", "低い"],
        captions=["IV > 30%（プレミアムが高い）", "IV < 20%（プレミアムが低い）"])

st.divider()

# 戦略を取得
key = (outlook, iv_level)
strategies = STRATEGIES.get(key, [])

if strategies:
    st.subheader(f"② {outlook}相場 × IV{iv_level} で使える戦略")

    for i, s in enumerate(strategies):
        with st.expander(f"{s['emoji']} {s['name']}（{s['nickname']}）", expanded=(i==0)):

            st.write(f"**概要:** {s['description']}")

            st.subheader("📋 注文の組み方")
            for leg in s['legs']:
                st.markdown(f"""
| 項目 | 内容 |
|------|------|
| アクション | {leg['action']} |
| 種類 | {leg['type']} |
| ストライク | {leg['strike']} |
| 具体例 | {leg['example']} |
""")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("最大利益", s['profit'])
            col2.metric("最大損失", s['loss'])
            col3.metric("勝率目安", s['win_rate'])
            col4.metric("IV環境", s['best_iv'])

            st.info(f"💡 **具体的な注文例:** {s['example_trade']}")

    # AI解説
    st.divider()
    st.subheader("③ 今日の相場でどの戦略を使うか、AIに相談する")

    ticker_input = st.text_input("銘柄を入力（任意）", placeholder="例: AAPL, TSLA, NVDA")
    capital = st.number_input("運用資金（ドル）", value=50000, step=5000)

    if st.button("AIに詳しく聞く", type="primary"):
        with st.spinner("Claude AIが分析中..."):
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            strategy_names = [s['name'] for s in strategies]

            prompt = f"""あなたは米国株オプション取引の専門家です。

状況:
- 相場見通し: {outlook}
- IV水準: {iv_level}
- 銘柄: {ticker_input if ticker_input else '未指定（一般的な解説）'}
- 運用資金: ${capital:,}
- 候補戦略: {', '.join(strategy_names)}

以下を日本語で、小学5年生でもわかるように教えてください：

## 今の相場環境（{outlook} × IV{iv_level}）での戦略選び

### 🥇 一番のおすすめ: [戦略名]
**理由:** [なぜこの戦略が今最適か、データ根拠付きで]

**小学生向け説明:**
[保険屋さんのたとえなど、わかりやすい言葉で]

### 📋 具体的な注文手順（moomooで）
【ステップ1】...
【ステップ2】...
【ステップ3】...
【ステップ4】 数字の例:
- 売りストライク: $〇〇（株価の約〇%下/上）
- 買いストライク: $〇〇（保険）
- 満期日: 今から約30〜45日後
- 受取プレミアム目安: $〇〇〜$〇〇

### 💰 ${capital:,}での資金計画
- 1枚あたり必要資金: $〇〇
- 推奨枚数: 〇枚（資金の〇%）
- 期待利益: $〇〇〜$〇〇

### ⚠️ 注意点・損切りルール
[具体的に]

### 🔄 他の候補戦略との比較
[残りの戦略を簡単に比較]
"""
            msg = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            st.markdown(msg.content[0].text)

else:
    st.info("相場環境を選んでください")

# 全戦略一覧チートシート
with st.expander("📑 全戦略チートシート（一覧）"):
    st.markdown("""
| 相場 | IV | 戦略 | 最大利益 | リスク |
|------|-----|------|---------|--------|
| 上昇↑ | 高 | ブル・プット・スプレッド | プレミアム | 限定 |
| 上昇↑ | 高 | キャッシュセキュアードプット | プレミアム | 株買い義務 |
| 上昇↑ | 低 | ブル・コール・スプレッド | スプレッド幅 | 限定 |
| 上昇↑ | 低 | カバードコール | プレミアム | 株価下落 |
| 横ばい→ | 高 | アイアンコンドル | 両側プレミアム | 限定 |
| 横ばい→ | 高 | ショートストラングル | 大きいプレミアム | 無限大⚠️ |
| 横ばい→ | 低 | カレンダースプレッド | 毎月収入 | 限定 |
| 下落↓ | 高 | ベア・コール・スプレッド | プレミアム | 限定 |
| 下落↓ | 低 | ベア・プット・スプレッド | スプレッド幅 | 限定 |
| 下落↓ | 低 | ロング・プット | 無限大 | プレミアム |
""")

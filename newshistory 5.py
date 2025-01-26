"""
===============================================================================
【论文级示例】比特币新闻情绪 & 行情数据分析：融合多关键词、多特征、回归模型
===============================================================================
说明：
  1) 通过 Bing News API 多关键字搜索（如 "Bitcoin AND Trump" 等），
     并对新闻做情绪分析（TextBlob）+ 主题标记（Trump、Government、War）。
  2) 结合 Yahoo Finance 提供的 BTC-USD 行情数据，做特征工程：
     - 日收益率 (DailyReturn)
     - 日内波动率 (Volatility)
     - 新闻情绪滞后 (AvgSentiment_lag1)
  3) 使用 statsmodels 进行回归分析 (OLS)，并输出详细统计结果（p 值、AIC、BIC等）。
  4) 可视化：时间序列图 & 相关系数热力图，辅助论文撰写和结果展示。
  5) 注意：若 Bing News API 获取到的新闻量非常少、或与所需日期不匹配，
     则需要换更长周期、付费 API 或其他新闻源。

运行方式：
  - 在命令行或 IDE 中直接执行脚本： python your_script.py
  - 输入开始和结束日期 (如：2023-01-01 ~ 2023-01-31)
  - 脚本将尝试在此日期范围内搜索新闻+下载币价数据，进行情绪与行情分析。

提示：
  - 需手动将 BING_API_KEY 替换为你自己的 Bing News API 有效密钥。
  - 若需要更多历史数据，请自行获取或付费使用更全的新闻 API。
===============================================================================
"""

import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from textblob import TextBlob
import statsmodels.api as sm
import matplotlib.pyplot as plt
import seaborn as sns

# ========== 全局配置，请改为自己的 Bing News API key ==========
BING_API_KEY = "ae368a2d3e1f42cf89a673d0f36b359b"

# ========== Bing News API 的封装函数 ==========
def fetch_bing_news(
    api_key,
    query="Bitcoin",
    market="en-US",
    count=100,
    freshness=None
):
    """
    通过 Bing News API 获取新闻（默认按 Date 排序）。
    参数:
      api_key: Bing News API 密钥 (string)
      query:   搜索关键词 (string)，可含布尔逻辑，例如 "Bitcoin AND Trump"
      market:  语言区域 (string, e.g. "en-US")
      count:   拉取新闻条数上限 (int)
      freshness: 可指定 "Day" / "Week" / "Month"，代表仅看最近 1天/7天/30天新闻
    返回:
      返回新闻对象列表 (list of dict)。若请求失败或无结果，返回 []。
    """
    url = "https://api.bing.microsoft.com/v7.0/news/search"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {
        "q": query,
        "mkt": market,
        "count": count,
        "sortBy": "Date"
    }
    if freshness:
        params["freshness"] = freshness

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data_json = response.json()
        return data_json.get("value", [])
    except Exception as e:
        print(f"[ERROR] fetch_bing_news: {e}")
        return []

# ========== 对新闻内容进行情绪分析 + 主题标记 ==========
def analyze_news_and_tag(news_list):
    """
    输入: news_list (List[dict])，来自 Bing News API。
    输出: DataFrame, 包含 [Date, Title, Description, Polarity, Trump, War, Government] 等。
    其中:
      - Polarity 为 TextBlob 计算的情绪极性分数 [-1, 1].
      - Trump/War/Government 为 0/1 标记，用于后续做回归特征。
    """
    records = []
    for news in news_list:
        # 获取日期
        raw_date = news.get("datePublished", None)
        if not raw_date:
            continue
        date = pd.to_datetime(raw_date).date()

        # 获取标题描述
        title = news.get("name", "")
        desc = news.get("description", "")
        # 可选：有些新闻还有 "url", "provider", "category"等字段
        full_content = f"{title}. {desc}"

        # 情绪分析
        polarity = TextBlob(full_content).sentiment.polarity

        # 标记主题 (简单字符串包含判断，可以改进成 NER/主题分类)
        trump_flag = 1 if ("trump" in full_content.lower()) else 0
        war_flag = 1 if ("war" in full_content.lower()) else 0
        gov_flag = 1 if ("government" in full_content.lower()) else 0

        records.append({
            "Date": date,
            "Title": title,
            "Description": desc,
            "Polarity": polarity,
            "Trump": trump_flag,
            "War": war_flag,
            "Government": gov_flag
        })

    df = pd.DataFrame(records)
    return df

# ========== Yahoo Finance 获取 BTC 行情数据 ==========
def fetch_crypto_data(symbol, start_date, end_date):
    """
    使用 yfinance 获取行情数据：Open, High, Low, Close, Volume, ...
    返回 DataFrame；若失败或无数据，返回空 DataFrame。
    """
    data = yf.download(symbol, start=start_date, end=end_date, progress=False)
    if data.empty:
        print("[WARNING] 行情数据为空。请检查日期或网络。")
        return pd.DataFrame()
    data.reset_index(inplace=True)
    # 将日期列设为 date 类型（非 datetime64）
    data["Date"] = data["Date"].dt.date
    return data

# ========== 特征工程 & 合并数据 ==========
def merge_and_engineer_features(df_news, df_crypto):
    """
    1) 对新闻按 Date 做聚合 (平均情绪)。
    2) 合并到行情数据 (BTC-USD)，并构建：
       - DailyReturn: 当日收盘价涨跌幅
       - Volatility: (High - Low)/Open
       - AvgSentiment_lag1: 前一天的情绪
    3) 将主题标记 (Trump/War/Government) 也做成当日最大值或总和等方式聚合。
    """
    if df_news.empty or df_crypto.empty:
        return pd.DataFrame()

    # 对同一天多篇新闻做聚合：平均情绪
    agg_dict = {
        "Polarity": "mean",
        "Trump": "max",        # 若有任何文章提到Trump，则当日置为1
        "War": "max",
        "Government": "max"
    }
    df_daily_news = df_news.groupby("Date", as_index=False).agg(agg_dict)
    df_daily_news.rename(columns={"Polarity": "AvgSentiment"}, inplace=True)

    # 按日期合并
    merged = pd.merge(df_crypto, df_daily_news, on="Date", how="left")
    merged.sort_values("Date", inplace=True)

    # 计算日收益率
    merged["DailyReturn"] = merged["Close"].pct_change()

    # 计算日内波动率
    merged["Volatility"] = (merged["High"] - merged["Low"]) / merged["Open"]

    # 填补没查到新闻的那天：AvgSentiment可能是NaN，此处可视情况填充为0或前值
    merged["AvgSentiment"] = merged["AvgSentiment"].fillna(0)

    # Trump/War/Gov 也做同样处理
    for col in ["Trump", "War", "Government"]:
        merged[col] = merged[col].fillna(0)

    # 创建情绪滞后列 (前一天)
    merged["AvgSentiment_lag1"] = merged["AvgSentiment"].shift(1)

    # 过滤掉无法计算涨跌幅 / 滞后情绪的第一行
    merged.dropna(subset=["DailyReturn", "AvgSentiment_lag1"], inplace=True)

    merged.reset_index(drop=True, inplace=True)
    return merged

# ========== 回归分析函数 (statsmodels) ==========
def run_regression(df, y_col="DailyReturn"):
    """
    1) 以 y_col (如 DailyReturn) 作为因变量
    2) 自变量 X 包含：AvgSentiment, AvgSentiment_lag1, Trump, War, Government, Volume, Volatility
    3) 打印回归结果 (OLS Summary) 供论文引用
    """
    # 若数据过少，无法做回归
    if len(df) < 10:
        print("[WARNING] 数据量过少，无法进行回归")
        return None

    # 构造自变量
    candidate_features = [
        "AvgSentiment",
        "AvgSentiment_lag1",
        "Trump",
        "War",
        "Government",
        "Volume",
        "Volatility"
    ]
    # 过滤掉确实存在的列
    X_cols = [c for c in candidate_features if c in df.columns]
    X = df[X_cols]
    Y = df[y_col]

    # 加上截距
    X = sm.add_constant(X)

    model = sm.OLS(Y, X).fit()
    print(f"\n{'='*60}")
    print(f"回归因变量: {y_col}")
    print(model.summary())
    print(f"{'='*60}\n")
    return model

# ========== 可视化：时间序列与相关系数 ==========
def plot_time_series(df):
    """
    绘制收盘价+情绪、日收益率+主题标记等时间序列图，供论文中放置。
    你可根据需求再增加更多子图/对比。
    """
    if df.empty:
        return

    # 图1: 价格 & 成交量 & 平均情绪
    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax2 = ax1.twinx()

    ax1.plot(df["Date"], df["Close"], label="BTC Close", color="blue", marker="o")
    ax1.set_ylabel("BTC Price (USD)", color="blue")
    ax1.tick_params(axis="y", labelcolor="blue")

    ax2.bar(df["Date"], df["Volume"], label="Volume", alpha=0.3, color="grey")
    ax2.set_ylabel("Volume", color="grey")
    ax2.tick_params(axis="y", labelcolor="grey")

    plt.title("比特币价格 & 成交量 时间序列")
    fig.tight_layout()
    plt.show()

    # 图2: 日收益率 & 平均情绪 (可叠加主题标记)
    fig, ax3 = plt.subplots(figsize=(12, 6))
    ax4 = ax3.twinx()

    ax3.plot(df["Date"], df["DailyReturn"], label="Daily Return", color="red", marker="s")
    ax3.set_ylabel("DailyReturn", color="red")
    ax3.tick_params(axis="y", labelcolor="red")

    ax4.plot(df["Date"], df["AvgSentiment"], label="AvgSentiment", color="green", marker="^")
    ax4.set_ylabel("Sentiment", color="green")
    ax4.tick_params(axis="y", labelcolor="green")

    plt.title("比特币日收益率 & 平均情绪 时间序列")
    fig.tight_layout()
    plt.show()

def plot_correlation_heatmap(df, cols=None):
    """
    相关系数热力图，可观察多变量间的线性相关性。
    """
    if df.empty:
        return
    if cols is None:
        # 根据你论文想讨论的特征，选择一组
        cols = ["Close", "Volume", "DailyReturn", "Volatility",
                "AvgSentiment", "AvgSentiment_lag1", "Trump", "War", "Government"]
        # 只保留实际存在且为数值类型的列
        cols = [c for c in cols if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]

    corr_matrix = df[cols].corr()
    plt.figure(figsize=(10, 8))
    sns.heatmap(corr_matrix, annot=True, fmt=".2f", cmap="RdBu_r", center=0)
    plt.title("多变量相关系数热力图")
    plt.tight_layout()
    plt.show()


# ========== 主程序入口 ==========
def main():
    print("==========【论文级】比特币情绪 & 政治/事件主题分析示例==========")
    start_date_str = input("请输入开始日期 (格式 YYYY-MM-DD): ")
    end_date_str = input("请输入结束日期 (格式 YYYY-MM-DD): ")

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")

    print(f"[INFO] 日期范围：{start_date.date()} 至 {end_date.date()}")

    # ========== 1) 多关键词检索新闻：Bitcoin AND (Trump / Government / War / ...) ==========
    # 这里可根据需要自由加关键词
    queries = [
        "Bitcoin",
        "Bitcoin AND Trump",
        "Bitcoin AND Government",
        "Bitcoin AND War"
    ]
    all_news = []
    for q in queries:
        # 根据freshness可拉近30天新闻 (Month) 或7天 (Week) 等
        news_list = fetch_bing_news(BING_API_KEY, q, count=100, freshness="Month")
        all_news.extend(news_list)

    # 去重：有些新闻可能在多个搜索里重复出现；用 url 做键
    dedup_dict = {}
    for item in all_news:
        if "url" in item:
            dedup_dict[item["url"]] = item
    unique_news_list = list(dedup_dict.values())

    print(f"[INFO] 多关键词合并后新闻总数: {len(unique_news_list)}")

    # 分析新闻情绪 + 主题标记
    df_news = analyze_news_and_tag(unique_news_list)
    # 只保留所需日期
    df_news = df_news[
        (df_news["Date"] >= start_date.date()) &
        (df_news["Date"] <= end_date.date())
    ]
    print(f"[INFO] 过滤后新闻数量: {len(df_news)}")

    # ========== 2) 获取 BTC 行情数据 ==========
    df_crypto = fetch_crypto_data("BTC-USD", start_date, end_date)
    if df_crypto.empty:
        print("[ERROR] 未能获取到行情数据，程序结束。")
        return

    print(f"[INFO] 获取到 {len(df_crypto)} 条 BTC 行情数据。")

    # ========== 3) 合并新闻 & 行情，进行特征工程 ==========
    merged_df = merge_and_engineer_features(df_news, df_crypto)
    print(f"[INFO] 合并后可用数据条数: {len(merged_df)}")

    if merged_df.empty:
        print("[ERROR] 合并后数据为空，无法进行后续分析。")
        return

    # ========== 4) 可视化 ==========
    plot_time_series(merged_df)
    plot_correlation_heatmap(merged_df)

    # ========== 5) 回归分析：以每日收益率为因变量 ==========
    print("\n[回归分析：预测 DailyReturn]")
    model_return = run_regression(merged_df, y_col="DailyReturn")

    # 你也可以再做另外一个回归，如：预测价格 Close 或 预测波动率
    print("\n[回归分析：预测 Volatility]")
    model_vol = run_regression(merged_df, y_col="Volatility")

    # 可将数据输出到 CSV 以备查阅或在论文中引用
    # merged_df.to_csv("merged_for_paper.csv", index=False)
    # print("[INFO] 已将最终合并数据保存到 merged_for_paper.csv")

    print("[INFO] 分析流程结束，如需更多统计或模型，可在此基础上扩展。")

# ========== 执行主函数 ==========

if __name__ == "__main__":
    main()

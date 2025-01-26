import feedparser
import urllib.parse
import pandas as pd


def crawl_google_news_rss(keyword, language="en-US", region="US"):
    """
    使用 Google News RSS Feed 拉取搜索结果:
      - keyword: 搜索关键词 (例如 "Bitcoin Crypto Musk")
      - language: 语言/本地化, 如 "en-US"
      - region: 地区, 如 "US"

    返回: 包含 [title, link, published, source, summary] 等字段的 DataFrame
    """

    # 组装 RSS URL，示例:
    #   https://news.google.com/rss/search?q=bitcoin+crypto+musk&hl=en-US&gl=US&ceid=US:en
    # 说明:
    #   q=  搜索关键词(支持+空格)
    #   hl= 指定语言(en-US)
    #   gl= 地区(US)
    #   ceid= Country & language(US:en)
    base_url = "https://news.google.com/rss/search"
    query_params = {
        "q": keyword,  # 搜索关键词
        "hl": language,  # 语言
        "gl": region,  # 地区
        "ceid": f"{region}:{language.split('-')[0]}"
    }
    url = base_url + "?" + urllib.parse.urlencode(query_params)

    print(f"[INFO] Fetching RSS from: {url}")

    # 解析 RSS
    feed = feedparser.parse(url)

    # 如果 feed['entries'] 为空，可能是网络或关键词无结果等原因
    entries = feed.get("entries", [])
    records = []
    for e in entries:
        title = e.get("title", "")
        link = e.get("link", "")
        published = e.get("published", "")  # 或 published_parsed
        summary = e.get("summary", "")

        # Google News RSS 中，来源通常在 'source' 或者 summary里含有
        # 但 feedparser 可能把 <source> ... </source> 解析为 e['source']['title']
        source = ""
        if "source" in e and "title" in e["source"]:
            source = e["source"]["title"]

        # 也可能解析出作者 e.get('author', '')

        records.append({
            "title": title,
            "link": link,
            "published": published,
            "source": source,
            "summary": summary
        })

    df = pd.DataFrame(records)
    return df


if __name__ == "__main__":
    # 示例：搜索 "Bitcoin Crypto Musk"
    keyword = "Bitcoin Crypto Musk"

    df_news = crawl_google_news_rss(keyword, language="en-US", region="US")
    print(f"[INFO] 抓到 {len(df_news)} 条新闻。")

    # 打印预览
    print(df_news.head(10))

    # 存储到 CSV
    df_news.to_csv("google_news_rss_results.csv", index=False, encoding="utf-8-sig")
    print("[INFO] 已保存至 google_news_rss_results.csv")

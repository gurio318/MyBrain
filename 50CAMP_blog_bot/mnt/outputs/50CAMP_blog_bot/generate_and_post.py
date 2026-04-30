#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
50CAMP ブログ自動化ボット
Claude API で記事生成 → WordPress REST API で自動投稿

使い方:
  python generate_and_post.py              # 1記事生成して下書き保存
  python generate_and_post.py --publish    # 1記事生成して即時公開
  python generate_and_post.py --count 3   # 3記事まとめて生成
  python generate_and_post.py --keyword "50代 副業 始め方"  # キーワード直接指定
"""

import argparse
import base64
import csv
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime

# config.py から設定を読み込む
try:
    from config import (
        CLAUDE_API_KEY, CLAUDE_MODEL,
        WP_URL, WP_USERNAME, WP_APP_PASS,
        WP_STATUS, WP_CATEGORY_ID, WP_DEFAULT_TAGS,
        ARTICLE_MAX_TOKENS, KEYWORDS_CSV, LOG_FILE, PERSONA
    )
except ImportError:
    print("❌ config.py が見つかりません。同じフォルダに config.py を置いてください。")
    sys.exit(1)


# ============================================================
#  キーワード管理
# ============================================================

def load_keywords(csv_path: str) -> list[dict]:
    """CSVからキーワード一覧を読み込む"""
    if not os.path.exists(csv_path):
        print(f"❌ {csv_path} が見つかりません。keywords.csv を作成してください。")
        sys.exit(1)

    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def get_next_keyword(csv_path: str) -> dict | None:
    """未使用のキーワードを1件取得する"""
    rows = load_keywords(csv_path)
    for row in rows:
        if row.get("status", "").strip().lower() not in ("done", "済", "完了"):
            return row
    return None


def mark_keyword_done(csv_path: str, keyword: str):
    """使用済みキーワードを「済」にマークする"""
    rows = load_keywords(csv_path)
    for row in rows:
        if row["keyword"] == keyword:
            row["status"] = "済"
            break

    # ヘッダーを保ちながら書き戻す
    fieldnames = list(rows[0].keys()) if rows else []
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
#  記事生成（Claude API）
# ============================================================

def build_prompt(keyword: str, monetize_type: str = "", product_name: str = "") -> str:
    """記事生成プロンプトを作成する"""

    monetize_note = ""
    if monetize_type:
        monetize_note = f"\n\nマネタイズ手法: {monetize_type}"
    if product_name:
        monetize_note += f"\n紹介する商品/サービス: {product_name}（記事内で自然に紹介してください。アフィリエイトリンクは [AFFILIATE_LINK_HERE] と書いておいてください）"

    return f"""{PERSONA}

---

以下のキーワードで、SEOを意識したブログ記事を書いてください。{monetize_note}

【ターゲットキーワード】
{keyword}

【記事の構成ルール】
1. タイトル（H1）: キーワードを含む・数字か感情ワードを入れる・32文字以内
2. リード文（200字）: 読者の悩みに共感するエピソードを入れる
3. 本文（H2・H3見出しで構成、合計1,500字以上）:
   - 具体的な体験・スクリーンショット説明・数字を混じえる
   - 難しい言葉は使わない
4. まとめ（200字）: 行動を促すCTAを入れる

【出力形式】
WordPressに貼れるHTML形式で出力してください。
<h1>、<h2>、<h3>、<p>、<ul><li>、<strong> タグを使用。
タイトルは <title>〜</title> タグで先頭に書いてください。
メタディスクリプション（120字以内）は <meta_description>〜</meta_description> タグで書いてください。
"""


def call_claude_api(prompt: str) -> str:
    """Claude API を呼び出して記事を生成する"""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    body = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": ARTICLE_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    print(f"  📡 Claude APIに接続中...")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            result = json.loads(res.read().decode("utf-8"))
            return result["content"][0]["text"]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"❌ Claude API エラー {e.code}: {error_body}")
        sys.exit(1)


def parse_article(raw: str) -> dict:
    """生成されたテキストからタイトル・本文・メタ説明を抽出する"""
    # タイトル
    title_match = re.search(r"<title>(.*?)</title>", raw, re.DOTALL)
    title = title_match.group(1).strip() if title_match else "50CAMPブログ記事"

    # メタディスクリプション
    meta_match = re.search(r"<meta_description>(.*?)</meta_description>", raw, re.DOTALL)
    meta_desc = meta_match.group(1).strip() if meta_match else ""

    # 本文（<title>と<meta_description>タグを除いた部分）
    content = raw
    content = re.sub(r"<title>.*?</title>", "", content, flags=re.DOTALL)
    content = re.sub(r"<meta_description>.*?</meta_description>", "", content, flags=re.DOTALL)
    content = content.strip()

    return {"title": title, "meta_description": meta_desc, "content": content}


# ============================================================
#  WordPress投稿（REST API）
# ============================================================

def get_or_create_tags(tag_names: list[str]) -> list[int]:
    """タグ名からWordPressのタグIDを取得（なければ作成）する"""
    tag_ids = []
    credentials = base64.b64encode(f"{WP_USERNAME}:{WP_APP_PASS}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json"
    }

    for name in tag_names:
        # タグ検索
        search_url = f"{WP_URL}/wp-json/wp/v2/tags?search={urllib.parse.quote(name)}&per_page=5"
        req = urllib.request.Request(search_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                tags = json.loads(res.read())
                matched = [t for t in tags if t["name"] == name]
                if matched:
                    tag_ids.append(matched[0]["id"])
                    continue
        except Exception:
            pass

        # タグ作成
        create_url = f"{WP_URL}/wp-json/wp/v2/tags"
        body = json.dumps({"name": name}).encode("utf-8")
        req = urllib.request.Request(create_url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                new_tag = json.loads(res.read())
                tag_ids.append(new_tag["id"])
        except Exception as e:
            print(f"  ⚠️ タグ「{name}」の作成に失敗: {e}")

    return tag_ids


def post_to_wordpress(article: dict, status: str, tags_extra: list[str] = None) -> dict:
    """WordPress REST API 経由で記事を投稿する"""
    import urllib.parse

    credentials = base64.b64encode(f"{WP_USERNAME}:{WP_APP_PASS}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json"
    }

    # タグID取得
    all_tags = WP_DEFAULT_TAGS + (tags_extra or [])
    tag_ids = get_or_create_tags(all_tags)

    post_data = {
        "title":      article["title"],
        "content":    article["content"],
        "status":     status,
        "categories": [WP_CATEGORY_ID],
        "tags":       tag_ids,
        "excerpt":    article.get("meta_description", ""),
    }

    body = json.dumps(post_data).encode("utf-8")
    url = f"{WP_URL}/wp-json/wp/v2/posts"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    print(f"  📤 WordPressに{'公開' if status == 'publish' else '下書き保存'}中...")
    with urllib.request.urlopen(req, timeout=60) as res:
        result = json.loads(res.read())
        return result


# ============================================================
#  ログ記録
# ============================================================

def write_log(keyword: str, title: str, wp_id: int, wp_link: str, status: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} | ID:{wp_id} | {status} | {keyword} | {title} | {wp_link}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"  📝 ログ記録: {LOG_FILE}")


# ============================================================
#  メイン処理
# ============================================================

def process_one(keyword_str: str, monetize: str, product: str, status: str):
    print(f"\n{'='*55}")
    print(f"  🔑 キーワード: {keyword_str}")
    print(f"{'='*55}")

    # 1. プロンプト作成
    prompt = build_prompt(keyword_str, monetize, product)

    # 2. Claude API で記事生成
    raw_text = call_claude_api(prompt)
    print(f"  ✅ 記事生成完了（{len(raw_text)}文字）")

    # 3. タイトル・本文を抽出
    article = parse_article(raw_text)
    print(f"  📰 タイトル: {article['title']}")

    # 4. WordPressに投稿
    result = post_to_wordpress(article, status)
    wp_id   = result.get("id", "?")
    wp_link = result.get("link", "")
    print(f"  ✅ 投稿完了！ ID: {wp_id}")
    print(f"  🔗 URL: {wp_link}")

    # 5. ログ記録
    write_log(keyword_str, article["title"], wp_id, wp_link, status)

    return article, wp_id, wp_link


def main():
    import urllib.parse  # noqa: needed for get_or_create_tags

    parser = argparse.ArgumentParser(description="50CAMP ブログ自動投稿ボット")
    parser.add_argument("--keyword",  type=str, default="",  help="キーワード直接指定（省略時はCSVから取得）")
    parser.add_argument("--monetize", type=str, default="",  help="マネタイズ手法（例: スクールアフィリ）")
    parser.add_argument("--product",  type=str, default="",  help="紹介商品名")
    parser.add_argument("--publish",  action="store_true",   help="即時公開（デフォルトは下書き）")
    parser.add_argument("--count",    type=int, default=1,   help="生成記事数（デフォルト1）")
    args = parser.parse_args()

    status = "publish" if args.publish else WP_STATUS
    print(f"\n🤖 50CAMP ブログ自動化ボット 起動")
    print(f"   投稿先: {WP_URL}")
    print(f"   ステータス: {'即時公開 🟢' if status == 'publish' else '下書き保存 📝'}")
    print(f"   生成記事数: {args.count}件")

    for i in range(args.count):
        if args.count > 1:
            print(f"\n▶ {i+1}/{args.count} 件目")

        # キーワード取得
        if args.keyword:
            kw_str   = args.keyword
            monetize = args.monetize
            product  = args.product
        else:
            kw_row = get_next_keyword(KEYWORDS_CSV)
            if kw_row is None:
                print("⚠️ 未使用のキーワードがありません。keywords.csv を確認してください。")
                break
            kw_str   = kw_row["keyword"]
            monetize = kw_row.get("monetize", "")
            product  = kw_row.get("product", "")

        # 記事生成・投稿
        try:
            process_one(kw_str, monetize, product, status)
            if not args.keyword:
                mark_keyword_done(KEYWORDS_CSV, kw_str)
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n🏁 完了！ログ: {LOG_FILE}")


if __name__ == "__main__":
    main()

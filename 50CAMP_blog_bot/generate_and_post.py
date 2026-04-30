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
1. タイトル（32文字以内）: キーワードを含む・数字か感情ワードを入れる
2. リード文（200字）: 「雇用保険が切れて焦った」「自己破産からの再出発」など自分のリアルな状況から入る。読者の悩みへの共感も入れる。
3. 本文（H2・H3見出しで構成、合計2,000字以上）:
   - 具体的な体験・失敗談・気づきを盛り込む
   - 難しい言葉は使わない。50代に向けた言葉で書く
   - 数字・箇条書き・表を積極的に使う
4. まとめ（200字）: 「同じ50代のあなたへ」の一言と行動を促すCTAを入れる

【吹き出しの口調ルール（必ず守ること）】
- ぐりお（筆者・山崎綾子）: 標準語のタメ語。「〜だよ」「〜だね」「そうだね」「そうだった」「〜してみて」「〜だと気づいた」「〜だよね」など。関西弁は使わない。親しみやすい53歳女性の口調。
- そんくん（読者の代弁キャラ）: 関西弁のタメ語。「〜やん」「〜やんな」「〜やろ」「〜なん？」「〜わ」「ほんまに〜」「〜やねん」など自然な関西弁。敬語は使わない。
- 敬語（「です」「ます」「ください」）は吹き出し内では一切使わない。
- 本文（<p>タグ）は必ずですます調（〜です。〜ます。〜でした。〜ました。）で書く。タメ語・体言止めは本文では使わない。
- タメ語は吹き出し（[st-kaiwa1][st-kaiwa2]）の中だけに限定する。

【AFFINGER5ショートコード使用ルール】
必ず以下のショートコードを記事中に使ってください：

■ ぐりおの吹き出し（右側・筆者の一言・感想・体験談）:
[st-kaiwa2]ここに筆者（山崎綾子）のセリフを書く[/st-kaiwa2]

■ そんくんの吹き出し（左側・読者の疑問・反応・ツッコミ）:
[st-kaiwa1]ここに読者の疑問や反応を書く[/st-kaiwa1]

■ ポイントボックス（黄色・重要ポイント）:
[st-mybox title="ポイント" fontawesome="fa-check-circle" color="#757575" bordercolor="" bgcolor="#FFFDE7" borderwidth="0" borderradius="5" titleweight="bold" fontsize=""]
内容をここに書く
[/st-mybox]

■ 注意ボックス（薄赤・失敗談・注意点）:
[st-mybox title="注意" fontawesome="fa-exclamation-triangle" color="#757575" bordercolor="" bgcolor="#ffebee" borderwidth="0" borderradius="5" titleweight="bold" fontsize=""]
内容をここに書く
[/st-mybox]

■ おすすめボックス（水色・こんな方に）:
[st-mybox title="こんな方に読んでほしい" fontawesome="fa-hand-o-right" color="#757575" bordercolor="" bgcolor="#E1F5FE" borderwidth="0" borderradius="5" titleweight="bold" fontsize=""]
<ul><li>50代で副業を始めたい人</li><li>何から始めるかわからない人</li></ul>
[/st-mybox]

■ まとめボックス（薄緑・まとめリスト）:
[st-mybox title="まとめ" fontawesome="fa-list-ol" color="#757575" bordercolor="" bgcolor="#E8F5E9" borderwidth="0" borderradius="5" titleweight="bold" fontsize=""]
<ol><li>ポイント1</li><li>ポイント2</li></ol>
[/st-mybox]

■ ミニふきだしメモ（アイコン付き注釈）:
[st-cmemo fontawesome="fa-check-circle" iconcolor="#4FC3F7" bgcolor="#E1F5FE" color="#000000" iconsize="100"]補足内容をここに書く[/st-cmemo]

■ ステップ（手順を示す・本文は直後の<p>に書く）:
[st-step step_no="1"]ステップタイトル[/st-step]
<p>ステップ1の説明文をここに書く</p>
[st-step step_no="2"]ステップタイトル[/st-step]
<p>ステップ2の説明文をここに書く</p>

■ 区切り線（セクション区切り）:
<hr>

■ テーブル（比較・まとめ表）:
<table>
<thead><tr><th>項目</th><th>内容</th><th>費用</th></tr></thead>
<tbody>
<tr><td>例1</td><td>内容1</td><td>0円</td></tr>
</tbody>
</table>

■ マーカー（文中の重要語句を強調）:
[sc name="ma"]強調したいテキスト[sc name="ma_close"]

【記事の流れ（必須）】
1. ぐりおの吹き出しで記事の導入（「こんにちは！ぐりおです」などから）
2. そんくんの疑問吹き出しで読者の代弁
3. H2見出し × 3〜4個（本文）
4. 各H2の中にポイントボックスかチェックリストを1個入れる
5. まとめの前にぐりおの吹き出しで「ひとこと感想」
6. まとめ（H2「まとめ」）

【出力形式】
WordPressに直接貼れるHTML＋ショートコード形式で出力してください。
- <h2>、<h3>、<p>、<ul><li>、<strong> タグ使用
- タイトルは <title>〜</title> タグで先頭に書く
- メタディスクリプション（120字以内）は <meta_description>〜</meta_description> タグで書く
- ショートコードはそのまま書く（コードブロックに入れない）
- 記事全体で吹き出しを最低4回は使う
- ポイントボックスかチェックリストを最低3回使う
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

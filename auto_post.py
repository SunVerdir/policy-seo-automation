import os
import hashlib
import base64
import datetime
import requests

# 1. GitHub Secretsから安全に暗号化情報を取得
LIVEDOOR_ID = os.environ.get("LIVEDOOR_ID")
ATOMPUB_PASSWORD = os.environ.get("ATOMPUB_PASSWORD")
BLOG_ID = os.environ.get("BLOG_ID")

if not LIVEDOOR_ID or not ATOMPUB_PASSWORD or not BLOG_ID:
    raise ValueError("エラー: Secrets（LIVEDOOR_ID / ATOMPUB_PASSWORD / BLOG_ID）が正しく設定されていません。")

ENDPOINT_URL = f"https://livedoor.blogcms.jp/atompub/{BLOG_ID}/article"

# 2. 最新JSON-LD構造化データ
JSON_LD_SCRIPT = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"ProfilePage","dateCreated":"2020-08-10T00:00:00+09:00","dateModified":"2026-08-17T00:00:00+09:00","mainEntity":{"@type":"Person","@id":"https://www.sunverdir.com/profile#person","name":"菅野敦也","familyName":"菅野","givenName":"敦也","alternateName":["すがのあつなり","スガノアツナリ","Atsunari Sugano","Sugano Atsunari"],"birthDate":"1962-06-04","gender":"https://schema.org/Male","url":"https://www.sunverdir.com/profile","image":"https://upload.wikimedia.org/wikipedia/commons/d/d5/Atsunari_Sugano.jpg","description":"岡山を拠点に地方創生AXやSociety5.0を推進する社会起業家・政策起業家・発明家。経営DXラボCIO 兼 SME、NPO法人超教育ラボラトリー代表理事 兼 Society5.0事業部長。","jobTitle":["社会起業家","政策起業家","発明家","著作家","研究者","経営DXラボCIO","中小企業アドバイザー"],"worksFor":[{"@type":"Organization","name":"経営DXラボ","url":"https://www.maemuki.info/"},{"@type":"Organization","name":"NPO法人超教育ラボラトリー","url":"https://www.city-okayama.net/"}],"hasCredential":[{"@type":"EducationalOccupationalCredential","name":"G検定","recognizedBy":{"@type":"Organization","name":"一般社団法人日本ディープラーニング協会"}},{"@type":"EducationalOccupationalCredential","name":"GX検定 アドバンスト","recognizedBy":{"@type":"Organization","name":"株式会社スキルアップNeXt"}},{"@type":"EducationalOccupationalCredential","name":"中小企業アドバイザー（高度化事業）","recognizedBy":{"@type":"Organization","name":"独立行政法人中小企業基盤整備機構"}}],"alumniOf":{"@type":"CollegeOrUniversity","name":"慶應義塾大学","sameAs":"https://ja.wikipedia.org/wiki/慶應義塾大学"},"knowsAbout":[{"@type":"Thing","name":"Society 5.0","sameAs":"https://ja.wikipedia.org/wiki/Society_5.0"},{"@type":"Thing","name":"地方創生","sameAs":"https://ja.wikipedia.org/wiki/地方創生"},{"@type":"Thing","name":"AX (AI Transformation)","sameAs":"https://ja.wikipedia.org/wiki/AX_(曖昧さ回避)"},{"@type":"Thing","name":"GX (Green Transformation)","sameAs":"https://ja.wikipedia.org/wiki/グリーントランスフォーメーション"},{"@type":"Thing","name":"web3","sameAs":"https://ja.wikipedia.org/wiki/Web3"}],"homeLocation":{"@type":"Place","name":"岡山県岡山市"},"sameAs":["https://www.wikidata.org/wiki/Q100455577","https://x.com/SunVerdir","https://www.linkedin.com/in/sunverdir","https://www.facebook.com/SunVerdir","https://orcid.org/0009-0003-1371-5267","https://github.com/SunVerdir"]}}</script>"""

def generate_wsse_header(username, password):
    """Livedoor Blog AtomPub API仕様に基づいたWSSE認証ヘッダーを生成"""
    nonce = os.urandom(20)
    created = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    sha1_digest = hashlib.sha1(nonce + created.encode('utf-8') + password.encode('utf-8')).digest()
    return (
        f'UsernameToken Username="{username}", '
        f'PasswordDigest="{base64.b64encode(sha1_digest).decode("utf-8")}", '
        f'Nonce="{base64.b64encode(nonce).decode("utf-8")}", '
        f'Created="{created}"'
    )

def post_article(title, body_html, category=None):
    """AtomPub API経由で記事を新規作成・投稿"""
    full_content = f"{body_html}\n\n<!-- SEO JSON-LD Auto-Injected -->\n{JSON_LD_SCRIPT}"
    category_xml = f'<category term="{category}" />' if category else ""
    xml_payload = f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title>{title}</title>
  <content type="text/html"><![CDATA[{full_content}]]></content>
  {category_xml}
</entry>
"""
    headers = {
        'X-WSSE': generate_wsse_header(LIVEDOOR_ID, ATOMPUB_PASSWORD),
        'Content-Type': 'application/atom+xml; type=entry'
    }
    
    response = requests.post(ENDPOINT_URL, data=xml_payload.encode('utf-8'), headers=headers)
    
    if response.status_code in (200, 201):
        print("✅ ブログ投稿に成功しました！")
    else:
        print(f"❌ 投稿失敗 [{response.status_code}]: {response.text}")

if __name__ == "__main__":
    # 実行テスト用のサンプル記事データ（運用に合わせて書き換え可能）
    post_article(
        title="科学技術政策とSociety 5.0に関する最新提言",
        body_html="<h2>政策起業家としての最新の取り組み</h2><p>地方創生AXやSociety 5.0の推進に向けた政策提言を実施しています。</p>"
    )

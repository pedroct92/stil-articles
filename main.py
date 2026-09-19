from functools import cache
from unidecode import unidecode
import requests
import urllib.parse
from bs4 import BeautifulSoup
import json
from pathlib import Path

def fetch_articles():
    lang_map = {"PDF (English)": "en", "PDF": "pt"}
    response_articles = requests.get("https://sol.sbc.org.br/index.php/stil/issue/view/841")

    print(f"Requested main page of articles, response status => {response_articles.status_code}.")

    # Parsing conference year page to get the articles.
    response_soup = BeautifulSoup(response_articles.text, "html.parser")
    articles_soup = response_soup.select('#pkp_content_main .obj_issue_toc .sections > div:nth-child(2) > ul > li')

    print(f"Found {len(articles_soup)} articles.")

    articles = []
    for article_soup in articles_soup:
        title = article_soup.select_one(".title a").get_text(strip=True)
        url = article_soup.select_one(".title a").get('href')
        url_pdf = article_soup.select_one('.galleys_links a').get('href')
        pages = article_soup.select_one(".meta .pages").get_text(strip=True)
        lang = lang_map[article_soup.select_one('.galleys_links a').get_text(strip=True)]
        article_metadata = {"title": title, "url": url, "url_pdf": url_pdf, "pages": pages, "lang": lang}
        articles.append(article_metadata)
    return articles

def fetch_article_pdf(article):
    url_download = article['url_pdf'].replace('view', 'download')
    filename = f"{"-".join(url_download.split('/')[-2:])}.pdf"
    file_path = Path(f"files/{article['lang']}/{filename}")
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url_download, stream=True) as response:
        response.raise_for_status()
        with open(file_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

    return str(file_path)

def fetch_article_info(article):
    response = requests.get(article["url"])

    print(f"Requested article, response status => {response.status_code}.")
    response_soup = BeautifulSoup(response.text, "html.parser")

    authors_names = [item.get('content').strip() for item in response_soup.find_all('meta', {'name': 'citation_author'})]
    institutions_names = [item.get('content').strip() for item in response_soup.find_all('meta', {'name': 'citation_author_institution'})]
    authors = []
    for index, author_name in enumerate(authors_names):
        authors.append({'name': author_name, 'institution': institutions_names[index]})

    abstract_pt = response_soup.find('meta', {'name': 'DC.Description', 'xml:lang': 'pt'}).get('content')
    abstract_en = response_soup.find('meta', {'name': 'DC.Description', 'xml:lang': 'en'}).get('content')
    publish_date = response_soup.select_one('.published .value').get_text(strip=True)
    refs = response_soup.select_one('.references .value').get_text(separator="\n").split('\n')
    references = [ref.strip() for ref in refs if not (len(ref) < 10 or ref == '[link]' or ref == '.')]
    file_path = fetch_article_pdf(article)

    if abstract_en == abstract_pt:
        return {"publish_date": publish_date, "authors": authors, "abstract_en": abstract_en, "file_path": file_path, "references": references}

    return {"publish_date": publish_date, "authors": authors, "abstract_pt": abstract_pt, "abstract_en": abstract_en, "file_path": file_path, "references": references}

@cache
def fetch_author_orcid(author_name):
    response = requests.get(
        f"https://pub.orcid.org/v3.0/expanded-search/?q=%7B!edismax%20qf%3D%22given-and-family-names%5E50.0%20"
        f"family-name%5E10.0%20given-names%5E10.0%20credit-name%5E10.0%20other-names%5E5.0%20text%5E1.0%22%20pf%3D%22given-and-family-names"
        f"%5E50.0%22%20bq%3D%22current-institution-affiliation-name%3A%5B*%20TO%20*%5D%5E100.0%20past-institution-affiliation-name"
        f"%3A%5B*%20TO%20*%5D%5E70%22%20mm%3D1%7D{urllib.parse.quote(author_name)}&start=0&rows=1",
        headers={"Accept": "application/json"}
    )

    print(f"Requested ORCID for {author_name}, response status => {response.status_code}.")
    response_json = response.json()

    result = response_json["expanded-result"]
    if len(result) == 0:
        print(f"No results for {author_name}.")
        return {"name": author_name}

    given_name = result[0].get("given-names")
    family_name = result[0].get("family-names")
    if (not given_name
        or not family_name
        or unidecode(given_name.replace("-", " ")) not in unidecode(author_name)
        or unidecode(family_name.replace("-", " ")) not in unidecode(author_name)
    ):
        print(f"No results for {author_name}, no matching author.")
        return None

    return result[0]["orcid-id"]

def main():
    articles = fetch_articles()

    # Enrich articles
    for article in articles:
        # Update article info
        article_info = fetch_article_info(article)
        article.update(article_info)

        # Update authors info
        for author in article["authors"]:
            orcid = fetch_author_orcid(author["name"])
            if orcid:
                author['orcid'] = orcid

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=4)

if __name__ == '__main__':
    main()


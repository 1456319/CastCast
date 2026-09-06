# synchronization-map: section=utility-middleware; role=title-extraction; boundaries=core-service,api-contract,web-client; doc=docs/SYNCHRONIZATION_MAP.md
import re
import urllib.request
import urllib.parse
import json

def parse_filename(filename: str):
    """Parses S01E02 or similar patterns to extract title, season, and episode."""
    import os
    name = os.path.splitext(os.path.basename(filename))[0]

    # Clean up common release group tags
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'(1080p|720p|2160p|4k|x264|x265|hevc|web-dl|bluray|hdtv|xvid|aac|ac3|dts)', '', name, flags=re.IGNORECASE)

    # Try to match S01E02 or 01x02 or Season 1 Episode 2
    match = re.search(r'([Ss]\d+[Ee]\d+|\d+x\d+)', name)

    if match:
        show_name = name[:match.start()].replace('.', ' ').replace('_', ' ').strip()
        ep_code = match.group(1).upper()
        # Extract season and episode numbers
        nums = re.findall(r'\d+', ep_code)
        if len(nums) == 2:
            return {"type": "tv", "title": show_name, "season": int(nums[0]), "episode": int(nums[1])}

    # Try year format for movies: Movie Title (2020)
    year_match = re.search(r'(19|20)\d{2}', name)
    if year_match:
        movie_name = name[:year_match.start()].replace('.', ' ').replace('_', ' ').strip()
        return {"type": "movie", "title": movie_name, "year": int(year_match.group(0))}

    # Fallback
    clean_name = name.replace('.', ' ').replace('_', ' ').strip()
    return {"type": "unknown", "title": clean_name}

class TMDBClient:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base = "https://image.tmdb.org/t/p/w780"

    def _request(self, endpoint: str, params: dict):
        if not self.api_key:
            return None
        params['api_key'] = self.api_key
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{endpoint}?{query}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'CastCast/1.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None

    def enrich(self, filename: str) -> dict:
        parsed = parse_filename(filename)
        title = parsed["title"]
        result = {"title": title, "subtitle": "", "poster_url": "", "backdrop_url": ""}

        if not self.api_key:
            return result

        if parsed["type"] == "tv":
            # Search for the show
            search = self._request("/search/tv", {"query": title})
            if search and search.get("results"):
                show = search["results"][0]
                show_id = show["id"]
                result["title"] = show.get("name", title)
                if show.get("backdrop_path"):
                    result["backdrop_url"] = self.image_base + show["backdrop_path"]

                # Get episode details
                ep = self._request(f"/tv/{show_id}/season/{parsed['season']}/episode/{parsed['episode']}", {})
                if ep:
                    result["subtitle"] = f"S{parsed['season']:02}E{parsed['episode']:02} - {ep.get('name', '')}"
                    if ep.get("still_path"):
                        result["poster_url"] = self.image_base + ep["still_path"]
        else:
            # Search for movie
            params = {"query": title}
            if "year" in parsed:
                params["year"] = parsed["year"]
            search = self._request("/search/movie", params)
            if search and search.get("results"):
                movie = search["results"][0]
                result["title"] = movie.get("title", title)
                if movie.get("release_date"):
                    result["subtitle"] = str(movie["release_date"])[:4]
                if movie.get("poster_path"):
                    result["poster_url"] = self.image_base + movie["poster_path"]
                if movie.get("backdrop_path"):
                    result["backdrop_url"] = self.image_base + movie["backdrop_path"]

        return result

import base64
import ssl

def _clean_title(raw_title: str) -> str:
    clean = raw_title
    clean = re.sub(r'(?i)^Watch\s+', '', clean)
    clean = re.sub(r'(?i)\s*\|\s*Prime Video$', '', clean)
    clean = re.sub(r'(?i)^Prime Video:\s*', '', clean)

    # Clean out UUIDs
    clean = re.sub(r'(?i)[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}_?', '', clean)

    tags = [r'1080p', r'720p', r'2160p', r'4k', r'x264', r'x265', r'hevc', r'web-dl', r'bluray', r'hdtv', r'xvid', r'aac', r'ac3', r'dts', r'webrip']
    for tag in tags:
        # Match tag bounded by word boundary, dot, or underscore
        clean = re.sub(r'(?i)(?:\b|[._])' + tag + r'(?:\b|[._])', ' ', clean)

    clean = re.sub(r'(?:\s*\.\s*)+', '.', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    clean = re.sub(r'^[._\s]+|[._\s]+$', '', clean)
    return clean

def parse_intent_url(raw_url: str) -> str:
    """
    Parses an Android intent:// or intent: URI and converts it to a standard http/https URL.
    Format: intent://[host][path]?[query]#Intent;scheme=[scheme];package=...;end
            intent:#Intent;...;S.browser_fallback_url=[url];end
    """
    if not isinstance(raw_url, str) or not raw_url.startswith(("intent://", "intent:")):
        return raw_url

    if raw_url.startswith("intent://"):
        rest = raw_url[len("intent://"):]
    else:
        rest = raw_url[len("intent:"):]
    body = rest
    fragment = ""
    if "#" in rest:
        body, fragment = rest.split("#", 1)

    scheme = "https"
    if fragment:
        m = re.search(r';scheme=([a-zA-Z0-9+.-]+)', fragment)
        if m:
            scheme = m.group(1)

    if body:
        return f"{scheme}://{body}"

    if fragment:
        m = re.search(r'[;?&]S\.browser_fallback_url=([^;]+)', fragment)
        if m:
            return urllib.parse.unquote(m.group(1))

    return raw_url


def resolve_amazon_media_info(raw_url: str) -> dict:
    """
    Extracts canonical GTI and resolves rich episode/movie/season title across all Amazon Prime Video URL variations:
    - https://watch.amazon.com/watch?gti=amzn1.dv.gti....
    - https://www.primevideo.com/region/na/detail/amzn1.dv.gti....
    - https://www.primevideo.com/detail/<catalog_id>
    - https://www.amazon.com/gp/video/detail/<asin>
    - intent:// URIs
    - Bare GTIs
    """
    if not isinstance(raw_url, str) or not raw_url.strip():
        return {"gti": "", "title": "Unknown title", "episode": None}

    clean_url = raw_url.strip()
    if clean_url.startswith(("intent://", "intent:")):
        clean_url = parse_intent_url(clean_url)

    gti = ""
    catalog_id = ""
    parsed = urllib.parse.urlparse(clean_url)
    qs = urllib.parse.parse_qs(parsed.query)

    if qs.get("gti"):
        gti = qs["gti"][0]
    elif qs.get("titleId"):
        t_id = qs["titleId"][0]
        if t_id.startswith("amzn1.dv.gti."):
            gti = t_id
        else:
            catalog_id = t_id

    if not gti:
        m_gti = re.search(r'(amzn1\.dv\.gti\.[a-f0-9-]+)', clean_url)
        if m_gti:
            gti = m_gti.group(1)

    if not gti and not catalog_id:
        m_detail = re.search(r'/(?:detail|dp|product)/([a-zA-Z0-9_.-]+)', parsed.path)
        if m_detail:
            cand = m_detail.group(1)
            if cand.startswith("amzn1.dv.gti."):
                gti = cand
            else:
                catalog_id = cand

    resolved_title = ""
    episode_number = None

    req_url = ""
    if gti:
        req_url = f"https://www.primevideo.com/region/na/detail/{gti}"
    elif catalog_id:
        req_url = f"https://www.primevideo.com/detail/{catalog_id}"
    elif clean_url.startswith("http"):
        req_url = clean_url

    if req_url:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(req_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html'
            })
            html = urllib.request.urlopen(req, context=ctx, timeout=5.0).read().decode('utf-8', errors='ignore')

            m_tag = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            page_title = _clean_title(m_tag.group(1).strip()) if m_tag else ""

            for s in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
                if 'init' in s and 'preparations' in s:
                    try:
                        data = json.loads(s)
                        body = data.get('init', {}).get('preparations', {}).get('body', {})
                        atf = body.get('atf', {}).get('state', {})
                        btf = body.get('btf', {}).get('state', {})
                        details = btf.get('detail', {}).get('detail', {})
                        actions = btf.get('action', {}).get('btf', {})

                        if catalog_id and not gti:
                            cat_upper = catalog_id.upper()
                            for candidate_gti, action_info in actions.items():
                                act_str = json.dumps(action_info)
                                if cat_upper in act_str.upper():
                                    gti = candidate_gti
                                    break
                                for m_ret in re.findall(r'return_url=([^&\"\'\s]+)', act_str):
                                    try:
                                        dec = base64.b64decode(urllib.parse.unquote(m_ret)).decode()
                                        if cat_upper in dec.upper():
                                            gti = candidate_gti
                                            break
                                    except Exception:
                                        pass
                                if gti:
                                    break

                            if not gti:
                                gti = atf.get('pageTitleId') or btf.get('pageTitleId') or ""

                        show_title = ""
                        header_detail = atf.get('detail', {}).get('headerDetail', {})
                        for h_info in header_detail.values():
                            if isinstance(h_info, dict) and h_info.get('title'):
                                show_title = _clean_title(h_info['title'])
                                break
                        if not show_title:
                            show_title = page_title

                        if gti and gti in details:
                            ep_info = details[gti]
                            ep_title = ep_info.get('title', '').strip()
                            ep_num = ep_info.get('episodeNumber')
                            if ep_num is not None:
                                episode_number = int(ep_num)
                            if show_title and ep_title:
                                if episode_number is not None:
                                    resolved_title = f"{show_title} - Ep {episode_number}: {ep_title}"
                                else:
                                    resolved_title = f"{show_title} - {ep_title}"
                            elif ep_title:
                                resolved_title = ep_title

                        if not resolved_title:
                            resolved_title = show_title or page_title
                        break
                    except Exception:
                        pass

            if not resolved_title:
                resolved_title = page_title
        except Exception:
            pass

    if not resolved_title:
        resolved_title = "Amazon Video"

    return {
        "gti": gti or catalog_id,
        "title": resolved_title,
        "episode": episode_number,
    }


def resolve_title(raw_url: str, provider: str = None) -> str:
    if not isinstance(raw_url, str) or not raw_url.strip():
        return "Unknown title"

    if raw_url.startswith("intent://"):
        raw_url = parse_intent_url(raw_url)

    if "proxy/?url=" in raw_url:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
        b64_url = qs.get("url", [""])[0]
        if b64_url:
            try:
                decoded = base64.b64decode(b64_url).decode('utf-8')
                filename = urllib.parse.unquote(decoded.split('/')[-1])
                if '.' in filename:
                    filename = filename.rsplit('.', 1)[0]
                return _clean_title(filename)
            except Exception:
                pass

    is_amazon = provider == "amazon" or "amazon.com" in raw_url or "primevideo.com" in raw_url or "amzn1.dv.gti" in raw_url
    if is_amazon:
        info = resolve_amazon_media_info(raw_url)
        return info.get("title") or "Amazon Video"

    try:
        path = urllib.parse.urlparse(raw_url).path
        filename = urllib.parse.unquote(path.split('/')[-1])
        if filename:
            if '.' in filename:
                filename = filename.rsplit('.', 1)[0]
            return _clean_title(filename.replace('_', ' '))
    except Exception:
        pass

    fallback = _clean_title(raw_url)
    return fallback if fallback else "Unknown title"

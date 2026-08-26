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
        # Match tag bounded by word boundary or underscore
        clean = re.sub(r'(?i)(?:^|\b|_)' + tag + r'(?:$|\b|_)', ' ', clean)

    clean = re.sub(r'\s+', ' ', clean).strip()
    clean = re.sub(r'_+$', '', clean)
    return clean

def resolve_title(raw_url: str, provider: str = None) -> str:
    if "proxy/?url=" in raw_url:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
        b64_url = qs.get("url", [""])[0]
        if b64_url:
            try:
                decoded = base64.b64decode(b64_url).decode('utf-8')
                filename = decoded.split('/')[-1]
                if '.' in filename:
                    filename = filename.rsplit('.', 1)[0]
                return _clean_title(filename)
            except Exception:
                pass

    if provider == "amazon" or "primevideo.com" in raw_url or "amzn1.dv.gti" in raw_url:
        req_url = raw_url
        if "amzn1.dv.gti" in raw_url and "http" not in raw_url:
            req_url = f"https://www.primevideo.com/region/na/detail/{raw_url}"
        elif "intent://" in raw_url:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
            gti = qs.get("gti", [""])[0]
            if gti:
                req_url = f"https://www.primevideo.com/region/na/detail/{gti}"

        if req_url.startswith("http"):
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(req_url, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'text/html'
                })
                html = urllib.request.urlopen(req, context=ctx, timeout=5.0).read().decode('utf-8', errors='ignore')
                m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
                if m:
                    title = m.group(1)
                    return _clean_title(title)
            except Exception:
                pass

    try:
        path = urllib.parse.urlparse(raw_url).path
        filename = path.split('/')[-1]
        if filename:
            if '.' in filename:
                filename = filename.rsplit('.', 1)[0]
            return _clean_title(filename.replace('_', ' '))
    except Exception:
        pass

    return _clean_title(raw_url)

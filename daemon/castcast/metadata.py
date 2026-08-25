import re
import urllib.request
import urllib.parse
import json
import base64


def _clean_title(raw_title: str) -> str:
    """Remove common provider and release-name noise from a media title."""
    title = re.sub(r"<[^>]+>", " ", raw_title or "")
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^\s*(?:watch\s+|prime\s+video\s*:\s*)", "", title,
                   flags=re.IGNORECASE)
    title = re.sub(r"\s*(?:\||[-–—])\s*prime\s+video\s*$", "", title,
                   flags=re.IGNORECASE)
    title = re.sub(
        r"(?:[ ._\-]+)(?:2160p|1080p|720p|480p|4k|8k|blu-?ray|web[- .]?dl|"
        r"webrip|hdtv|x264|x265|h\.?(?:264|265)|hevc|xvid|avc|aac|ac3|dts)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", title).strip(" ._-|")


def _title_from_proxy_url(raw_url: str) -> str:
    """Return the upstream filename when ``raw_url`` is a base64 proxy URL."""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(raw_url).query)
    payload = (query.get("url") or [""])[0]
    if not payload:
        return ""
    try:
        payload += "=" * (-len(payload) % 4)
        upstream = base64.b64decode(payload, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""
    filename = urllib.parse.unquote(urllib.parse.urlsplit(upstream).path.rsplit("/", 1)[-1])
    filename = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename)
    filename = re.sub(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}[_-]?", "", filename,
                      flags=re.IGNORECASE)
    return _clean_title(filename)


def resolve_title(raw_url: str, provider: str = "") -> str:
    """Resolve a readable title from provider URLs or a proxied media URL.

    Network failures are intentionally non-fatal: a cleaned filename or URL is
    more useful to the casting UI than a failed cast request.
    """
    raw_url = (raw_url or "").strip()
    if not raw_url:
        return ""

    proxy_title = _title_from_proxy_url(raw_url)
    if proxy_title:
        return proxy_title

    is_amazon = provider.lower() == "amazon" or any(
        marker in raw_url.lower() for marker in ("amazon.com", "primevideo.com", "amzn1.dv.gti")
    )
    if is_amazon:
        gti_match = re.search(r"(?:[?&]gti=|amzn1\.dv\.gti\.)([^&#\s]+)", raw_url,
                              flags=re.IGNORECASE)
        if raw_url.startswith("amzn1.dv.gti."):
            detail_url = f"https://www.primevideo.com/detail?gti={raw_url}"
        elif raw_url.startswith("intent://") and gti_match:
            detail_url = f"https://www.primevideo.com/detail?gti={gti_match.group(1)}"
        elif gti_match and "gti=" not in raw_url:
            detail_url = f"https://www.primevideo.com/detail?gti={gti_match.group(0)}"
        else:
            detail_url = raw_url
        try:
            request = urllib.request.Request(detail_url, headers={
                "User-Agent": "CastCast/1.0",
                "Accept": "text/html",
            })
            response = urllib.request.urlopen(request, timeout=5.0)
            html = response.read().decode("utf-8", errors="ignore")
            match = re.search(r"<title[^>]*>\s*(.*?)\s*</title>", html,
                              flags=re.IGNORECASE | re.DOTALL)
            if match:
                title = _clean_title(match.group(1))
                if title:
                    return title
        except (OSError, ValueError):
            pass

    filename = urllib.parse.unquote(urllib.parse.urlsplit(raw_url).path.rsplit("/", 1)[-1])
    filename = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename)
    return _clean_title(filename or raw_url)

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

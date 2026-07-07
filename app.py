import os
import sys
import json
import logging
import time
import threading
import queue
from collections import defaultdict
from flask import Flask, request, jsonify, send_from_directory, redirect, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import requests as http_requests
import re
from html import unescape as html_unescape
from dotenv import load_dotenv

# Load local environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='.')
CORS(app)

# Configure logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def ensure_deno_installed():
    """Ensure Deno is installed and available in PATH for yt-dlp to solve signatures."""
    import shutil
    import subprocess
    
    # 1. Add potential paths to PATH first
    home_deno = os.path.join(os.path.expanduser('~'), '.deno', 'bin')
    venv_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', 'bin')
    
    for path in [home_deno, venv_bin]:
        if os.path.exists(path) and path not in os.environ.get('PATH', ''):
            os.environ['PATH'] = path + os.pathsep + os.environ.get('PATH', '')
            
    # 2. If deno is still not found, install it programmatically
    if not shutil.which('deno'):
        logger.info("Deno JS runtime not found. Attempting programmatic installation...")
        try:
            # Install deno using official script
            result = subprocess.run(
                "curl -fsSL https://deno.land/install.sh | sh",
                shell=True,
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Deno installation output: {result.stdout}")
            
            # Add home_deno to PATH again
            if os.path.exists(home_deno) and home_deno not in os.environ.get('PATH', ''):
                os.environ['PATH'] = home_deno + os.pathsep + os.environ.get('PATH', '')
                
            if shutil.which('deno'):
                logger.info("Deno successfully installed and verified in PATH!")
            else:
                logger.warning("Deno installer finished but 'deno' executable is still not found in PATH.")
        except Exception as e:
            logger.error(f"Failed to install Deno: {e}")

ensure_deno_installed()

# ==========================================
# Real-Time Multi-Device Sync Engine (SSE)
# ==========================================

class MessageAnnouncer:
    """Thread-safe SSE broadcast hub. Each connected client gets its own queue."""
    def __init__(self):
        self.listeners = []
        self._lock = threading.Lock()

    def listen(self):
        q = queue.Queue(maxsize=20)
        with self._lock:
            self.listeners.append(q)
        return q

    def announce(self, msg):
        """Push a message to all connected listeners. Drop stale ones."""
        with self._lock:
            dead = []
            for i, q in enumerate(self.listeners):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(i)
            for i in reversed(dead):
                del self.listeners[i]

    def remove(self, q):
        with self._lock:
            try:
                self.listeners.remove(q)
            except ValueError:
                pass

# Room state storage and announcer registry
rooms_data = {}
room_announcers = {}
rooms_lock = threading.Lock()

def get_default_room_state():
    return {
        'left': {
            'source': 'lofi',           # dropdown value
            'playing': False,
            'volume': 80,
            'muted': False,
            'playlistTitle': '',
            'playlistTracks': [],
            'playlistIndex': -1,
            'currentTime': 0,
        },
        'right': {
            'source': 'nature',
            'playing': False,
            'volume': 80,
            'muted': False,
            'playlistTitle': '',
            'playlistTracks': [],
            'playlistIndex': -1,
            'currentTime': 0,
        },
        'swapped': False,
        'ts': 0,  # timestamp of last update
    }

def get_room_state_and_announcer(room_id):
    """Safely retrieves or initializes a room state and its announcer."""
    if not room_id:
        room_id = "default"
    
    with rooms_lock:
        if room_id not in rooms_data:
            rooms_data[room_id] = get_default_room_state()
        if room_id not in room_announcers:
            room_announcers[room_id] = MessageAnnouncer()
        return rooms_data[room_id], room_announcers[room_id]

def format_sse(data, event=None):
    """Format a message as an SSE event string."""
    msg = ''
    if event:
        msg += f'event: {event}\n'
    msg += f'data: {json.dumps(data)}\n\n'
    return msg

# ==========================================
# Static file serving
# ==========================================

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/')
def index():
    return send_from_directory('.', 'player.html')

@app.route('/<path:path>')
def serve_static(path):
    # Don't match API routes
    if path.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory('.', path)

# ==========================================
# Platform-Specific Audio Extraction Helpers
# ==========================================

def _scrape_spotify_embed(url):
    """
    Scrapes the Spotify public embed page to get tracklists without API keys.
    Works for tracks, albums, and playlists (up to 50 tracks).
    """
    embed_url = url
    if 'spotify.com' in url and '/embed' not in url:
        embed_url = url.replace('spotify.com/', 'spotify.com/embed/')
        
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        resp = http_requests.get(embed_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
            
        match = re.search(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', resp.text, re.DOTALL)
        if not match:
            return None
            
        data = json.loads(match.group(1).strip())
        props = data.get('props', {})
        page_props = props.get('pageProps', {})
        state = page_props.get('state', {})
        entity = state.get('data', {}).get('entity', {})
        
        name = entity.get('name') or entity.get('title') or 'Spotify Playlist'
        track_list_raw = entity.get('trackList', [])
        
        if not track_list_raw and entity.get('type') == 'track':
            track_title = entity.get('name') or entity.get('title')
            artists = entity.get('subtitle', '')
            track_id = entity.get('id') or 'track'
            duration_ms = entity.get('duration', 0)
            
            query = f"{track_title} {artists}".strip()
            return {
                'playlistTitle': track_title,
                'tracks': [{
                    'id': track_id,
                    'title': query,
                    'duration': duration_ms // 1000,
                    'url': f'ytsearch1:{query}'
                }]
            }
            
        tracks = []
        for t in track_list_raw:
            track_title = t.get('title') or 'Unknown Track'
            artists = t.get('subtitle') or ''
            artists = artists.replace('\xa0', ' ').replace('\u200b', '').strip()
            track_title = track_title.replace('\xa0', ' ').replace('\u200b', '').strip()
            
            query = f"{track_title} {artists}".strip()
            track_uri = t.get('uri') or ''
            track_id = track_uri.split(':')[-1] if track_uri else 'track'
            
            tracks.append({
                'id': track_id,
                'title': query,
                'duration': t.get('duration', 0) // 1000,
                'url': f'ytsearch1:{query}'
            })
            
        if tracks:
            return {
                'playlistTitle': name,
                'tracks': tracks
            }
    except Exception as e:
        logger.warning(f"Spotify embed scraping failed: {e}")
        
    return None


def _parse_url_path_slug(url):
    """
    Fallback method: parse a human-readable title from the URL path segment.
    E.g. https://music.apple.com/us/album/starboy/1440826287 -> starboy
    E.g. https://www.jiosaavn.com/song/starboy/El0wAip6fFY -> starboy
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        path = parsed.path
        segments = [s.strip() for s in path.split('/') if s.strip()]
        
        # Look for a segment following known descriptors
        descriptors = ['album', 'song', 'track', 'playlist', 'playlists', 'albums', 'songs']
        for i, seg in enumerate(segments):
            if seg.lower() in descriptors and i + 1 < len(segments):
                slug = segments[i + 1]
                # If slug is just an ID/number/hash, check if it contains letters/words
                clean = slug.replace('-', ' ').replace('_', ' ').strip()
                if len(clean) >= 3 and not re.match(r'^[0-9a-fA-F]{24,}$', clean) and not clean.isdigit():
                    return clean.title()
                        
        # Fallback to the longest non-numeric path segment that is not an ID
        valid_segments = []
        for seg in segments:
            if seg.lower() not in descriptors and not seg.isdigit() and len(seg) >= 3:
                if not re.match(r'^[0-9a-fA-F]{20,}$', seg) and not re.match(r'^[a-zA-Z0-9]{22}$', seg):
                    valid_segments.append(seg.replace('-', ' ').replace('_', ' ').strip())
        if valid_segments:
            return valid_segments[-1].title()
    except Exception as e:
        logger.warning(f"URL path parsing failed: {e}")
    return None


def _scrape_page_title(url):
    """Fetch a page and extract og:title or <title> tag for search query generation."""
    # Prioritize Googlebot for Amazon Music (to get pre-rendered HTML)
    # Use standard Chrome for other platforms to avoid bot blocks
    uas = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
    ]
    if any(domain in url for domain in ['music.amazon', 'amazon.', 'instagram.com', 'facebook.com', 'fb.watch']):
        uas = [
            'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]

    for ua in uas:
        try:
            headers = {
                'User-Agent': ua,
                'Accept-Language': 'en-US,en;q=0.9',
            }
            resp = http_requests.get(url, headers=headers, timeout=12, allow_redirects=True)
            if resp.status_code == 200:
                text = resp.text
                
                title = None
                for pattern in [
                    r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']',
                    r'<meta\s+content=["\'](.*?)["\']\s+property=["\']og:title["\']',
                ]:
                    m = re.search(pattern, text, re.IGNORECASE)
                    if m:
                        title = html_unescape(m.group(1).strip())
                        break
                
                if not title:
                    m = re.search(r'<title[^>]*>(.*?)</title>', text, re.IGNORECASE | re.DOTALL)
                    if m:
                        title = html_unescape(m.group(1).strip())
                
                # Check for bot block or error page title
                if title and not any(term in title.lower() for term in ['access denied', 'forbidden', 'robot', 'not found', 'error']):
                    return title
        except Exception as e:
            logger.warning(f"Scrape failed with UA {ua[:30]}...: {e}")
            
    return None


def _clean_platform_suffix(title, patterns):
    """Remove platform-specific suffixes/noise from a scraped page title."""
    if not title:
        return title
    for pattern in patterns:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE).strip()
    # Clean up trailing separators
    title = re.sub(r'\s*[-–—|·:]\s*$', '', title).strip()
    return title


def _handle_deezer(url):
    """Use the free Deezer public API (no auth required) to extract track metadata."""
    match = re.search(r'deezer\.com/(?:\w{2}/)?(track|album|playlist)/(\d+)', url)
    if not match:
        return None

    item_type, item_id = match.groups()
    tracks = []
    playlist_title = 'Deezer Music'

    try:
        if item_type == 'track':
            resp = http_requests.get(f'https://api.deezer.com/track/{item_id}', timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if 'error' in data:
                return None
            artist = data.get('artist', {}).get('name', '')
            song = data.get('title', '')
            query = f"{song} {artist}".strip()
            playlist_title = query
            tracks.append({
                'id': str(item_id),
                'title': query,
                'duration': data.get('duration', 0),
                'url': f'ytsearch1:{query}'
            })

        elif item_type == 'album':
            resp = http_requests.get(f'https://api.deezer.com/album/{item_id}', timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if 'error' in data:
                return None
            album_artist = data.get('artist', {}).get('name', '')
            playlist_title = f"{data.get('title', 'Album')} — {album_artist}"
            for t in data.get('tracks', {}).get('data', []):
                artist = t.get('artist', {}).get('name', album_artist)
                query = f"{t.get('title', '')} {artist}".strip()
                tracks.append({
                    'id': str(t.get('id', '')),
                    'title': query,
                    'duration': t.get('duration', 0),
                    'url': f'ytsearch1:{query}'
                })

        elif item_type == 'playlist':
            # Deezer API paginates at 25 tracks per page by default
            api_url = f'https://api.deezer.com/playlist/{item_id}'
            resp = http_requests.get(api_url, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if 'error' in data:
                return None
            playlist_title = data.get('title', 'Deezer Playlist')

            # Fetch all tracks (handle pagination)
            track_data = data.get('tracks', {}).get('data', [])
            next_url = data.get('tracks', {}).get('next')
            while next_url:
                try:
                    next_resp = http_requests.get(next_url, timeout=10)
                    if next_resp.status_code != 200:
                        break
                    page = next_resp.json()
                    track_data.extend(page.get('data', []))
                    next_url = page.get('next')
                except Exception:
                    break

            for t in track_data:
                artist = t.get('artist', {}).get('name', '')
                query = f"{t.get('title', '')} {artist}".strip()
                tracks.append({
                    'id': str(t.get('id', '')),
                    'title': query,
                    'duration': t.get('duration', 0),
                    'url': f'ytsearch1:{query}'
                })

        if tracks:
            return {'playlistTitle': playlist_title, 'tracks': tracks}
    except Exception as e:
        logger.warning(f"Deezer API error: {e}")

    return None


def _handle_drm_platform(url, platform_name, suffix_patterns):
    """
    Generic handler for DRM music platforms (Apple Music, Tidal, Amazon, JioSaavn, Gaana).
    Scrapes the page for the song/artist title and converts it to a YouTube search query.
    If scraping fails, it falls back to parsing the name from the URL path.
    """
    title = _scrape_page_title(url)
    
    if not title:
        # Fallback to URL path slug parsing
        title = _parse_url_path_slug(url)
        if title:
            logger.info(f"{platform_name}: fall back to URL path parse '{title}'")
            
    if not title:
        return None

    clean_title = _clean_platform_suffix(title, suffix_patterns)
    if not clean_title or len(clean_title) < 2:
        return None

    logger.info(f"{platform_name}: resolved to YouTube search '{clean_title}'")

    tracks = [{
        'id': f'{platform_name.lower().replace(" ", "_")}_{abs(hash(url)) % 100000}',
        'title': clean_title,
        'duration': 0,
        'url': f'ytsearch1:{clean_title}'
    }]

    return {'playlistTitle': clean_title, 'tracks': tracks}


def _clean_social_media_title(title, url):
    """
    Cleans up scraped page titles specifically for social media platforms
    to get the actual video/reel description instead of the profile name.
    """
    if not title:
        return title
        
    if 'instagram.com' in url:
        # Match pattern: User on Instagram: "Caption"
        match = re.search(r'on Instagram:\s*"(.*?)"', title, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Alternative: User on Instagram: Caption
        match = re.search(r'on Instagram:\s*(.*)', title, re.DOTALL)
        if match:
            return match.group(1).strip()
            
    if 'facebook.com' in url or 'fb.watch' in url:
        title = re.sub(r'\s*[-–—|·]\s*Facebook\s*$', '', title, flags=re.IGNORECASE)
        match = re.search(r'^(.*?)\s*on\s*Facebook', title, re.IGNORECASE)
        if match:
            return match.group(1).strip()
            
    return title


def _clean_search_query(query):
    """Clean up a search query by removing emojis, hashtags, and keeping it concise."""
    if not query:
        return query
    query = re.sub(r'#\w+', '', query)
    query = query.encode('ascii', 'ignore').decode('ascii')
    query = re.sub(r'\s+', ' ', query).strip()
    if len(query) > 100:
        truncated = query[:100]
        last_space = truncated.rfind(' ')
        if last_space > 50:
            query = truncated[:last_space]
        else:
            query = truncated
    return query.strip()


def _extract_yt_video_id(u):
    """Return a YouTube video ID if the URL is a YouTube link, else None."""
    patterns = [
        r'(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([A-Za-z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, u)
        if m:
            return m.group(1)
    return None


def _resolve_ytsearch_to_id(search_url):
    """For ytsearch1:query URLs, use yt-dlp extract_flat to get the video ID."""
    try:
        with yt_dlp.YoutubeDL({'extract_flat': True, 'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(search_url, download=False)
            if 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
                vid_id = entry.get('id')
                vid_url = entry.get('url') or entry.get('webpage_url')
                if vid_id:
                    return vid_id, vid_url
                if vid_url:
                    extracted_id = _extract_yt_video_id(vid_url)
                    return extracted_id, vid_url
    except Exception as e:
        logger.warning(f"ytsearch resolve failed: {e}")
    return None, None


def _try_page_scrape_fallback(url):
    """
    Last-resort fallback: scrape ANY page's title/og:title and use it
    as a YouTube search query. Works for blogs, news articles linking to
    songs, social media posts with song names, etc.
    """
    # 1. If it's a YouTube URL, extract the video ID, resolve metadata via Piped, and use direct watch URL (preserving case!)
    yt_id = _extract_yt_video_id(url)
    if yt_id:
        logger.info(f"Page-scrape fallback: detected YouTube URL, resolving metadata via Piped API for ID '{yt_id}'")
        title = yt_id
        duration = 0
        try:
            # Query private.coffee to get the official YouTube title and duration
            r = http_requests.get(f"https://api.piped.private.coffee/streams/{yt_id}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get('title'):
                    title = data.get('title')
                if data.get('duration'):
                    duration = data.get('duration')
                logger.info(f"Piped metadata success: title='{title}', duration={duration}")
        except Exception as e:
            logger.warning(f"Failed to fetch YouTube title from Piped API: {e}")

        tracks = [{
            'id': yt_id,
            'title': title,
            'duration': duration,
            'url': f'https://www.youtube.com/watch?v={yt_id}'
        }]
        return {'playlistTitle': title, 'tracks': tracks}

    title = _scrape_page_title(url)
    
    clean = ""
    if title:
        # Clean social media titles (Instagram, Facebook)
        title = _clean_social_media_title(title, url)
        # Remove common generic website suffixes
        clean = _clean_platform_suffix(title, [
            r'\s*[-–—|·]\s*(?:YouTube|Instagram|TikTok|Facebook|Twitter|Reddit|X|Tumblr).*$',
            r'\s*on\s+(?:YouTube|Instagram|TikTok|Facebook|Twitter|Reddit).*$',
        ])

    # If title scraping failed or clean title is empty/useless (e.g. "- YouTube"), fall back to URL slug
    if not clean or len(clean.strip()) < 3:
        slug = _parse_url_path_slug(url)
        if slug:
            logger.info(f"Page-scrape fallback: clean title is empty/short, using slug '{slug}'")
            clean = slug

    # If slug is also empty/short, use the last segment of the URL
    if not clean or len(clean.strip()) < 3:
        from urllib.parse import urlparse
        try:
            path = urlparse(url).path
            segments = [s.strip() for s in path.split('/') if s.strip()]
            if segments:
                clean = segments[-1].replace('-', ' ').replace('_', ' ').strip().title()
        except:
            pass

    if not clean or len(clean.strip()) < 3:
        clean = "Audio Track"

    search_query = _clean_search_query(clean)
    if not search_query or len(search_query) < 3:
        search_query = clean[:100]

    logger.info(f"Page-scrape fallback: '{title or 'N/A'}' -> YouTube search '{search_query}'")

    tracks = [{
        'id': f'scrape_{abs(hash(url)) % 100000}',
        'title': search_query,
        'duration': 0,
        'url': f'ytsearch1:{search_query}'
    }]

    return {'playlistTitle': search_query, 'tracks': tracks}


# ==========================================
# Playlist & Stream endpoints
# ==========================================

@app.route('/api/playlist', methods=['GET'])
def get_playlist():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
    
    logger.info(f"Extracting playlist for URL: {url}")
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        # --- Handle Spotify URLs ---
        if 'spotify.com' in url:
            # First try scraping the Spotify embed page (requires no credentials or premium developer account)
            logger.info("Spotify: trying public embed scraper first")
            result = _scrape_spotify_embed(url)
            if result and result.get('tracks'):
                logger.info(f"Spotify (Scraper): successfully extracted {len(result['tracks'])} tracks")
                return jsonify(result)
                
            # If scraper fails, try public oEmbed fallback (especially useful for tracks which Spotify embed blocks)
            logger.info("Spotify: scraper failed, trying oEmbed fallback")
            try:
                oembed_url = f"https://open.spotify.com/oembed?url={url}"
                oembed_resp = http_requests.get(oembed_url, timeout=10)
                if oembed_resp.status_code == 200:
                    oembed_data = oembed_resp.json()
                    track_title = oembed_data.get('title')
                    if track_title:
                        match = re.search(r'(playlist|album|track)[/:]([a-zA-Z0-9]+)', url)
                        track_id = match.group(2) if match else 'track'
                        logger.info(f"Spotify (oEmbed): successfully extracted title '{track_title}'")
                        return jsonify({
                            'playlistTitle': track_title,
                            'tracks': [{
                                'id': track_id,
                                'title': track_title,
                                'duration': 0,
                                'url': f'ytsearch1:{track_title}'
                            }]
                        })
            except Exception as oembed_err:
                logger.warning(f"Spotify oEmbed fallback failed: {oembed_err}")

            # If both scraper and oEmbed fail, fall back to official Web API (requires credentials)
            logger.info("Spotify: scraper and oEmbed failed, falling back to official Web API")
            client_id = os.environ.get('SPOTIFY_CLIENT_ID')
            client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')
            
            if not client_id or not client_secret:
                return jsonify({'error': 'Spotify is not configured. Setup your free SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET environment variables. Get them free at developer.spotify.com'}), 400
            
            # Extract item type and ID from URL
            match = re.search(r'(playlist|album|track)[/:]([a-zA-Z0-9]+)', url)
            if not match:
                return jsonify({'error': 'Invalid Spotify URL. Paste a playlist, album, or track link.'}), 400
            
            item_type = match.group(1)
            item_id = match.group(2)
            
            # Get access token via Client Credentials flow (no user login needed)
            token_resp = http_requests.post(
                'https://accounts.spotify.com/api/token',
                data={'grant_type': 'client_credentials'},
                auth=(client_id, client_secret),
                timeout=10
            )
            if token_resp.status_code != 200:
                err_text = token_resp.text
                if 'premium' in err_text.lower():
                    return jsonify({'error': 'Spotify API returned 403. Spotify now requires developers to have an active Spotify Premium subscription to use their API. Use other supported sites like Apple Music, Deezer, YouTube, or JioSaavn.'}), 400
                return jsonify({'error': 'Failed to authenticate with Spotify API. Check your client ID/secret.'}), 400
            
            access_token = token_resp.json().get('access_token')
            sp_headers = {'Authorization': f'Bearer {access_token}'}
            
            tracks = []
            playlist_title = 'Spotify Playlist'
            
            if item_type == 'track':
                # Single track
                track_resp = http_requests.get(f'https://api.spotify.com/v1/tracks/{item_id}', headers=sp_headers, timeout=10)
                if track_resp.status_code != 200:
                    return jsonify({'error': 'Could not fetch track. It might be private or invalid.'}), 400
                t = track_resp.json()
                artist_names = ', '.join([a['name'] for a in t.get('artists', [])])
                query = f"{t['name']} {artist_names}"
                playlist_title = query
                tracks.append({'id': t['id'], 'title': query, 'duration': t.get('duration_ms', 0) // 1000, 'url': f'ytsearch1:{query}'})
                
            elif item_type == 'album':
                # Album
                album_resp = http_requests.get(f'https://api.spotify.com/v1/albums/{item_id}', headers=sp_headers, timeout=10)
                if album_resp.status_code != 200:
                    return jsonify({'error': 'Could not fetch album. It might be private or invalid.'}), 400
                album = album_resp.json()
                playlist_title = f"{album.get('name', 'Album')} — {', '.join([a['name'] for a in album.get('artists', [])])}"
                for t in album.get('tracks', {}).get('items', []):
                    artist_names = ', '.join([a['name'] for a in t.get('artists', [])])
                    query = f"{t['name']} {artist_names}"
                    tracks.append({'id': t['id'], 'title': query, 'duration': t.get('duration_ms', 0) // 1000, 'url': f'ytsearch1:{query}'})
                    
            else:
                # Playlist — may need pagination for large playlists
                pl_resp = http_requests.get(f'https://api.spotify.com/v1/playlists/{item_id}', headers=sp_headers, timeout=10)
                if pl_resp.status_code != 200:
                    return jsonify({'error': 'Could not fetch playlist. It might be private or invalid.'}), 400
                pl = pl_resp.json()
                playlist_title = pl.get('name', 'Spotify Playlist')
                
                # Fetch all tracks (handles pagination for playlists > 100 tracks)
                items = pl.get('tracks', {}).get('items', [])
                next_url = pl.get('tracks', {}).get('next')
                
                while next_url:
                    next_resp = http_requests.get(next_url, headers=sp_headers, timeout=10)
                    if next_resp.status_code != 200:
                        break
                    page = next_resp.json()
                    items.extend(page.get('items', []))
                    next_url = page.get('next')
                
                for item in items:
                    t = item.get('track')
                    if not t or not t.get('name'):
                        continue
                    artist_names = ', '.join([a['name'] for a in t.get('artists', [])])
                    query = f"{t['name']} {artist_names}"
                    tracks.append({'id': t.get('id', ''), 'title': query, 'duration': t.get('duration_ms', 0) // 1000, 'url': f'ytsearch1:{query}'})
            
            logger.info(f"Spotify: extracted {len(tracks)} tracks from {item_type} '{playlist_title}'")
            return jsonify({'playlistTitle': playlist_title, 'tracks': tracks})
        
        # --- Deezer → Free public API (no auth needed) ---
        if 'deezer.com' in url:
            result = _handle_deezer(url)
            if result and result.get('tracks'):
                logger.info(f"Deezer: extracted {len(result['tracks'])} tracks")
                return jsonify(result)
            return jsonify({'error': 'Could not extract tracks from Deezer. The link might be invalid or private.'}), 400

        # --- Apple Music → iTunes Lookup API (Accurate Song Lookup) → Fallback to Scrape ---
        if 'music.apple.com' in url:
            # Check for song track ID query parameter "?i=1488408488" or similar
            track_match = re.search(r'[?&]i=(\d+)', url)
            if track_match:
                track_id = track_match.group(1)
                try:
                    logger.info(f"Apple Music: trying iTunes API lookup for track {track_id}")
                    api_resp = http_requests.get(f'https://itunes.apple.com/lookup?id={track_id}', timeout=8)
                    if api_resp.status_code == 200:
                        res_data = api_resp.json()
                        if res_data.get('resultCount', 0) > 0:
                            track_info = res_data['results'][0]
                            song_title = f"{track_info.get('trackName', '')} {track_info.get('artistName', '')}".strip()
                            if song_title:
                                logger.info(f"Apple Music: iTunes API resolved track to '{song_title}'")
                                return jsonify({
                                    'playlistTitle': song_title,
                                    'tracks': [{
                                        'id': f'apple_{track_id}',
                                        'title': song_title,
                                        'duration': track_info.get('trackTimeMillis', 0) // 1000,
                                        'url': f'ytsearch1:{song_title}'
                                    }]
                                })
                except Exception as api_err:
                    logger.warning(f"iTunes API lookup failed: {api_err}")

            result = _handle_drm_platform(url, 'Apple Music', [
                r'\s*[-–—]\s*(?:Single|Album|EP|Playlist)\s+by\s+.*',
                r'\s+on\s+Apple\s*Music.*$',
                r'\s*[-–—]\s*Apple\s*Music.*$',
            ])
            if result and result.get('tracks'):
                return jsonify(result)
            return jsonify({'error': 'Could not extract song info from Apple Music. Try pasting a direct song link.'}), 400

        # --- Tidal → Scrape page metadata → YouTube search ---
        if 'tidal.com' in url:
            result = _handle_drm_platform(url, 'Tidal', [
                r'\s*[-–—|]\s*TIDAL.*$',
                r'\s+on\s+TIDAL.*$',
                r'\s*[-–—]\s*Tidal.*$',
            ])
            if result and result.get('tracks'):
                return jsonify(result)
            return jsonify({'error': 'Could not extract song info from Tidal. Try pasting a direct song link.'}), 400

        # --- Amazon Music → Scrape page metadata → YouTube search ---
        if 'music.amazon' in url or ('amazon.' in url and '/music' in url):
            result = _handle_drm_platform(url, 'Amazon Music', [
                r'\s*[-–—|]\s*Amazon\s*Music.*$',
                r'\s+on\s+Amazon\s*Music.*$',
                r'\s*\|\s*Amazon\.com.*$',
            ])
            if result and result.get('tracks'):
                return jsonify(result)
            return jsonify({'error': 'Could not extract song info from Amazon Music. Try pasting a direct song link.'}), 400

        # JioSaavn URLs fall through to yt-dlp native extraction below

        # --- Gaana → Scrape page metadata → YouTube search ---
        if 'gaana.com' in url:
            result = _handle_drm_platform(url, 'Gaana', [
                r'\s*[-–—|]\s*Gaana.*$',
                r'\s+on\s+Gaana.*$',
            ])
            if result and result.get('tracks'):
                return jsonify(result)
            return jsonify({'error': 'Could not extract song info from Gaana. Try pasting a direct song link.'}), 400

        # --- All other URLs: yt-dlp first, then page-scrape fallback ---
        # yt-dlp natively supports 1700+ sites including YouTube, SoundCloud,
        # Instagram, TikTok, Twitter/X, Facebook, Reddit, Bandcamp, Vimeo, etc.
        try:
            ydl_opts = {
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv_downgraded', 'android_vr', 'web_safari', 'ios', 'android']
                    }
                },
                'http_headers': {
                    'X-Forwarded-For': '192.168.1.1'
                }
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"yt-dlp: extracting info for: {url}")
                info = ydl.extract_info(url, download=False)

                if not info:
                    raise Exception('yt-dlp returned no info')

                tracks = []

                if 'entries' in info:
                    playlist_title = info.get('title') or 'Playlist / Album'
                    entries = info.get('entries', [])
                    for entry in entries:
                        if entry:
                            track_title = entry.get('title') or entry.get('name') or 'Unknown Track'
                            track_url = entry.get('url') or entry.get('webpage_url')
                            if not track_url and entry.get('id'):
                                track_url = f"https://www.youtube.com/watch?v={entry.get('id')}"

                            if track_url:
                                tracks.append({
                                    'id': entry.get('id') or track_url,
                                    'title': track_title,
                                    'duration': entry.get('duration'),
                                    'url': track_url
                                })
                else:
                    playlist_title = info.get('title') or 'Single Track'
                    tracks.append({
                        'id': info.get('id') or url,
                        'title': playlist_title,
                        'duration': info.get('duration'),
                        'url': url
                    })

                if tracks:
                    return jsonify({
                        'playlistTitle': playlist_title,
                        'tracks': tracks
                    })
                raise Exception('No playable tracks found')

        except Exception as ydl_err:
            # yt-dlp failed — try page scrape → YouTube search as last resort
            logger.info(f"yt-dlp failed for {url}, trying page-scrape fallback: {ydl_err}")
            fallback = _try_page_scrape_fallback(url)
            if fallback and fallback.get('tracks'):
                return jsonify(fallback)
            # Nothing worked — return the original yt-dlp error
            return jsonify({'error': f'Could not extract audio from this URL. {str(ydl_err)}'}), 400

    except Exception as e:
        logger.error(f"Error extracting playlist: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stream', methods=['GET'])
def get_stream():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400

    # --- Helper: try Piped API instances as fallback for YouTube ---
    PIPED_INSTANCES = [
        'https://api.piped.private.coffee',
        'https://pipedapi.kavin.rocks',
        'https://pipedapi.adminforge.de',
        'https://pipedapi.leptons.xyz',
    ]

    def _try_piped_stream(video_id):
        """Try multiple Piped API instances to get an audio stream URL."""
        for instance in PIPED_INSTANCES:
            try:
                api_url = f"{instance}/streams/{video_id}"
                logger.info(f"Piped fallback: trying {api_url}")
                resp = http_requests.get(api_url, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                audio_streams = data.get('audioStreams', [])
                
                # Fallback to combined video streams if no audio-only streams are returned
                is_video_fallback = False
                if not audio_streams:
                    video_streams = data.get('videoStreams', [])
                    audio_streams = [s for s in video_streams if not s.get('videoOnly', False)]
                    is_video_fallback = True
                    
                if not audio_streams:
                    continue
                # Pick the best quality audio stream (highest bitrate)
                best = max(audio_streams, key=lambda s: s.get('bitrate', 0))
                stream_url = best.get('url')
                if stream_url:
                    logger.info(f"Piped fallback SUCCESS from {instance} (video_fallback={is_video_fallback}): bitrate={best.get('bitrate')}, mime={best.get('mimeType')}")
                    return stream_url, best.get('mimeType', 'audio/webm')
            except Exception as e:
                logger.warning(f"Piped instance {instance} failed: {e}")
                continue
        return None, None



    # --- Main streaming logic ---
    ydl_opts = {
        'format': 'bestaudio/best',
        'skip_download': True,
        'quiet': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['tv_downgraded', 'android_vr', 'web_safari', 'ios', 'android']
            }
        },
        'http_headers': {
            'X-Forwarded-For': '192.168.1.1'
        }
    }
    
    stream_url = None
    content_type = 'audio/webm'

    # Step 1: Try yt-dlp first (works for non-YouTube sites and unblocked IPs)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get('url')
            
            if not stream_url and 'entries' in info and len(info['entries']) > 0:
                stream_url = info['entries'][0].get('url')
                
            if stream_url:
                logger.info(f"yt-dlp stream resolved successfully for: {url}")
    except Exception as e:
        logger.warning(f"yt-dlp stream failed for {url}: {e}")

    # Step 2: If yt-dlp failed, try Piped API for YouTube content
    if not stream_url:
        video_id = _extract_yt_video_id(url)
        
        # If it's a ytsearch1: query, resolve it to a video ID first
        if not video_id and url.startswith('ytsearch'):
            video_id, resolved_url = _resolve_ytsearch_to_id(url)
            if not video_id and resolved_url:
                video_id = _extract_yt_video_id(resolved_url)
        
        if video_id:
            logger.info(f"Trying Piped API fallback for video ID: {video_id}")
            stream_url, piped_mime = _try_piped_stream(video_id)
            if piped_mime:
                content_type = piped_mime

    # Step 3: If Piped fallback failed (or returned 403 / blocked), try SoundCloud search fallback!
    if not stream_url:
        logger.info("YouTube/Piped resolver failed. Attempting SoundCloud search fallback...")
        video_id = _extract_yt_video_id(url)
        title = "audio track"
        
        # If it was a search query, extract search query from URL as title
        if url.startswith('ytsearch1:'):
            title = url.replace('ytsearch1:', '')
        elif url.startswith('ytsearch:'):
            title = url.replace('ytsearch:', '')
        elif video_id:
            try:
                # Query private.coffee to get the official YouTube title
                r = http_requests.get(f"https://api.piped.private.coffee/streams/{video_id}", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    if data.get('title'):
                        title = data.get('title')
            except Exception as e:
                logger.warning(f"Could not get video title for SoundCloud search: {e}")
                
        # Refined query builder: split on separators and filter out video descriptors
        raw_parts = re.split(r'\||-|–|—|\[|\(', title)
        clean_parts = []
        video_descriptors = ['video', 'full', 'official', 'lyrical', 'lyrics', 'audio', 'song', 'hd', '4k', 'remaster', 'mv', 'clip']
        for part in raw_parts:
            part_clean = part.strip()
            if not part_clean or len(part_clean) < 2:
                continue
            is_descriptor = any(word in part_clean.lower() for word in video_descriptors)
            if not is_descriptor:
                clean_parts.append(part_clean)
                
        if len(clean_parts) >= 2:
            search_query_raw = f"{clean_parts[0]} {clean_parts[1]}"
        elif len(clean_parts) == 1:
            search_query_raw = clean_parts[0]
        else:
            search_query_raw = title
            
        # Clean title for search
        search_query = _clean_search_query(search_query_raw)
        logger.info(f"Searching SoundCloud for: '{search_query}'")
        try:
            ydl_opts_sc = {
                'format': 'bestaudio/best',
                'skip_download': True,
                'quiet': True,
                'no_warnings': True
            }
            with yt_dlp.YoutubeDL(ydl_opts_sc) as ydl:
                info = ydl.extract_info(f"scsearch1:{search_query}", download=False)
                if 'entries' in info and len(info['entries']) > 0:
                    stream_url = info['entries'][0].get('url')
                    logger.info(f"SoundCloud search fallback SUCCESS: resolved to '{info['entries'][0].get('title')}'")
        except Exception as e:
            logger.warning(f"SoundCloud search fallback failed: {e}")

    if not stream_url:
        return jsonify({'error': 'Could not resolve stream URL from any source'}), 400
    
    # Step 3: Proxy the resolved stream to the client
    try:
        headers = {}
        range_header = request.headers.get('Range', None)
        if range_header:
            headers['Range'] = range_header
            
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        
        req = http_requests.get(stream_url, headers=headers, stream=True, timeout=15)
        
        def generate():
            for chunk in req.iter_content(chunk_size=65536):
                yield chunk
        
        resp_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
        }
        
        if 'Content-Type' in req.headers:
            resp_headers['Content-Type'] = req.headers['Content-Type']
        else:
            resp_headers['Content-Type'] = content_type
        if 'Content-Length' in req.headers:
            resp_headers['Content-Length'] = req.headers['Content-Length']
        if 'Content-Range' in req.headers:
            resp_headers['Content-Range'] = req.headers['Content-Range']
        if 'Accept-Ranges' in req.headers:
            resp_headers['Accept-Ranges'] = req.headers['Accept-Ranges']
            
        return Response(
            stream_with_context(generate()),
            status=req.status_code,
            headers=resp_headers
        )

    except Exception as e:
        logger.error(f"Error proxying stream: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ==========================================
# YouTube ID Resolution API (Client-Side Streaming Help)
# ==========================================

@app.route('/api/resolve-yt-id', methods=['GET'])
def resolve_yt_id():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
        
    # 1. Extract direct video ID first (preserving case!)
    video_id = _extract_yt_video_id(url)
    if video_id:
        return jsonify({'videoId': video_id})
        
    # 2. If it is a search query, resolve it to a video ID
    if url.startswith('ytsearch'):
        video_id, resolved_url = _resolve_ytsearch_to_id(url)
        if not video_id and resolved_url:
            video_id = _extract_yt_video_id(resolved_url)
        if video_id:
            return jsonify({'videoId': video_id})
            
    # 3. Fallback: try flat extraction
    try:
        with yt_dlp.YoutubeDL({'extract_flat': True, 'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            vid_id = info.get('id')
            if vid_id and len(vid_id) == 11:
                return jsonify({'videoId': vid_id})
            if 'entries' in info and len(info['entries']) > 0:
                vid_id = info['entries'][0].get('id')
                if vid_id:
                    return jsonify({'videoId': vid_id})
    except Exception as e:
        logger.warning(f"resolve_yt_id extract_flat failed: {e}")
        
    return jsonify({'error': 'Could not resolve YouTube video ID'}), 404


# ==========================================
# Diagnostic Fallbacks Route
# ==========================================

@app.route('/api/test-fallbacks', methods=['GET'])
def test_fallbacks():
    results = {}
    video_id = 'II2EO3Nw4m0' # Badtameez Dil
    
    # 1. Test Invidious Instances list API
    try:
        r = http_requests.get('https://api.invidious.io/instances.json', timeout=5)
        results['invidious_instances_api'] = {
            'status': r.status_code,
            'length': len(r.json()) if r.status_code == 200 else 0
        }
    except Exception as e:
        results['invidious_instances_api'] = {'error': str(e)}
        
    # 2. Test direct Invidious URL
    invidious_tests = [
        'https://inv.nadeko.net',
        'https://invidious.nerdvpn.de',
        'https://yt.chocolatemoo53.com',
        'https://invidious.tiekoetter.com',
        'https://invidious.f5.si',
    ]
    results['invidious_nodes'] = {}
    for node in invidious_tests:
        try:
            r = http_requests.get(f"{node}/api/v1/videos/{video_id}", timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            results['invidious_nodes'][node] = {
                'status': r.status_code,
                'has_audio': ('adaptiveFormats' in r.json()) if r.status_code == 200 else False
            }
        except Exception as e:
            results['invidious_nodes'][node] = {'error': str(e)}
            
    # 3. Test Piped Nodes
    piped_tests = [
        'https://pipedapi.kavin.rocks',
        'https://pipedapi.leptons.xyz',
        'https://pipedapi-libre.kavin.rocks',
        'https://api.piped.yt',
        'https://api.piped.private.coffee',
    ]
    results['piped_nodes'] = {}
    for node in piped_tests:
        try:
            r = http_requests.get(f"{node}/streams/{video_id}", timeout=5)
            results['piped_nodes'][node] = {
                'status': r.status_code,
                'has_audio': ('audioStreams' in r.json()) if r.status_code == 200 else False
            }
        except Exception as e:
            results['piped_nodes'][node] = {'error': str(e)}
            
    return jsonify(results)

# ==========================================
# Multi-Device Sync API (Multi-Room Update)
# ==========================================

@app.route('/api/state', methods=['GET'])
def get_state():
    """Return the current shared room state for the requested room."""
    room_id = request.args.get('room', 'default')
    room_state, _ = get_room_state_and_announcer(room_id)
    return jsonify(room_state)

@app.route('/api/sync', methods=['POST'])
def post_sync():
    """
    Receive a control action from any client for a specific room.
    Updates room_state and broadcasts to all other connected SSE listeners in that room.
    """
    data = request.get_json(silent=True)
    if not data or 'action' not in data:
        return jsonify({'error': 'Missing action'}), 400
    
    room_id = data.get('room', 'default')
    action = data['action']
    channel = data.get('channel')  # "left", "right", or None for global actions
    
    room_state, announcer = get_room_state_and_announcer(room_id)
    
    with rooms_lock:
        room_state['ts'] = time.time()
        
        if action == 'play' and channel:
            room_state[channel]['playing'] = True
        
        elif action == 'pause' and channel:
            room_state[channel]['playing'] = False
        
        elif action == 'playBoth':
            room_state['left']['playing'] = True
            room_state['right']['playing'] = True
        
        elif action == 'pauseBoth':
            room_state['left']['playing'] = False
            room_state['right']['playing'] = False
        
        elif action == 'volume' and channel:
            room_state[channel]['volume'] = data.get('value', 80)
        
        elif action == 'mute' and channel:
            room_state[channel]['muted'] = data.get('value', False)
        
        elif action == 'source' and channel:
            room_state[channel]['source'] = data.get('value', 'none')
            # Clear playlist state when switching to a built-in source
            if not data.get('value', '').startswith('file:'):
                room_state[channel]['playlistTracks'] = []
                room_state[channel]['playlistIndex'] = -1
                room_state[channel]['playlistTitle'] = ''
        
        elif action == 'seek' and channel:
            room_state[channel]['currentTime'] = data.get('value', 0)
        
        elif action == 'loadPlaylist' and channel:
            room_state[channel]['playlistTitle'] = data.get('title', '')
            room_state[channel]['playlistTracks'] = data.get('tracks', [])
            room_state[channel]['playlistIndex'] = data.get('index', 0)
            room_state[channel]['source'] = 'none'
            room_state[channel]['playing'] = True
        
        elif action == 'playTrack' and channel:
            room_state[channel]['playlistIndex'] = data.get('index', 0)
            room_state[channel]['playing'] = True
        
        elif action == 'swap':
            room_state['swapped'] = data.get('value', False)
    
    # Broadcast only to the announcer for this room
    event_data = {**data, 'ts': room_state['ts']}
    announcer.announce(format_sse(event_data, event='sync'))
    
    return jsonify({'ok': True})

@app.route('/api/events')
def sse_stream():
    """SSE endpoint. Clients connect here with EventSource to receive real-time sync events for their room."""
    room_id = request.args.get('room', 'default')
    _, announcer = get_room_state_and_announcer(room_id)
    
    def stream():
        q = announcer.listen()
        try:
            # Send an initial heartbeat
            yield format_sse({'type': 'connected', 'room': room_id}, event='hello')
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield msg
                except queue.Empty:
                    # Send keepalive comment to prevent proxy/browser timeout
                    yield ': keepalive\n\n'
        except GeneratorExit:
            announcer.remove(q)
    
    return Response(
        stream_with_context(stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*',
        }
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)

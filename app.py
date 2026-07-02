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
from playwright.sync_api import sync_playwright

app = Flask(__name__, static_folder='.')
CORS(app)

# Configure logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

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

@app.route('/')
def index():
    return send_from_directory('.', 'dual-channel-player (2).html')

@app.route('/<path:path>')
def serve_static(path):
    # Don't match API routes
    if path.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory('.', path)

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
            match = re.search(r'(playlist|album|track)[/:]([a-zA-Z0-9]+)', url)
            if not match:
                return jsonify({'error': 'Invalid Spotify URL format'}), 400
                
            item_type = match.group(1)
            item_id = match.group(2)
            embed_url = f"https://open.spotify.com/embed/{item_type}/{item_id}"
            
            logger.info(f"Extracting Spotify playlist via embed: {embed_url}")
            
            tracks = []
            playlist_title = "Spotify Converted Playlist"
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(embed_url, wait_until='networkidle', timeout=15000)
                page.wait_for_timeout(3000) # Give it time to render tracks
                
                text_content = page.evaluate("() => document.body.innerText")
                
                # Try getting the title
                try:
                    title_elem = page.query_selector('h1')
                    if title_elem:
                        playlist_title = title_elem.inner_text()
                except:
                    pass
                    
                browser.close()
                
                extracted_tracks = []
                lines = text_content.split('\n')
                for i in range(len(lines)):
                    line = lines[i].strip()
                    if line.isdigit() and int(line) > 0:
                        if i + 3 < len(lines):
                            title = lines[i+1].strip()
                            artist_raw = lines[i+2].strip()
                            artist = artist_raw[1:] if (artist_raw.startswith('E') and len(artist_raw) > 1) else artist_raw
                            time_raw = lines[i+3].strip()
                            if re.match(r'^\d+:\d+$', time_raw):
                                extracted_tracks.append({'title': title, 'artist': artist})
                
                if not extracted_tracks:
                    return jsonify({'error': 'Could not extract tracks from Spotify. Playlist might be private or invalid.'}), 400
                    
                for idx, t in enumerate(extracted_tracks):
                    title = t.get('title', '')
                    artist = t.get('artist', '')
                    if title:
                        query = f"{title} {artist}".strip()
                        tracks.append({
                            'id': f"spotify-{item_id}-{idx}",
                            'title': query,
                            'duration': 0, # Don't have exact duration here
                            'url': f"ytsearch1:{query}"
                        })
                        
            return jsonify({
                'playlistTitle': playlist_title,
                'tracks': tracks
            })
        
        # --- Handle YouTube/SoundCloud etc ---
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'X-Forwarded-For': '192.168.1.1' # Simple spoofing to reduce block chance
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Extracting playlist info for: {url}")
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return jsonify({'error': 'Could not extract playlist info'}), 400
            
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
                
            return jsonify({
                'title': playlist_title,
                'tracks': tracks
            })
            
    except Exception as e:
        logger.error(f"Error extracting playlist: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stream', methods=['GET'])
def get_stream():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
        
    ydl_opts = {
        'format': 'bestaudio/best',
        'skip_download': True,
        'quiet': True,
        'http_headers': {
            'X-Forwarded-For': '192.168.1.1' # Simple spoofing to reduce block chance
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get('url')
            
            # For ytsearch1: queries, the url is inside entries[0]
            if not stream_url and 'entries' in info and len(info['entries']) > 0:
                stream_url = info['entries'][0].get('url')
                
            if not stream_url:
                return jsonify({'error': 'Could not resolve stream URL'}), 400
            
            headers = {}
            range_header = request.headers.get('Range', None)
            if range_header:
                headers['Range'] = range_header
                
            headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            
            req = http_requests.get(stream_url, headers=headers, stream=True, timeout=15)
            
            def generate():
                for chunk in req.iter_content(chunk_size=65536): # 64KB chunks for optimized streaming
                    yield chunk
            
            resp_headers = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
            }
            
            if 'Content-Type' in req.headers:
                resp_headers['Content-Type'] = req.headers['Content-Type']
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
        logger.error(f"Error getting stream: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
    app.run(host='0.0.0.0', port=8000, debug=True, threaded=True)

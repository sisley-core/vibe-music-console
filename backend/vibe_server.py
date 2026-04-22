#!/usr/bin/env python3
"""
Vibe Console V2 — 智能音乐系统
per-profile per-genre 预建库架构 + 渐变混播
Smart Play v5: UI 轮询加库 → 原生 AppleScript 播放
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import subprocess
import threading
import logging
import json
import os
import time
import urllib.request
import urllib.parse
import ssl
import random
import re
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger()

# macOS Python 3.12 缺失根证书，全局禁用 SSL 验证
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# ===== 配置（从环境变量或 .env 文件读取）=====
def _load_env():
    """Load .env file if exists"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

# LLM API (DeepSeek, OpenAI, or any OpenAI-compatible API)
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.deepseek.com/v1')
LLM_MODEL = os.environ.get('LLM_MODEL', 'deepseek-chat')

MEMORY_DIR = os.environ.get('MEMORY_DIR', os.path.expanduser('~/vibe-console/memory'))
os.makedirs(MEMORY_DIR, exist_ok=True)

# ===== LG TV 配置 =====
LG_TV_IP = os.environ.get('LG_TV_IP', '192.168.1.100')
LG_TV_MAC = os.environ.get('LG_TV_MAC', 'AA:BB:CC:DD:EE:FF')
LG_HDMI_APPLETV = os.environ.get('LG_HDMI_APPLETV', 'HDMI_1')
LG_HDMI_MAC = os.environ.get('LG_HDMI_MAC', 'HDMI_3')

# ===== GLM MIDI 配置 =====
GLM_MIDI_CH = 0
current_volume = 107  # 初始 -20dB
mute_saved_volume = None  # None = not muted
current_glm_group = 'HiFi'  # 'HiFi' or 'Movie'

# ===== 家庭成员（每人 4 风格，各自独立）=====
# Customize these profiles for your household. Each person gets 4 genres
# with AI prompts, neighbor relationships for journey mode, and time-of-day weights.
PROFILES = {
    'alice': {
        'name': 'Alice',
        'preferences': {
            'description': 'Loves jazz, bossa nova, classical piano, ambient electronic. Dislikes heavy metal and rap.',
        },
        'genres': {
            'Jazz':        {'prompt': '【Strictly Jazz】: Swing/Bebop/Cool Jazz/Bossa Nova/Fusion/Vocal Jazz/Latin Jazz.', 'playlist': 'Vibe_Alice_Jazz'},
            'Classical':   {'prompt': '【Strictly Classical】: Symphony/Chamber/Piano Solo/Concerto/Baroque/Romantic.', 'playlist': 'Vibe_Alice_Classical'},
            'Electronic':  {'prompt': '【Strictly Electronic】: Ambient/House/Techno/IDM/Downtempo/Synthwave.', 'playlist': 'Vibe_Alice_Electronic'},
            'Pop':         {'prompt': '【Strictly Pop】: Indie Pop/Dream Pop/Synth Pop/Art Pop.', 'playlist': 'Vibe_Alice_Pop'},
        },
        'neighbors': {
            'Jazz': ['Classical', 'Pop'], 'Classical': ['Jazz', 'Electronic'],
            'Electronic': ['Classical', 'Pop'], 'Pop': ['Jazz', 'Electronic'],
        },
        'time_weights': {
            'morning':   {'Jazz': 3, 'Classical': 2, 'Electronic': 0.5, 'Pop': 1},
            'afternoon': {'Pop': 3, 'Electronic': 2, 'Jazz': 1, 'Classical': 0.5},
            'evening':   {'Classical': 3, 'Jazz': 2, 'Electronic': 1, 'Pop': 0.5},
            'night':     {'Classical': 2, 'Jazz': 2, 'Electronic': 1, 'Pop': 0.5},
        },
    },
    'bob': {
        'name': 'Bob',
        'preferences': {
            'description': 'Loves electronic, trip-hop, brit-rock, new wave. Dislikes country.',
        },
        'genres': {
            'Electronic':  {'prompt': '【Strictly Electronic】: Ambient/House/Techno/IDM/Downtempo/Chillwave.', 'playlist': 'Vibe_Bob_Electronic'},
            'TripHop':     {'prompt': '【Strictly Trip-Hop/Downtempo】: Portishead/Massive Attack/Tricky/Morcheeba/DJ Shadow style.', 'playlist': 'Vibe_Bob_TripHop'},
            'BritRock':    {'prompt': '【Strictly Brit-Rock】: Britpop/Shoegaze/Post-Punk/Indie Rock.', 'playlist': 'Vibe_Bob_BritRock'},
            'NewWave':     {'prompt': '【Strictly New Wave/Synth-Pop/Post-Punk】: Depeche Mode/New Order/Tears for Fears/The Cure.', 'playlist': 'Vibe_Bob_NewWave'},
        },
        'neighbors': {
            'Electronic': ['TripHop', 'NewWave'], 'TripHop': ['Electronic', 'BritRock'],
            'BritRock': ['TripHop', 'NewWave'], 'NewWave': ['BritRock', 'Electronic'],
        },
        'time_weights': {
            'morning':   {'Electronic': 2, 'TripHop': 1, 'BritRock': 0.5, 'NewWave': 1},
            'afternoon': {'BritRock': 3, 'NewWave': 2, 'Electronic': 1, 'TripHop': 1},
            'evening':   {'TripHop': 3, 'Electronic': 2, 'NewWave': 1, 'BritRock': 1},
            'night':     {'TripHop': 3, 'Electronic': 2, 'NewWave': 1, 'BritRock': 0.5},
        },
    },
    'grandma': {
        'name': 'Grandma',
        'preferences': {
            'description': 'Loves classic oldies, Motown, Frank Sinatra, Nat King Cole, film soundtracks.',
        },
        'genres': {
            'GoldenOldies': {'prompt': '【Strictly 50s-70s Golden Oldies】: Frank Sinatra/Nat King Cole/Dean Martin/Ella Fitzgerald. Only classic well-known songs.', 'playlist': 'Vibe_Grandma_GoldenOldies'},
            'Motown':       {'prompt': '【Strictly Motown/Soul】: Stevie Wonder/Marvin Gaye/The Temptations/Aretha Franklin/The Supremes.', 'playlist': 'Vibe_Grandma_Motown'},
            'Country':      {'prompt': '【Strictly Classic Country】: Johnny Cash/Patsy Cline/Dolly Parton/Willie Nelson. Only timeless classics.', 'playlist': 'Vibe_Grandma_Country'},
            'OST':          {'prompt': '【Strictly Classic Film Soundtracks】: The Sound of Music/Singin in the Rain/West Side Story/My Fair Lady. Only iconic film songs.', 'playlist': 'Vibe_Grandma_OST'},
        },
        'neighbors': {
            'GoldenOldies': ['Motown', 'Country'], 'Motown': ['GoldenOldies', 'OST'],
            'Country': ['GoldenOldies', 'OST'], 'OST': ['Motown', 'Country'],
        },
        'time_weights': {
            'morning':   {'GoldenOldies': 2, 'Motown': 2, 'Country': 1, 'OST': 1},
            'afternoon': {'Motown': 2, 'GoldenOldies': 2, 'OST': 1, 'Country': 1},
            'evening':   {'GoldenOldies': 3, 'OST': 2, 'Motown': 1, 'Country': 1},
            'night':     {'GoldenOldies': 3, 'OST': 2, 'Motown': 1, 'Country': 0.5},
        },
    },
}


def _get_profile_genres(profile):
    """获取角色的风格列表"""
    return list(PROFILES.get(profile, {}).get('genres', {}).keys())


def _get_genre_prompt(profile, genre):
    """获取角色某个风格的 prompt 约束"""
    return PROFILES.get(profile, {}).get('genres', {}).get(genre, {}).get('prompt', '')


def _get_genre_playlist(profile, genre):
    """获取角色某个风格的播放列表名"""
    return PROFILES.get(profile, {}).get('genres', {}).get(genre, {}).get('playlist', f'Vibe_{profile}_{genre}')


def _get_genre_neighbors(profile, genre):
    """获取角色某个风格的邻居"""
    return PROFILES.get(profile, {}).get('neighbors', {}).get(genre, [])

# ===== 全局状态 =====
vibe_state = {
    'status': 'idle',           # idle / playing
    'active_profile': None,     # 当前角色
    'current_genre': None,      # 当前播放的风格
    'play_mode': None,          # 'genre' / 'journey' / None
    'current_track': None,      # {"title": ..., "artist": ...}
    'songs_in_current_genre': 0,  # 旅程模式计数
    'previous_genre': None,     # 旅程模式：上一个风格（避免回头）
    'energy': 50,
    'mood': 50,
    'discovery': 30,
    'watchdog_active': False,
}

# 库元数据缓存: library_meta[profile][genre] = [song_meta, ...]
library_meta = {}
# 最近播放记录（用于选歌时排除）: recent_played[profile][genre] = [title, ...]
recent_played = {}
# 后台补货锁
_refill_locks = {}
_refill_active = {}  # 跟踪正在补货的 profile+genre

TOUCHSTRIP_FILE = '/tmp/vibe_touchstrip.txt'
TOUCHSTRIP_UUID = 'C537D17A-99BB-44EC-BCE0-E6BCC53438FD'
BTT_PORT = 12345  # BTT 内置 webserver 端口

def _push_to_btt(text):
    """通过 BTT refresh_widget 立即刷新触摸条（让 BTT 重新执行 cat 脚本）"""
    try:
        import urllib.request
        url = f'http://127.0.0.1:{BTT_PORT}/refresh_widget/?uuid={TOUCHSTRIP_UUID}'
        urllib.request.urlopen(url, timeout=0.5)
    except Exception:
        pass

def _write_touchstrip():
    """计算触摸条文本（始终2行），写入文件，然后通知 BTT 刷新"""
    try:
        db_val = current_volume - 127
        muted = '🔇' if mute_saved_volume is not None else '🔊'
        e = vibe_state['energy']
        m = vibe_state['mood']
        d = vibe_state['discovery']
        bar = f"{muted} {db_val}    ┃    ⚡ 静 {e} 燃    ┃    🌗 暗 {m} 亮    ┃    🔮 经典 {d} 小众"

        # 第一行: GLM组名 + 歌名(如有) + 歌手(如有)
        parts = [current_glm_group]
        track = vibe_state.get('current_track')
        if track:
            parts.append(track.get('title', '')[:25])
            if track.get('artist'):
                parts.append(track['artist'][:20])
        line1 = '  '.join(parts)

        text = f"{line1}\n{bar}"
        with open(TOUCHSTRIP_FILE, 'w', encoding='utf-8') as f:
            f.write(text)
        # 写完后立即通知 BTT 刷新 widget
        threading.Thread(target=_push_to_btt, args=(text,), daemon=True).start()
    except Exception:
        pass


# ===== 元数据管理 =====
def _meta_path(profile, genre):
    return os.path.join(MEMORY_DIR, f'library_{profile}_{genre}.json')


def _load_library_meta(profile, genre):
    """加载风格库元数据"""
    key = f'{profile}_{genre}'
    path = _meta_path(profile, genre)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        library_meta.setdefault(profile, {})[genre] = data
        return data
    library_meta.setdefault(profile, {})[genre] = []
    return []


def _save_library_meta(profile, genre):
    """保存风格库元数据"""
    data = library_meta.get(profile, {}).get(genre, [])
    path = _meta_path(profile, genre)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_library_meta(profile, genre):
    """获取库元数据（内存优先）"""
    if profile in library_meta and genre in library_meta[profile]:
        return library_meta[profile][genre]
    return _load_library_meta(profile, genre)


def _add_to_library_meta(profile, genre, title, artist, source='ai'):
    """添加歌曲到库元数据"""
    meta = _get_library_meta(profile, genre)
    # 去重
    for m in meta:
        if m['title'] == title and m['artist'] == artist:
            return
    meta.append({
        'title': title,
        'artist': artist,
        'genre': genre,
        'added_date': datetime.now().strftime('%Y-%m-%d'),
        'last_played': None,
        'play_count': 0,
        'loved': False,
        'skip_count': 0,
        'source': f'{source}_{datetime.now().strftime("%Y%m%d")}',
    })
    _save_library_meta(profile, genre)


def _get_recent_played(profile, genre):
    """获取最近播放列表"""
    return recent_played.get(profile, {}).get(genre, [])


def _add_recent_played(profile, genre, title):
    """记录最近播放（保留 20 首）"""
    recent_played.setdefault(profile, {}).setdefault(genre, [])
    lst = recent_played[profile][genre]
    if title in lst:
        lst.remove(title)
    lst.append(title)
    if len(lst) > 20:
        lst.pop(0)


# ===== 播放列表管理 (AppleScript) =====
def _playlist_name(profile, genre):
    """生成播放列表名（从 profile 配置读取）"""
    return _get_genre_playlist(profile, genre)


def _ensure_playlist_exists(playlist_name):
    """确保播放列表存在"""
    script = f'''
    tell application "Music"
        try
            set p to user playlist "{playlist_name}"
        on error
            make new user playlist with properties {{name:"{playlist_name}"}}
        end try
        return "OK"
    end tell
    '''
    try:
        subprocess.run(['osascript', '-e', script],
                      capture_output=True, text=True, timeout=10)
    except Exception as e:
        log.warning(f"Ensure playlist failed: {e}")


def _add_to_playlist(playlist_name, song, artist):
    """将已入库歌曲添加到指定播放列表"""
    safe_song = song.replace('"', '\\"').replace("'", "\\'")
    safe_artist = artist.replace('"', '\\"').replace("'", "\\'")
    script = f'''
    tell application "Music"
        set vibeList to user playlist "{playlist_name}"
        -- 检查是否已在列表中
        repeat with t in tracks of vibeList
            if name of t is "{safe_song}" then return "ALREADY"
        end repeat
        -- 搜索资料库并添加
        set results to (search library playlist 1 for "{safe_song}" only songs)
        repeat with t in results
            if (artist of t) contains "{safe_artist}" or "{safe_artist}" contains (artist of t) then
                duplicate t to vibeList
                return "ADDED"
            end if
        end repeat
        if (count of results) > 0 then
            duplicate item 1 of results to vibeList
            return "ADDED_FALLBACK"
        end if
        return "NOT_FOUND"
    end tell
    '''
    try:
        r = subprocess.run(['osascript', '-e', script],
                          capture_output=True, text=True, timeout=10)
        result = r.stdout.strip()
        return result.startswith("ADDED") or result == "ALREADY"
    except Exception as e:
        log.warning(f"Add to playlist failed: {e}")
        return False


def _get_playlist_tracks(playlist_name):
    """获取播放列表中的所有歌曲"""
    script = f'''
    tell application "Music"
        try
            set vibeList to user playlist "{playlist_name}"
            set output to ""
            repeat with t in tracks of vibeList
                set output to output & (name of t) & " ||| " & (artist of t) & linefeed
            end repeat
            return output
        on error
            return "NO_PLAYLIST"
        end try
    end tell
    '''
    try:
        r = subprocess.run(['osascript', '-e', script],
                          capture_output=True, text=True, timeout=15)
        output = r.stdout.strip()
        if output == "NO_PLAYLIST" or not output:
            return []
        tracks = []
        for line in output.split('\n'):
            line = line.strip()
            if ' ||| ' in line:
                parts = line.split(' ||| ')
                tracks.append({'title': parts[0], 'artist': parts[1] if len(parts) > 1 else ''})
        return tracks
    except Exception as e:
        log.warning(f"Get playlist tracks failed: {e}")
        return []


# ===== 播放历史 =====
def _log_play_history(profile, title, artist, genre, action, duration_pct, trigger, mode):
    """记录播放历史到 JSONL 文件"""
    path = os.path.join(MEMORY_DIR, f'play_history_{profile}.jsonl')
    entry = {
        'title': title,
        'artist': artist,
        'genre': genre,
        'profile': profile,
        'action': action,
        'duration_pct': duration_pct,
        'timestamp': datetime.now().isoformat(),
        'trigger': trigger,
        'mode': mode,
    }
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        log.warning(f"Play history write failed: {e}")


# ===== DeepSeek API =====
def _ask_deepseek_batch(prompt, max_retries=2):
    """调用 DeepSeek API，返回 JSON 数组"""
    payload = json.dumps({
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': '你是一个顶级音乐推荐引擎。只输出JSON数组，不要输出其他任何内容。'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.9,
        'max_tokens': 800
    }).encode('utf-8')

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LLM_API_KEY}'
    }

    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(
                f'{LLM_BASE_URL}/chat/completions',
                data=payload, headers=headers
            )
            with urllib.request.urlopen(req, context=_ssl_ctx, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                content = data['choices'][0]['message']['content'].strip()
                if content.startswith('```'):
                    content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return [parsed]
                return parsed
        except Exception as e:
            log.warning(f"DeepSeek batch attempt {attempt+1} failed: {e}")
            if attempt < max_retries:
                time.sleep(1)
    return None


# ===== iTunes / Apple Music 验证 =====
def _verify_on_apple_music(song, artist):
    """通过 iTunes API 验证歌曲在 Apple Music 上是否存在"""
    try:
        query = urllib.parse.quote(f"{artist} {song}")
        url = f"https://itunes.apple.com/search?term={query}&entity=song&limit=3"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data['resultCount'] > 0:
                track = data['results'][0]
                track_id = track.get('trackId', '')
                collection_url = track.get('collectionViewUrl', '')
                track_url = track.get('trackViewUrl', '')

                play_url = ''
                if collection_url and track_id:
                    sep = '&' if '?' in collection_url else '?'
                    play_url = f"{collection_url}{sep}i={track_id}"
                elif track_url:
                    play_url = _convert_song_url_to_album_url(track_url, track_id) or track_url

                return {
                    'song': track.get('trackName', song),
                    'artist': track.get('artistName', artist),
                    'play_url': play_url,
                    'track_id': str(track_id),
                    'verified': True
                }
    except Exception as e:
        log.warning(f"iTunes verify failed: {e}")
    return None


def _convert_song_url_to_album_url(song_url, track_id=None):
    """将 /song/ URL 转换为 /album/?i= 格式"""
    match = re.search(r'/song/[^/]+/(\d+)', song_url)
    if not match:
        return None
    song_id = match.group(1)
    try:
        lookup_url = f"https://itunes.apple.com/lookup?id={song_id}&entity=album"
        req = urllib.request.Request(lookup_url)
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            for result in data.get('results', []):
                if result.get('wrapperType') == 'collection':
                    album_url = result.get('collectionViewUrl', '')
                    if album_url:
                        sep = '&' if '?' in album_url else '?'
                        return f"{album_url}{sep}i={song_id}"
    except Exception:
        pass
    return None


# ===== Smart Play v5 引擎（从 V1 移植） =====
def _check_music_playing():
    try:
        result = subprocess.run(
            ['osascript', '-e', 'tell application "Music" to get player state'],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and result.stdout.strip() == 'playing'
    except Exception:
        return False


def _ensure_music_frontmost():
    try:
        subprocess.run(['osascript', '-e', '''
            tell application "Music" to activate
            delay 0.5
            tell application "System Events"
                tell process "Music"
                    set frontmost to true
                    delay 0.3
                    if (count of windows) is 0 then
                        try
                            click menu item "Music" of menu "Window" of menu bar 1
                        end try
                        delay 1
                        if (count of windows) is 0 then
                            keystroke "1" using command down
                            delay 1
                        end if
                    end if
                end tell
            end tell
        '''], capture_output=True, text=True, timeout=10)
    except Exception as e:
        log.warning(f"Ensure Music frontmost failed: {e}")


def _add_to_library_via_ui():
    add_script = '''
    tell application "Music" to activate
    delay 0.5
    tell application "System Events"
        tell process "Music"
            try
                set sa to scroll area 2 of splitter group 1 of window 1
                set albumHeader to UI element 1 of list 1 of list 1 of sa
                repeat with b in (every button of albumHeader)
                    if description of b is "添加" then
                        click b
                        return "CLICKED_ADD"
                    end if
                end repeat
                return "NO_ADD_BUTTON"
            on error errMsg
                return "ERROR:" & errMsg
            end try
        end tell
    end tell
    '''
    try:
        r = subprocess.run(['osascript', '-e', add_script],
                          capture_output=True, text=True, timeout=10)
        output = r.stdout.strip()
        log.info(f"AddToLibrary UI: {output}")
        return output == "CLICKED_ADD" or output == "NO_ADD_BUTTON"
    except Exception as e:
        log.warning(f"AddToLibrary UI failed: {e}")
        return False


def _wait_for_page_load(max_wait=15):
    check_script = '''
    tell application "Music" to activate
    delay 0.3
    tell application "System Events"
        tell process "Music"
            try
                set sa to scroll area 2 of splitter group 1 of window 1
                set mainList to list 1 of sa
                set subCount to count of (every list of mainList)
                try
                    set errBtn to (first button of sa whose name is "重试")
                    click errBtn
                    return "RETRYING"
                end try
                if subCount >= 2 then
                    return "LOADED:" & subCount
                end if
                return "LOADING:" & subCount
            on error errMsg
                return "ERROR:" & errMsg
            end try
        end tell
    end tell
    '''
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = subprocess.run(['osascript', '-e', check_script],
                              capture_output=True, text=True, timeout=10)
            output = r.stdout.strip()
            if output.startswith("LOADED:"):
                return True
            elif output == "RETRYING":
                time.sleep(3)
            else:
                time.sleep(1.5)
        except Exception:
            time.sleep(1.5)
    return False


def _search_library_and_play(song, artist):
    """在资料库中搜索歌曲并用原生 AppleScript 播放"""
    safe_song = song.replace('"', '\\"').replace("'", "\\'")
    safe_artist = artist.replace('"', '\\"').replace("'", "\\'")

    search_terms = [safe_song]
    simplified = re.sub(r'\s*[\(（\[].*?[\)）\]]', '', song)
    simplified = re.sub(r',.*$', '', simplified)
    simplified = re.sub(r'\s*Op\.?\s*\d+.*$', '', simplified, flags=re.IGNORECASE)
    simplified = re.sub(r'\s*BWV\s*\d+.*$', '', simplified, flags=re.IGNORECASE)
    simplified = re.sub(r'\s*No\.?\s*\d+.*$', '', simplified, flags=re.IGNORECASE)
    simplified = simplified.strip()
    if simplified and simplified != song:
        search_terms.append(simplified.replace('"', '\\"').replace("'", "\\'"))

    for term in search_terms:
        script = f'''
        tell application "Music"
            set results to (search library playlist 1 for "{term}" only songs)
            if (count of results) is 0 then return "NOT_FOUND"
            repeat with t in results
                if (artist of t) contains "{safe_artist}" or "{safe_artist}" contains (artist of t) then
                    play t
                    delay 1
                    return "PLAYING:" & (name of t) & " - " & (artist of t)
                end if
            end repeat
            play item 1 of results
            delay 1
            return "PLAYING:" & (name of item 1 of results) & " - " & (artist of item 1 of results)
        end tell
        '''
        try:
            r = subprocess.run(['osascript', '-e', script],
                              capture_output=True, text=True, timeout=10)
            output = r.stdout.strip()
            if output.startswith("PLAYING:"):
                log.info(f"Library play: {output}")
                return True
        except Exception as e:
            log.warning(f"Library search/play failed: {e}")
    return False


def _is_in_library(song, artist):
    """检查歌曲是否已在本地资料库中"""
    safe_song = song.replace('"', '\\"').replace("'", "\\'")
    safe_artist = artist.replace('"', '\\"').replace("'", "\\'")
    search_terms = [safe_song]
    simplified = re.sub(r'\s*[\(（\[].*?[\)）\]]', '', song)
    simplified = re.sub(r',.*$', '', simplified)
    simplified = simplified.strip()
    if simplified and simplified != song:
        search_terms.append(simplified.replace('"', '\\"').replace("'", "\\'"))

    for term in search_terms:
        script = f'''
        tell application "Music"
            set results to (search library playlist 1 for "{term}" only songs)
            repeat with t in results
                if (artist of t) contains "{safe_artist}" or "{safe_artist}" contains (artist of t) then
                    return "FOUND"
                end if
            end repeat
            return "NOT_FOUND"
        end tell
        '''
        try:
            r = subprocess.run(['osascript', '-e', script],
                              capture_output=True, text=True, timeout=10)
            if r.stdout.strip() == "FOUND":
                return True
        except Exception:
            pass
    return False


def _add_song_to_library_only(song, artist, verified_info=None):
    """仅加库不播放"""
    if _is_in_library(song, artist):
        return True

    play_url = None
    if verified_info and verified_info.get('play_url'):
        play_url = verified_info['play_url']
    else:
        info = _verify_on_apple_music(song, artist)
        if info and info.get('play_url'):
            play_url = info['play_url']

    if not play_url:
        return False

    music_url = play_url.replace('https://', 'music://')
    try:
        subprocess.run(['open', music_url], check=True, capture_output=True, timeout=10)
    except Exception:
        return False

    _ensure_music_frontmost()
    if not _wait_for_page_load(max_wait=15):
        return False

    time.sleep(0.5)
    ui_clicked = _add_to_library_via_ui()

    time.sleep(6)
    deadline = time.time() + 20
    while time.time() < deadline:
        if _is_in_library(song, artist):
            return True
        time.sleep(2)

    # UI 成功点了添加但搜索验证找不到（常见于中文歌曲），信任 UI 结果
    if ui_clicked:
        log.info(f"AddToLibrary: UI clicked add but search verify failed, trusting UI for '{song}'")
        return True
    return False


def _smart_play(song, artist, verified_info=None):
    """Smart Play v5: 搜库秒播 → URL加库 → 原生播放"""
    log.info(f"SmartPlay v5: '{song}' - '{artist}'")

    # 策略1: 直接搜索本地资料库
    if _search_library_and_play(song, artist):
        log.info(f"SmartPlay: ✓ Already in library")
        return True

    # 策略2: 获取 URL
    play_url = None
    if verified_info and verified_info.get('play_url'):
        play_url = verified_info['play_url']
    else:
        info = _verify_on_apple_music(song, artist)
        if info and info.get('play_url'):
            play_url = info['play_url']

    if not play_url:
        log.warning(f"SmartPlay: ✗ No URL for '{song}'")
        return False

    # 策略3: URL 加库 → 原生播放
    music_url = play_url.replace('https://', 'music://')
    try:
        subprocess.run(['osascript', '-e', 'tell application "Music" to pause'],
                      capture_output=True, text=True, timeout=5)
        time.sleep(0.3)
    except Exception:
        pass

    try:
        subprocess.run(['open', music_url], check=True, capture_output=True, timeout=10)
    except Exception as e:
        log.warning(f"SmartPlay: open URL failed: {e}")
        return False

    _ensure_music_frontmost()
    if not _wait_for_page_load(max_wait=15):
        return False

    time.sleep(0.5)
    add_ok = _add_to_library_via_ui()
    if add_ok:
        time.sleep(6)
        sync_deadline = time.time() + 25
        while time.time() < sync_deadline:
            if _search_library_and_play(song, artist):
                log.info(f"SmartPlay: ✓ Added and playing")
                return True
            time.sleep(2)

    # 最终 fallback
    try:
        subprocess.run(['osascript', '-e', 'tell application "Music" to play'],
                      capture_output=True, text=True, timeout=5)
        time.sleep(1)
        if _check_music_playing():
            return True
    except Exception:
        pass

    log.warning(f"SmartPlay: ✗ All strategies failed for '{song}'")
    return False


# ===== 选歌逻辑 =====
def _pick_song_from_library(profile, genre):
    """从风格库选歌：排除最近20首 → loved 30% → 新歌优先 → 随机"""
    meta = _get_library_meta(profile, genre)
    if not meta:
        return None

    recent = set(_get_recent_played(profile, genre))
    available = [m for m in meta if m['title'] not in recent]

    if not available:
        # 全部播过了，放宽限制
        available = list(meta)

    if not available:
        return None

    # loved 歌 30% 概率
    loved = [m for m in available if m.get('loved')]
    others = [m for m in available if not m.get('loved')]

    if loved and random.random() < 0.3:
        pool = loved
    else:
        # 新入库优先：按 added_date 降序，最新的排前面
        others.sort(key=lambda m: m.get('added_date', ''), reverse=True)
        # 前 1/3 新歌权重 ×2
        if len(others) > 3:
            new_count = max(1, len(others) // 3)
            weighted = others[:new_count] * 2 + others[new_count:]
            pool = weighted
        else:
            pool = others if others else loved

    pick = random.choice(pool)
    return pick


# ===== 统一填充逻辑 =====
def _check_and_refill(profile, genre):
    """统一填充：检查库存水位 → 触发后台补货"""
    meta = _get_library_meta(profile, genre)
    recent = set(_get_recent_played(profile, genre))
    available = len([m for m in meta if m['title'] not in recent])

    if available < 10:
        key = f'{profile}_{genre}'
        if key not in _refill_active or not _refill_active[key]:
            _refill_active[key] = True
            threading.Thread(
                target=_background_refill,
                args=(profile, genre),
                daemon=True
            ).start()


def _background_refill(profile, genre):
    """后台补货线程：AI 生成 10 首 → 验证 → 加库 → 加播放列表"""
    key = f'{profile}_{genre}'
    try:
        log.info(f"🔄 Refill: Starting for {profile}/{genre}")
        profile_data = PROFILES.get(profile, {})
        prefs = profile_data.get('preferences', {})
        meta = _get_library_meta(profile, genre)

        # 收集信号
        loved_songs = [f"{m['title']} - {m['artist']}" for m in meta if m.get('loved')][-10:]
        skipped_songs = [f"{m['title']} - {m['artist']}" for m in meta if m.get('skip_count', 0) > 0][-10:]
        existing_songs = [f"{m['title']} - {m['artist']}" for m in meta]

        genre_constraint = _get_genre_prompt(profile, genre)

        prompt = f"""你是一个世界顶级的音乐品味鉴赏师。

## 任务
为用户的 {genre} 风格库推荐 10 首歌曲。

## 风格约束
{genre_constraint}

## 用户偏好
{prefs.get('description', '')}

## 用户喜欢的歌（推荐类似的）
{', '.join(loved_songs) if loved_songs else '暂无'}

## 用户跳过的歌（严格规避类似风格）
{', '.join(skipped_songs) if skipped_songs else '暂无'}

## 已在库中的歌（绝对不要重复推荐）
{', '.join(existing_songs[-30:]) if existing_songs else '暂无'}

## 强制规则
1. 推荐的歌必须真实存在于 Apple Music
2. 不要重复已有列表中的歌
3. 随机种子: {random.randint(1, 100000)}

输出 JSON 数组: [{{"song": "歌名", "artist": "歌手"}}]"""

        results = _ask_deepseek_batch(prompt)
        if not results:
            log.warning(f"🔄 Refill: AI returned nothing for {genre}")
            return

        plist = _playlist_name(profile, genre)
        _ensure_playlist_exists(plist)
        added = 0

        for item in results:
            if not item or 'song' not in item:
                continue

            verified = _verify_on_apple_music(item['song'], item['artist'])
            if not verified:
                log.info(f"🔄 Refill: ✗ {item['song']} not on Apple Music")
                continue

            song_name = verified['song']
            artist_name = verified['artist']

            # 加入 Music.app 资料库
            ok = _add_song_to_library_only(song_name, artist_name, verified_info=verified)
            if not ok:
                log.warning(f"🔄 Refill: ✗ Failed to add '{song_name}'")
                continue

            # 加入播放列表
            _add_to_playlist(plist, song_name, artist_name)

            # 更新元数据
            _add_to_library_meta(profile, genre, song_name, artist_name, source='ai_refill')
            added += 1
            log.info(f"🔄 Refill: ✓ [{added}] {song_name} - {artist_name}")

        # 淘汰超出上限的旧歌
        _evict_old_songs(profile, genre)

        log.info(f"🔄 Refill: Done for {profile}/{genre}, added {added} songs")
    except Exception as e:
        log.warning(f"🔄 Refill error: {e}")
    finally:
        _refill_active[key] = False


def _evict_old_songs(profile, genre, max_size=50):
    """淘汰超出上限的旧歌"""
    meta = _get_library_meta(profile, genre)
    if len(meta) <= max_size:
        return

    # 分离 loved 和非 loved
    loved = [m for m in meta if m.get('loved')]
    unloved = [m for m in meta if not m.get('loved')]

    # 排序淘汰优先级：skip多 → 最久未播 → 最早入库
    unloved.sort(key=lambda m: (
        -m.get('skip_count', 0),
        m.get('last_played') or '1970-01-01',
        m.get('added_date', '1970-01-01'),
    ))

    keep_count = max_size - len(loved)
    if keep_count < 0:
        keep_count = 0

    kept = unloved[:keep_count]
    evicted = unloved[keep_count:]

    library_meta[profile][genre] = loved + kept
    _save_library_meta(profile, genre)

    if evicted:
        log.info(f"Evict: Removed {len(evicted)} songs from {profile}/{genre}")


# ===== 智能选起始风格 =====
def _get_time_period():
    h = datetime.now().hour
    if 6 <= h < 12: return 'morning'
    elif 12 <= h < 18: return 'afternoon'
    elif 18 <= h < 24: return 'evening'
    else: return 'night'


def _smart_pick_starting_genre(profile):
    """本地智能选起始风格（0 延迟）"""
    period = _get_time_period()
    profile_data = PROFILES.get(profile, {})
    profile_genres = _get_profile_genres(profile)
    time_weights = profile_data.get('time_weights', {})
    weights = dict(time_weights.get(period, {g: 1 for g in profile_genres}))
    meta_all = library_meta.get(profile, {})

    # 调整因子
    for genre in profile_genres:
        gm = meta_all.get(genre, [])
        if not gm:
            weights[genre] = weights.get(genre, 1) * 0.1  # 空库降权
            continue

        # 避免连续：上次播的风格降权
        if genre == vibe_state.get('current_genre'):
            weights[genre] = weights.get(genre, 1) * 0.3

        # love 加权
        love_count = sum(1 for m in gm if m.get('loved'))
        weights[genre] = weights.get(genre, 1) + love_count * 0.2

        # skip 惩罚
        total = len(gm)
        skip_heavy = sum(1 for m in gm if m.get('skip_count', 0) > 2)
        if total > 0 and skip_heavy / total > 0.5:
            weights[genre] = weights.get(genre, 1) * 0.5

    # 加权随机
    genres = list(weights.keys())
    w = [max(0.01, weights.get(g, 0.01)) for g in genres]
    total_w = sum(w)
    r = random.random() * total_w
    cumulative = 0
    for g, gw in zip(genres, w):
        cumulative += gw
        if r <= cumulative:
            return g
    return random.choice(profile_genres)


# ===== 渐变混播 =====
def _pick_neighbor_genre(current_genre, profile):
    """从相邻风格中选一个（love 多的优先，不回头）"""
    neighbors = _get_genre_neighbors(profile, current_genre)
    if not neighbors:
        return current_genre

    # 排除上一个风格（不回头）
    prev = vibe_state.get('previous_genre')
    candidates = [g for g in neighbors if g != prev]
    if not candidates:
        candidates = neighbors

    # 有库的优先
    candidates_with_songs = [g for g in candidates
                             if _get_library_meta(profile, g)]
    if candidates_with_songs:
        candidates = candidates_with_songs

    # love 多的权重高
    weights = []
    for g in candidates:
        gm = _get_library_meta(profile, g)
        love_count = sum(1 for m in gm if m.get('loved'))
        weights.append(1 + love_count * 0.3)

    total = sum(weights)
    r = random.random() * total
    cumulative = 0
    for g, w in zip(candidates, weights):
        cumulative += w
        if r <= cumulative:
            return g
    return candidates[0]


# ===== 核心播放函数 =====
def _play_song(profile, genre, song_meta, trigger='genre_button'):
    """播放一首歌 + 更新状态 + 触发填充检查"""
    global vibe_state
    title = song_meta['title']
    artist = song_meta['artist']

    log.info(f"▶ Playing: {title} - {artist} [{genre}]")
    success = _smart_play(title, artist)

    if success:
        vibe_state['current_track'] = {'title': title, 'artist': artist}
        vibe_state['status'] = 'playing'
        vibe_state['current_genre'] = genre
        _write_touchstrip()

        # 更新元数据
        song_meta['last_played'] = datetime.now().strftime('%Y-%m-%d')
        song_meta['play_count'] = song_meta.get('play_count', 0) + 1
        _save_library_meta(profile, genre)

        # 记录最近播放
        _add_recent_played(profile, genre, title)

        # 记录播放历史
        _log_play_history(profile, title, artist, genre, 'played', 1.0,
                         trigger, vibe_state.get('play_mode', 'genre'))

        # 统一填充检查
        _check_and_refill(profile, genre)
    else:
        log.warning(f"▶ Failed to play: {title}")

    return success


def _play_next_song():
    """自动下一首：根据模式选歌"""
    global vibe_state
    profile = vibe_state.get('active_profile')
    genre = vibe_state.get('current_genre')
    mode = vibe_state.get('play_mode')

    if not profile or not genre:
        return

    if mode == 'journey':
        vibe_state['songs_in_current_genre'] = vibe_state.get('songs_in_current_genre', 0) + 1

        # 每 3 首后 50% 概率渐变
        if vibe_state['songs_in_current_genre'] >= 3 and random.random() > 0.5:
            new_genre = _pick_neighbor_genre(genre, profile)
            log.info(f"🎵 Journey: {genre} → {new_genre}")
            vibe_state['previous_genre'] = genre
            vibe_state['current_genre'] = new_genre
            vibe_state['songs_in_current_genre'] = 0
            genre = new_genre

    song = _pick_song_from_library(profile, genre)
    if song:
        _play_song(profile, genre, song, trigger='auto')
    else:
        log.warning(f"No songs available in {profile}/{genre}")


# ===== Watchdog =====
def _get_playback_progress():
    try:
        script = '''
        tell application "Music"
            if player state is playing then
                set pos to player position
                set dur to duration of current track
                return (pos as text) & "|" & (dur as text) & "|playing"
            else if player state is paused then
                return "0|0|paused"
            else
                return "0|0|stopped"
            end if
        end tell
        '''
        result = subprocess.run(['osascript', '-e', script],
                              capture_output=True, text=True, timeout=5)
        parts = result.stdout.strip().split('|')
        if len(parts) == 3:
            return {
                'position': float(parts[0]),
                'duration': float(parts[1]),
                'state': parts[2]
            }
    except Exception:
        pass
    return None


def _watchdog_loop():
    """续播守护线程：检测歌曲结束 → 自动下一首"""
    global vibe_state
    vibe_state['watchdog_active'] = True
    log.info("👁 Watchdog started")

    while vibe_state['status'] == 'playing':
        try:
            time.sleep(5)

            if vibe_state['status'] != 'playing':
                break

            progress = _get_playback_progress()
            if not progress:
                continue

            state = progress['state']
            position = progress['position']
            duration = progress['duration']
            remaining = duration - position if duration > 0 else 999

            if state == 'stopped':
                log.info("👁 Watchdog: Playback stopped, playing next")
                _play_next_song()
                time.sleep(3)
                continue

            if remaining < 10 and duration > 30:
                log.info(f"👁 Watchdog: {remaining:.0f}s remaining, queuing next")
                time.sleep(max(0, remaining - 2))
                _play_next_song()
                time.sleep(3)
                continue

        except Exception as e:
            log.warning(f"👁 Watchdog error: {e}")
            time.sleep(5)

    vibe_state['watchdog_active'] = False
    log.info("👁 Watchdog stopped")


def _start_watchdog():
    """启动 watchdog（如果尚未运行）"""
    if not vibe_state.get('watchdog_active', False):
        threading.Thread(target=_watchdog_loop, daemon=True).start()


# ===== GLM / LG TV 控制（从 V1 移植）=====
def glm_send(cc, value):
    try:
        import mido
        all_ports = mido.get_output_names()
        iac_port = next((p for p in all_ports if 'SD2GLM' not in p), None)
        if not iac_port:
            return
        with mido.open_output(iac_port) as port:
            port.send(mido.Message('control_change', channel=GLM_MIDI_CH,
                                   control=cc, value=value))
    except Exception as e:
        log.warning(f"GLM MIDI failed: {e}")


def set_glm_volume(val):
    global current_volume
    current_volume = max(0, min(127, val))
    glm_send(20, current_volume)


_lg_lock = threading.Lock()

def _wake_lg_tv():
    """Send WOL magic packet to LG TV"""
    try:
        mac_bytes = bytes.fromhex(LG_TV_MAC.replace(':', ''))
        magic = b'\xff' * 6 + mac_bytes * 16
        import socket as _sock
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.setsockopt(_sock.SOL_SOCKET, _sock.SO_BROADCAST, 1)
        for addr in ['255.255.255.255', LG_TV_IP]:
            s.sendto(magic, (addr, 9))
        s.close()
        log.info("WOL sent to LG TV")
    except Exception as e:
        log.warning(f"WOL failed: {e}")

def lg_switch_hdmi(input_id):
    with _lg_lock:
        _wake_lg_tv()
        time.sleep(3)
        for attempt in range(5):
            try:
                script = f'''
import asyncio, os
from bscpylgtv import WebOsClient
async def switch():
    client = await WebOsClient.create("{LG_TV_IP}", ping_interval=None, states=[], key_file_path=os.path.expanduser("~/.lgtv_keys.sqlite"))
    await client.connect()
    await client.set_input("{input_id}")
    await client.disconnect()
asyncio.run(switch())
'''
                result = subprocess.run(['/usr/bin/python3', '-c', script],
                              capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    log.info(f"LG TV → {input_id} (attempt {attempt+1})")
                    return
                log.warning(f"LG TV attempt {attempt+1} failed: {result.stderr.strip()[-80:]}")
            except Exception as e:
                log.warning(f"LG TV attempt {attempt+1} exception: {e}")
            time.sleep(3)
        log.error(f"LG TV → {input_id} FAILED after 5 attempts")


def _switch_to_hifi():
    """切换到 Mac + HiFi 模式：LG TV 切 HDMI Mac → GLM 编组1 → 音量 -20dB"""
    global current_glm_group
    threading.Thread(target=lg_switch_hdmi, args=(LG_HDMI_MAC,), daemon=True).start()
    glm_send(31, 127)  # 编组1 (HiFi)
    time.sleep(0.3)
    set_glm_volume(107)  # -20dB
    current_glm_group = 'HiFi'
    log.info("HiFi: LG→Mac, GLM Group1, Vol -20dB")


def _switch_to_movie():
    """切换到 ATV + Movie 模式：LG TV 切 HDMI ATV → GLM 编组2 → 音量 0dB"""
    global current_glm_group
    threading.Thread(target=lg_switch_hdmi, args=(LG_HDMI_APPLETV,), daemon=True).start()
    glm_send(29, 127)  # 编组2 (Movie)
    time.sleep(0.3)
    set_glm_volume(127)  # 0dB
    current_glm_group = 'Movie'
    log.info("Movie: LG→ATV, GLM Group2, Vol 0dB")


# ===== ATV 控制（Docker → pyatv）=====
DOCKER_CMD = ['/usr/local/bin/docker', 'exec', 'homeassistant', 'python3', '/config/launch_app.py']

APP_ROUTES = {
    '/netflix':  DOCKER_CMD + ['netflix_pin'],
    '/hbo':      DOCKER_CMD + ['hbo_pin'],
    '/youtube':  DOCKER_CMD + ['youtube'],
    '/disney':   DOCKER_CMD + ['disney'],
    '/prime':    DOCKER_CMD + ['prime'],
    '/appletv':  DOCKER_CMD + ['appletv'],
    '/plex':     DOCKER_CMD + ['plex'],
}

OTHER_ROUTES = {
    '/standby':  DOCKER_CMD + ['standby'],
    '/wakeup':   DOCKER_CMD + ['wakeup'],
}


# ===== 三轴描述（旋钮按下用）=====
def _describe_energy(val):
    if val <= 15:  return "极致安静冥想级别"
    if val <= 35:  return "安静内省"
    if val <= 55:  return "舒适中等节奏"
    if val <= 75:  return "明快有活力"
    return "暴烈高能"


def _describe_mood(val):
    if val <= 15:  return "深度忧郁"
    if val <= 35:  return "淡淡忧伤"
    if val <= 55:  return "中性平和"
    if val <= 75:  return "温暖愉悦"
    return "极致欢快"


def _describe_discovery(val):
    if val <= 20:  return "广为人知的经典名曲"
    if val <= 45:  return "有品质的主流歌曲"
    if val <= 70:  return "独立厂牌小众佳作"
    return "极度小众实验先锋"


def _knob_generate(profile, genre):
    """旋钮按下：根据三轴坐标深度生成，替换当前风格库部分内容"""
    global vibe_state
    e = vibe_state['energy']
    m = vibe_state['mood']
    d = vibe_state['discovery']
    log.info(f"🎛 Knob generate: {profile}/{genre} E={e} M={m} D={d}")

    prefs = PROFILES.get(profile, {}).get('preferences', {})
    genre_constraint = _get_genre_prompt(profile, genre)

    prompt = f"""你是一个世界顶级的音乐品味鉴赏师。

## 用户情绪坐标（物理旋钮）
- 能量 Energy: {e}% → {_describe_energy(e)}
- 情绪 Mood: {m}% → {_describe_mood(m)}
- 探索度 Discovery: {d}% → {_describe_discovery(d)}
- 时段: {_get_time_period()}

## 风格约束
{genre_constraint}

## 用户偏好
{prefs.get('description', '')}

## 强制规则
1. 严格遵守三个维度的描述来选歌
2. 推荐的歌必须真实存在于 Apple Music
3. 随机种子: {random.randint(1, 100000)}

请推荐 10 首歌，输出 JSON 数组: [{{"song": "歌名", "artist": "歌手"}}]"""

    results = _ask_deepseek_batch(prompt)
    if not results:
        log.warning("🎛 Knob generate: DeepSeek returned no results")
        vibe_state['status'] = 'idle'
        _write_touchstrip()
        return

    plist = _playlist_name(profile, genre)
    _ensure_playlist_exists(plist)

    first_played = False
    for item in results:
        if not item or 'song' not in item:
            continue
        verified = _verify_on_apple_music(item['song'], item['artist'])
        if not verified:
            continue

        song_name = verified['song']
        artist_name = verified['artist']

        ok = _add_song_to_library_only(song_name, artist_name, verified_info=verified)
        if ok:
            _add_to_playlist(plist, song_name, artist_name)
            _add_to_library_meta(profile, genre, song_name, artist_name, source='knob')
            # Play first song immediately, continue adding rest in background
            if not first_played:
                first_played = True
                _play_song(profile, genre, {'title': song_name, 'artist': artist_name}, trigger='knob')
                _start_watchdog()
            log.info(f"🎛 Knob: ✓ {song_name} - {artist_name}")

    _evict_old_songs(profile, genre)

    if not first_played:
        log.warning("🎛 Knob generate: no playable songs found")
        vibe_state['status'] = 'idle'
        _write_touchstrip()


# ===== 入口函数 =====
def _start_genre_play(profile, genre):
    """点击风格按钮 → 秒播（不切 HiFi，保持当前 group 不割裂）"""
    global vibe_state

    vibe_state['active_profile'] = profile
    vibe_state['current_genre'] = genre
    vibe_state['play_mode'] = 'genre'
    vibe_state['songs_in_current_genre'] = 0
    vibe_state['previous_genre'] = None

    song = _pick_song_from_library(profile, genre)
    if song:
        _play_song(profile, genre, song, trigger='genre_button')
        _start_watchdog()
    else:
        log.warning(f"No songs in {profile}/{genre}, triggering cold fill")
        vibe_state['status'] = 'idle'
        _write_touchstrip()
        # 空库 → 触发补货
        _check_and_refill(profile, genre)


def _start_avatar_play(profile):
    """点击头像 → 渐变混播"""
    global vibe_state

    _switch_to_hifi()

    vibe_state['active_profile'] = profile
    vibe_state['play_mode'] = 'journey'
    vibe_state['songs_in_current_genre'] = 0
    vibe_state['previous_genre'] = None

    # 加载所有库元数据
    for genre in _get_profile_genres(profile):
        _load_library_meta(profile, genre)

    # 智能选起始风格
    genre = _smart_pick_starting_genre(profile)
    vibe_state['current_genre'] = genre
    log.info(f"🎭 Avatar: {profile} → starting genre: {genre}")

    song = _pick_song_from_library(profile, genre)
    if song:
        _play_song(profile, genre, song, trigger='avatar')
        _start_watchdog()
    else:
        log.warning(f"No songs in {profile}/{genre}")
        vibe_state['status'] = 'idle'
        _write_touchstrip()
        _check_and_refill(profile, genre)


def _do_exit():
    """退出 → 立即停播"""
    global vibe_state
    try:
        subprocess.run(['osascript', '-e', 'tell application "Music" to pause'],
                      capture_output=True, text=True, timeout=5)
    except Exception:
        pass

    vibe_state['status'] = 'idle'
    vibe_state['current_track'] = None
    vibe_state['play_mode'] = None
    vibe_state['active_profile'] = None
    vibe_state['current_genre'] = None
    _write_touchstrip()
    log.info("⏹ Exit: Paused and idle")


def _do_skip(profile, genre, mode):
    """跳过当前歌 + 记录 + 播下一首"""
    global vibe_state
    track = vibe_state.get('current_track')

    if track:
        # 更新 skip 计数
        meta = _get_library_meta(profile, genre)
        for m in meta:
            if m['title'] == track['title'] and m['artist'] == track['artist']:
                m['skip_count'] = m.get('skip_count', 0) + 1
                break
        _save_library_meta(profile, genre)

        # 记录历史
        _log_play_history(profile, track['title'], track['artist'], genre,
                         'skipped', 0.1, 'skip', mode or 'genre')

    # 播下一首
    _play_next_song()


def _do_love(profile, genre, mode):
    """标记喜欢"""
    global vibe_state
    track = vibe_state.get('current_track')
    if not track:
        return

    # 更新元数据
    meta = _get_library_meta(profile, genre)
    for m in meta:
        if m['title'] == track['title'] and m['artist'] == track['artist']:
            m['loved'] = True
            break
    _save_library_meta(profile, genre)

    # 告诉 Music.app
    try:
        subprocess.run(['osascript', '-e',
            'tell application "Music" to set loved of current track to true'],
            capture_output=True, text=True, timeout=5)
    except Exception:
        pass

    # 记录历史
    _log_play_history(profile, track['title'], track['artist'], genre,
                     'loved', 1.0, 'love', mode or 'genre')
    log.info(f"❤️ Loved: {track['title']} - {track['artist']}")


# ===== 冷启动 =====
def _cold_start(profile):
    """冷启动：为每个风格生成 20 首种子歌"""
    log.info(f"❄️ Cold start: Building libraries for {profile}")
    prefs = PROFILES.get(profile, {}).get('preferences', {})

    for genre in _get_profile_genres(profile):
        plist = _playlist_name(profile, genre)
        _ensure_playlist_exists(plist)

        genre_constraint = _get_genre_prompt(profile, genre)
        prompt = f"""你是一个世界顶级的音乐品味鉴赏师。

## 任务
为用户的 {genre} 风格库推荐 20 首种子歌曲（冷启动建库）。

## 风格约束
{genre_constraint}

## 用户偏好
{prefs.get('description', '')}

## 强制规则
1. 推荐的歌必须真实存在于 Apple Music
2. 风格多样化，覆盖该类型的不同子风格
3. 随机种子: {random.randint(1, 100000)}

输出 JSON 数组: [{{"song": "歌名", "artist": "歌手"}}]"""

        results = _ask_deepseek_batch(prompt)
        if not results:
            log.warning(f"❄️ Cold start: AI returned nothing for {genre}")
            continue

        added = 0
        for item in results:
            if not item or 'song' not in item:
                continue
            verified = _verify_on_apple_music(item['song'], item['artist'])
            if not verified:
                continue

            song_name = verified['song']
            artist_name = verified['artist']

            ok = _add_song_to_library_only(song_name, artist_name, verified_info=verified)
            if ok:
                _add_to_playlist(plist, song_name, artist_name)
                _add_to_library_meta(profile, genre, song_name, artist_name, source='cold_start')
                added += 1
                log.info(f"❄️ Cold start [{genre}]: ✓ [{added}] {song_name}")

        log.info(f"❄️ Cold start: {genre} done, {added} songs added")

    log.info(f"❄️ Cold start: Completed for {profile}")


# ===== HTTP Handler =====
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        global vibe_state, current_volume, current_glm_group, mute_saved_volume

        # ====== GLM 接口 ======
        if path.startswith('/glm/'):
            if path == '/glm/group1':
                glm_send(31, 127)
                time.sleep(0.3)
                set_glm_volume(107)  # 切HiFi必须跟-20dB，防止爆音
                current_glm_group = 'HiFi'
            elif path == '/glm/group2':
                glm_send(29, 127)
                time.sleep(0.3)
                set_glm_volume(127)  # 切Movie必须跟0dB
                current_glm_group = 'Movie'
            elif path == '/glm/vol_up':
                set_glm_volume(current_volume + 1)
            elif path == '/glm/vol_dn':
                set_glm_volume(current_volume - 1)
            elif path == '/glm/vol_0db':
                set_glm_volume(127)
            elif path == '/glm/mute':
                if mute_saved_volume is None:
                    mute_saved_volume = current_volume
                    set_glm_volume(0)
                    log.info(f"GLM muted (saved {mute_saved_volume - 127} dB)")
                else:
                    set_glm_volume(mute_saved_volume)
                    log.info(f"GLM unmuted → {mute_saved_volume - 127} dB")
                    mute_saved_volume = None
            elif path == '/glm/status_text':
                body = f"{current_volume - 127} dB".encode('utf-8')
                self._text(body)
                return
            elif path == '/glm/status':
                db_value = current_volume - 127
                self._json({'volume': f"{db_value} dB", 'midi': current_volume, 'group': current_glm_group, 'muted': mute_saved_volume is not None})
                return

            db_value = current_volume - 127
            _write_touchstrip()
            self._json({'volume': f"{db_value} dB", 'midi': current_volume, 'group': current_glm_group, 'muted': mute_saved_volume is not None})
            return

        # ====== 触摸条状态（始终2行） ======
        if path == '/home/screen/status':
            # 直接读文件返回（文件由 _write_touchstrip 维护）
            try:
                with open(TOUCHSTRIP_FILE, 'r', encoding='utf-8') as f:
                    text = f.read()
            except Exception:
                text = ''
            self._text(text.encode('utf-8'))
            return

        # ====== Vibe V2 路由 ======
        if path.startswith('/vibe/'):

            # --- 点击头像 ---
            if path.startswith('/vibe/profile/'):
                name = path.split('/')[-1]
                if name not in PROFILES:
                    self._json({'error': f'Unknown profile: {name}'})
                    return

                # 如果没有 active_profile，头像点击也设一下
                # 如果已经在别的 profile，切换
                vibe_state['active_profile'] = name
                vibe_state['status'] = 'generating'
                _write_touchstrip()
                def _do():
                    _start_avatar_play(name)
                threading.Thread(target=_do, daemon=True).start()
                self._json({'status': 'playing', 'profile': name, 'mode': 'journey'})
                return

            # --- 点击风格按钮 ---
            if path.startswith('/vibe/genre/'):
                genre_name = path.split('/')[-1]

                profile = vibe_state.get('active_profile')
                if not profile:
                    self._json({'error': 'No active profile. Click an avatar first.'})
                    return

                # 从当前角色的风格表查找（大小写不敏感）
                profile_genres = _get_profile_genres(profile)
                genre_map = {g.lower(): g for g in profile_genres}
                genre = genre_map.get(genre_name.lower(), genre_name)
                if genre not in profile_genres:
                    self._json({'error': f'Unknown genre: {genre_name}', 'available': profile_genres})
                    return

                def _do():
                    _start_genre_play(profile, genre)
                threading.Thread(target=_do, daemon=True).start()
                self._json({'status': 'playing', 'profile': profile, 'genre': genre, 'mode': 'genre'})
                return

            # --- 一键播放: /vibe/play/<profile>/<genre> ---
            if path.startswith('/vibe/play/'):
                parts = path.split('/')
                if len(parts) >= 5:
                    prof_name = parts[3]
                    genre_name = parts[4]
                else:
                    self._json({'error': 'Usage: /vibe/play/<profile>/<genre>'})
                    return

                if prof_name not in PROFILES:
                    self._json({'error': f'Unknown profile: {prof_name}'})
                    return

                vibe_state['active_profile'] = prof_name

                profile_genres = _get_profile_genres(prof_name)
                genre_map = {g.lower(): g for g in profile_genres}
                genre = genre_map.get(genre_name.lower(), genre_name)
                if genre not in profile_genres:
                    self._json({'error': f'Unknown genre: {genre_name}', 'available': profile_genres})
                    return

                def _do():
                    _start_genre_play(prof_name, genre)
                threading.Thread(target=_do, daemon=True).start()
                self._json({'status': 'playing', 'profile': prof_name, 'genre': genre, 'mode': 'genre'})
                return

            # --- Skip ---
            if path == '/vibe/skip':
                profile = vibe_state.get('active_profile')
                genre = vibe_state.get('current_genre')
                mode = vibe_state.get('play_mode')
                if profile and genre:
                    threading.Thread(target=_do_skip, args=(profile, genre, mode), daemon=True).start()
                self._json({'status': 'skipped'})
                return

            # --- Love ---
            if path == '/vibe/love':
                profile = vibe_state.get('active_profile')
                genre = vibe_state.get('current_genre')
                mode = vibe_state.get('play_mode')
                if profile and genre:
                    _do_love(profile, genre, mode)
                self._json({'status': 'loved', 'track': vibe_state.get('current_track')})
                return

            # --- Exit ---
            if path == '/vibe/exit':
                _do_exit()
                self._json({'status': 'idle'})
                return

            # --- 旋钮按下：深度生成 ---
            if path == '/vibe/generate':
                profile = vibe_state.get('active_profile')
                genre = vibe_state.get('current_genre')
                # 如果没有活跃 session，自动用默认 profile/genre 启动
                if not profile:
                    profile = 'alice'  # fallback to first profile
                    vibe_state['active_profile'] = profile
                    log.info(f"🎛 Generate: no active profile, defaulting to {profile}")
                if not genre:
                    genres = _get_profile_genres(profile)
                    genre = genres[0] if genres else None
                    if not genre:
                        self._json({'error': f'No genres for profile {profile}'})
                        return
                    vibe_state['current_genre'] = genre
                    vibe_state['play_mode'] = 'genre'
                    log.info(f"🎛 Generate: no active genre, defaulting to {genre}")
                vibe_state['status'] = 'generating'
                vibe_state['current_track'] = None
                _write_touchstrip()
                # 立即停止当前播放
                try:
                    subprocess.run(['osascript', '-e', 'tell application "Music" to pause'],
                                  capture_output=True, text=True, timeout=3)
                except Exception:
                    pass
                threading.Thread(target=_knob_generate, args=(profile, genre), daemon=True).start()
                self._json({'status': 'generating', 'energy': vibe_state['energy'],
                           'mood': vibe_state['mood'], 'discovery': vibe_state['discovery']})
                return

            # --- 旋钮旋转：调整三轴 ---
            if path == '/vibe/dial':
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                axis = q.get('axis', [''])[0]
                delta = int(q.get('delta', ['0'])[0])
                if axis == 'energy':
                    vibe_state['energy'] = max(0, min(100, vibe_state['energy'] + delta))
                elif axis == 'mood':
                    vibe_state['mood'] = max(0, min(100, vibe_state['mood'] + delta))
                elif axis == 'discovery':
                    vibe_state['discovery'] = max(0, min(100, vibe_state['discovery'] + delta))
                _write_touchstrip()
                self._json({
                    'energy': vibe_state['energy'],
                    'mood': vibe_state['mood'],
                    'discovery': vibe_state['discovery']
                })
                return

            # --- State ---
            if path == '/vibe/state':
                self._json(vibe_state)
                return

            # --- Screen: 三轴显示 ---
            if path == '/vibe/screen/energy':
                self._text(f"🔥 Energy {vibe_state['energy']}".encode())
                return
            if path == '/vibe/screen/mood':
                self._text(f"☀️ Mood {vibe_state['mood']}".encode())
                return
            if path == '/vibe/screen/discovery':
                self._text(f"🔮 Discover {vibe_state['discovery']}".encode())
                return

            self.send_response(404)
            self.end_headers()
            return

        # ====== 冷启动 ======
        if path.startswith('/vibe/init/'):
            # 放在 /vibe/ 外面因为是 POST，但也支持 GET 方便测试
            name = path.split('/')[-1]
            if name not in PROFILES:
                self._json({'error': f'Unknown profile: {name}'})
                return
            threading.Thread(target=_cold_start, args=(name,), daemon=True).start()
            self._json({'status': 'cold_start_initiated', 'profile': name})
            return

        # ====== Music 基础控制 ======
        if path == '/music/play_pause':
            subprocess.run(['osascript', '-e', 'tell application "Music" to playpause'],
                          capture_output=True, timeout=5)
            self._json({'status': 'toggled'})
            return
        if path == '/music/next':
            subprocess.run(['osascript', '-e', 'tell application "Music" to next track'],
                          capture_output=True, timeout=5)
            self._json({'status': 'next'})
            return
        if path == '/music/now_playing':
            script = '''
            tell application "Music"
                if player state is playing then
                    set t to current track
                    return (name of t) & " ||| " & (artist of t)
                else
                    return "STOPPED"
                end if
            end tell
            '''
            result = subprocess.run(['osascript', '-e', script],
                                  capture_output=True, text=True, timeout=5)
            info = result.stdout.strip()
            if info == "STOPPED" or not info:
                self._json({'playing': False})
            else:
                parts = info.split(' ||| ')
                self._json({'playing': True, 'song': parts[0],
                           'artist': parts[1] if len(parts) > 1 else ''})
            return
        if path == '/music/prev':
            subprocess.run(['osascript', '-e', 'tell application "Music" to previous track'],
                          capture_output=True, timeout=5)
            self._json({'status': 'prev'})
            return
        if path == '/music/add_to_loved':
            subprocess.run(['osascript', '-e',
                'tell application "Music" to set loved of current track to true'],
                capture_output=True, timeout=5)
            self._json({'status': 'loved'})
            return
        if path == '/music/play_song':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            query = q.get('q', [''])[0]
            if query:
                def _play():
                    subprocess.run(['shortcuts', 'run', 'PlaySong',
                                  '--input', query], timeout=30)
                threading.Thread(target=_play, daemon=True).start()
            self._json({'status': 'playing', 'query': query})
            return
        if path == '/music/artwork':
            artwork_path = '/tmp/now_playing_artwork.jpg'
            script = f'''
            tell application "Music"
                if player state is not stopped then
                    set t to current track
                    try
                        set artData to raw data of artwork 1 of t
                        set f to open for access POSIX file "{artwork_path}" with write permission
                        set eof f to 0
                        write artData to f
                        close access f
                        return "OK"
                    on error
                        return "NO_ART"
                    end try
                else
                    return "STOPPED"
                end if
            end tell
            '''
            result = subprocess.run(['osascript', '-e', script],
                                  capture_output=True, text=True, timeout=5)
            status = result.stdout.strip()
            if status == 'OK' and os.path.exists(artwork_path):
                with open(artwork_path, 'rb') as f:
                    img_data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(img_data)))
                self.end_headers()
                self.wfile.write(img_data)
            else:
                self.send_response(204)
                self.end_headers()
            return

        # ====== TV 切换 ======
        if path == '/tv/mac':
            threading.Thread(target=_switch_to_hifi, daemon=True).start()
            self._json({'status': 'switched', 'input': 'Mac', 'mode': 'HiFi'})
            return
        if path == '/tv/appletv':
            threading.Thread(target=_switch_to_movie, daemon=True).start()
            self._json({'status': 'switched', 'input': 'AppleTV', 'mode': 'Movie'})
            return

        # ====== ATV App 启动（切 Movie + Docker pyatv）======
        if path in APP_ROUTES:
            threading.Thread(target=_switch_to_movie, daemon=True).start()
            cmd = APP_ROUTES[path]
            threading.Thread(target=subprocess.run, args=(cmd,),
                           kwargs={'capture_output': True}, daemon=True).start()
            log.info(f"ATV App: {path}")
            self._json({'status': 'launching', 'app': path.strip('/')})
            return

        # ====== ATV 电源 ======
        if path in OTHER_ROUTES:
            cmd = OTHER_ROUTES[path]
            threading.Thread(target=subprocess.run, args=(cmd,),
                           kwargs={'capture_output': True}, daemon=True).start()
            self._json({'status': 'ok', 'action': path.strip('/')})
            return

        # ====== Mac Music 播放列表 ======
        if path == '/mac_music':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            playlist = q.get('list', ['喜爱歌曲'])[0]
            def _play_list():
                _switch_to_hifi()
                script = f'tell application "Music" to play playlist "{playlist}"'
                subprocess.run(['osascript', '-e', script], capture_output=True, timeout=10)
            threading.Thread(target=_play_list, daemon=True).start()
            self._json({'status': 'playing', 'playlist': playlist})
            return

        # ====== Smart Play 点歌 ======
        if path == '/smart_play':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            search_query = q.get('q', [''])[0]
            if search_query:
                def _do_smart():
                    _switch_to_hifi()
                    parts = search_query.split(' - ', 1)
                    song = parts[0].strip()
                    artist = parts[1].strip() if len(parts) == 2 else ''
                    _smart_play(song, artist)
                threading.Thread(target=_do_smart, daemon=True).start()
            self._json({'status': 'playing', 'query': search_query})
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        path = self.path.split('?')[0]

        # 冷启动
        if path.startswith('/vibe/init/'):
            name = path.split('/')[-1]
            if name not in PROFILES:
                self._json({'error': f'Unknown profile: {name}'})
                return
            threading.Thread(target=_cold_start, args=(name,), daemon=True).start()
            self._json({'status': 'cold_start_initiated', 'profile': name})
            return

        self.send_response(404)
        self.end_headers()

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info(fmt % args)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    # 启动时加载所有已有的库元数据
    total_genres = 0
    for profile in PROFILES:
        for genre in _get_profile_genres(profile):
            _load_library_meta(profile, genre)
            total_genres += 1
    log.info(f"Loaded library metadata: {len(PROFILES)} profiles, {total_genres} genre libraries")

    _write_touchstrip()  # 启动时写初始状态

    server = ThreadedHTTPServer(('127.0.0.1', 8555), Handler)
    log.info("Vibe Console V2 started: http://localhost:8555")
    log.info(f"Profiles: {list(PROFILES.keys())}")
    for p in PROFILES:
        log.info(f"  {p}: {_get_profile_genres(p)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped")

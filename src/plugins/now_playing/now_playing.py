from plugins.base_plugin.base_plugin import BasePlugin
import requests
import hashlib
import logging

logger = logging.getLogger(__name__)

FONT_SIZES = {
    "x-small": 0.7,
    "small": 0.9,
    "normal": 1,
    "large": 1.1,
    "x-large": 1.3
}

class NowPlaying(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "OpenAI",
            "expected_key": "OPEN_AI_SECRET"
        }
        template_params['style_settings'] = True
        return template_params

    def subsonic_request_params(self, username, password):
        salt = hashlib.md5().hexdigest()[:6]
        return {
            "u": username,
            "t": hashlib.md5((password + salt).encode('utf-8')).hexdigest(),
            "s": salt,
            "f": "json",
            "c": "Inky-Pi",
            "v": "1.16.1"
        }

    def parse_now_playing(self, subsonic_url, username, password):
        url = f"{subsonic_url}/rest/getNowPlaying"
        params = self.subsonic_request_params(username, password)

        logger.info(f"Fetching now playing data from URL: {url}")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json().get("subsonic-response")
        
        logger.info(f"Subsonic now playing response: {data}")
        assert data.get("status") == "ok", data.get("error", "Subsonic API returned an unknown error")
        
        entries = data.get("nowPlaying", {}).get("entry")
        now_playing_gen = (entry for entry in entries)
        
        now_playing = next(now_playing_gen, None)
        logging.info(f"Parsed now playing entry: {now_playing}")
        return now_playing
    
    def parse_cover_art_url(self, subsonic_url, username, password, cover_id, dimensions):
        url = f"{subsonic_url}/rest/getCoverArt"
        params = self.subsonic_request_params(username, password)
        params["id"] = cover_id
        params["size"] = dimensions[0]  # display width
        req = requests.Request('GET', url, params=params)
        cover_art_url = req.prepare().url

        logger.info(f"Constructed cover art URL: {cover_art_url}")

        return cover_art_url

    def generate_image(self, settings, device_config):
        subsonic_user = device_config.load_env_key("SUBSONIC_USER")
        if not subsonic_user:
            raise RuntimeError("Subsonic username is not configured")
        
        subsonic_pass = device_config.load_env_key("SUBSONIC_PASS")
        if not subsonic_pass:
            raise RuntimeError("Subsonic password is not configured")
        
        subsonic_url = settings.get("url")
        if not subsonic_url:
            raise RuntimeError("Subsonic URL is required.")
        
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        try:
            now_playing = self.parse_now_playing(subsonic_url, subsonic_user, subsonic_pass)
        except Exception as e:
            logger.error(f"Error fetching now playing data: {e}")
            now_playing = None

        try:
            if now_playing and "coverArt" in now_playing:
                cover_art_id = now_playing["coverArt"]
                cover_art = self.parse_cover_art_url(subsonic_url, subsonic_user, subsonic_pass, cover_art_id, dimensions)
        except Exception as e:
            logger.error(f"Error fetching cover art: {e}")
            cover_art = None

        template_params = {
            "title": now_playing.get("title") if now_playing else "No music playing",
            "artist": now_playing.get("artist") if now_playing else "",
            "album": now_playing.get("album") if now_playing else "",
            "cover_art_url": cover_art,
            "dimensions": dimensions,
            "display_id3_metadata": settings.get("display-id3-metadata"),
            "font_scale": FONT_SIZES.get(settings.get('fontSize', 'normal'), 1),
            "plugin_settings": settings
        }

        image = self.render_image(dimensions, "now_playing.html", "now_playing.css", template_params)
        return image
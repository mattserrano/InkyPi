from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image, ImageColor, ImageOps
from utils.http_client import get_http_session, requests
import hashlib
import logging
from utils.image_utils import pad_image_blur

logger = logging.getLogger(__name__)

FONT_SIZES = {
    "x-small": 0.7,
    "small": 0.9,
    "normal": 1,
    "large": 1.1,
    "x-large": 1.3
}

class SubsonicProvider:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = get_http_session()

    def request_params(self):
        salt = hashlib.md5().hexdigest()[:6]
        return {
            "u": self.username,
            "t": hashlib.md5((self.password + salt).encode('utf-8')).hexdigest(),
            "s": salt,
            "f": "json",
            "c": "Inky-Pi",
            "v": "1.16.1"
        }
    
    def get_now_playing(self):
        url = f"{self.base_url}/rest/getNowPlaying"
        params = self.request_params()

        logger.info(f"Fetching now playing data from URL: {url}")
        response = self.session.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json().get("subsonic-response")
        
        logger.info(f"Subsonic now playing response: {data}")
        assert data.get("status") == "ok", data.get("error", "Subsonic API returned an unknown error")
        
        entries = data.get("nowPlaying").get("entry", {})
        now_playing_gen = (entry for entry in entries)
        
        now_playing = next(now_playing_gen, None)
        logging.info(f"Parsed now playing entry: {now_playing}")
        return now_playing
    
    def get_cover_art_url(self, cover_id, dimensions):
        url = f"{self.base_url}/rest/getCoverArt"
        params = self.request_params()
        params["id"] = cover_id
        params["size"] = dimensions[0]  # display width
        req = requests.Request('GET', url, params=params)
        cover_art_url = req.prepare().url

        logger.info(f"Constructed cover art URL: {cover_art_url}")

        return cover_art_url
    
    def get_image(self,  dimensions, settings, renderer, resize=True):
        cover_art_url = None
        now_playing = self.get_now_playing()

        if now_playing and "coverArt" in now_playing:
            cover_id = now_playing["coverArt"]
            cover_art_url = self.get_cover_art_url(cover_id, dimensions)
           
        template_params = {
            "title": now_playing.get("title") if now_playing else "No music playing",
            "artist": now_playing.get("artist") if now_playing else "",
            "album": now_playing.get("album") if now_playing else "",
            "cover_art_url": cover_art_url,
            "dimensions": dimensions,
            "display_id3_metadata": settings.get("display-id3-metadata"),
            "font_scale": FONT_SIZES.get(settings.get('fontSize', 'normal'), 1),
            "plugin_settings": settings
        }

        image = renderer.render_image(dimensions, "now_playing.html", "now_playing.css", template_params)
        return image

class NowPlaying(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "Subsonic",
            "expected_key": "SUBSONIC_USER"
        }
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        logger.info("=== Now Playing Plugin: Starting image generation ===")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        music_provider = settings.get("musicProvider")
        logger.info(f"Music provider: {music_provider}")

        # Check padding options to determine resize strategy
        use_padding = settings.get('padImage') == "true"
        background_option = settings.get('backgroundOption', 'blur')
        logger.debug(f"Settings: pad_image={use_padding}, background_option={background_option}")

        match music_provider:
            case "Subsonic":
                subsonic_user = device_config.load_env_key("SUBSONIC_USER")
                if not subsonic_user:
                    raise RuntimeError("Subsonic username is not configured")
                
                subsonic_pass = device_config.load_env_key("SUBSONIC_PASS")
                if not subsonic_pass:
                    raise RuntimeError("Subsonic password is not configured")
                
                subsonic_url = settings.get("url")
                if not subsonic_url:
                    raise RuntimeError("Subsonic URL is required.")

                provider = SubsonicProvider(subsonic_url, subsonic_user, subsonic_pass)
                img = provider.get_image(dimensions, settings, self, resize=not use_padding)
                if not img:
                    logger.error("Failed to retrieve Subsonic now playing data")
                    raise RuntimeError("Failed to load image, please check logs.")
            case _:
                logger.error(f"Unknown music provider: {music_provider}")
                raise RuntimeError(f"Unsupported music provider: {music_provider}")
            
        # Apply padding if requested (image was loaded at full size)
        if use_padding:
            logger.debug(f"Applying padding with {background_option} background")
            if background_option == "blur":
                img = pad_image_blur(img, dimensions)
            else:
                background_color = ImageColor.getcolor(
                    settings.get('backgroundColor') or "white",
                    img.mode
                )
                img = ImageOps.pad(img, dimensions, color=background_color, method=Image.Resampling.LANCZOS)
        # else: loader already resized to fit with proper aspect ratio

        return img
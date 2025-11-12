from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image, ImageOps, ImageFilter
from io import BytesIO
import random
import requests
import logging

logger = logging.getLogger(__name__)

def grab_album_id(server_url, album_name, headers):
    """Fetch the album ID from Immich server using the album name."""
    try:
        response = requests.get(f"{server_url}/api/albums", headers=headers)
        response.raise_for_status()
        albums = response.json()
        for album in albums:
            if album['albumName'] == album_name:
                return album['id']
        raise RuntimeError(f"Album '{album_name}' not found on Immich server.")
    except requests.exceptions.HTTPError as e:
        print("HTTP error occurred:", e)
    except requests.exceptions.RequestException as e:
        print("A request error occurred:", e)

def grab_image(server_url, album_id, dimensions, pad_image, headers, timeout_ms=40000):
    """Grab an image from a URL and resize it to the specified dimensions."""
    try:
        response = requests.get(f"{server_url}/api/albums/{album_id}", headers=headers)
        response.raise_for_status()
        assets = response.json()['assets']
        if not assets or len(assets) == 0:
            raise RuntimeError("No images found in the specified album.")
        random_asset = random.choice(assets)
        asset_id = random_asset['id']
        image_url = f"{server_url}/api/assets/{asset_id}/original"
        logger.info(f"Grabbing Immich asset from downloadAsset endpoint: {image_url}")
        response = requests.get(image_url, headers=headers, timeout=timeout_ms / 1000)
        img = Image.open(BytesIO(response.content))
        img = ImageOps.exif_transpose(img)  # Correct orientation using EXIF
        img = ImageOps.contain(img, dimensions, Image.LANCZOS)

        if pad_image:
            bkg = ImageOps.fit(img, dimensions)
            bkg = bkg.filter(ImageFilter.BoxBlur(8))
            img_size = img.size
            bkg.paste(img, ((dimensions[0] - img_size[0]) // 2, (dimensions[1] - img_size[1]) // 2))
            img = bkg
        return img
    except Exception as e:
        logger.error(f"Error grabbing image asset from Immich: {e}")
        return None

class Immich(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['immichApiKey'] = {
            "required": True,
            "service": "Immich",
            "expected_key": "IMMICH_SECRET"
        }
        template_params['style_settings'] = False
        return template_params

    def generate_image(self, settings, device_config):
        # load required variables
        api_key = device_config.load_env_key("IMMICH_SECRET")
        if not api_key:
            raise RuntimeError("Immich API key not configured.")
        headers = {'x-api-key': api_key}
        sever_url = settings.get('immichServerUrl')
        if not sever_url:
            raise RuntimeError("Immich Server URL is required.")
        album_name = settings.get('albumName')
        if not album_name:
            raise RuntimeError("Album name is required.")
        dimensions = device_config.get_resolution()
        if not dimensions:
            raise RuntimeError("Device resolution is not configured.")
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        
        pad_image = settings.get('padImage', False)
        
        logger.info(f"Grabbing album from Immich URL: {sever_url} with name: {album_name}")
        album_id = grab_album_id(sever_url, album_name, headers)
        image = grab_image(sever_url, album_id, dimensions, pad_image, headers, timeout_ms=40000)
        if not image:
            raise RuntimeError("Failed to load image, please check logs.")
        
        # update plugin settings for next refresh
        settings['immichServerUrl'] = sever_url
        settings['albumName'] = album_name

        return image
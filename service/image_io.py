from io import BytesIO

import requests
from PIL import Image


def load_image_from_url(url: str) -> Image.Image:
    """
    从 URL 下载图片并转换为 RGB 的 PIL.Image。

    参数:
        url: 可访问的图片 HTTP/HTTPS 地址。

    返回:
        RGB 模式的 PIL.Image 对象。

    异常:
        下载失败、非图片内容或转换失败时抛出异常。
    """
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image

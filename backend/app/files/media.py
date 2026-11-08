from pathlib import PurePath

# Only inert image/video types are rendered inline. HTML and SVG remain downloads.
MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".ogv": "video/ogg",
}


def media_type(name):
    return MEDIA_TYPES.get(PurePath(name).suffix.lower())


def preview_kind(name):
    mime = media_type(name)
    return mime.split("/", 1)[0] if mime else None

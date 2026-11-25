"""Conversão de imagens."""
from PIL import Image, ImageOps

_heif_ready = False


def ensure_heif():
    global _heif_ready
    if not _heif_ready:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        _heif_ready = True


def convert(src, dst, fmt, quality):
    ensure_heif()
    img = Image.open(src)
    animated = getattr(img, "n_frames", 1) > 1 and fmt in ("GIF", "WEBP")
    if animated:
        frames = []
        for i in range(img.n_frames):
            img.seek(i)
            frames.append(img.convert("RGBA"))
        dur = img.info.get("duration", 100)
        if fmt == "GIF":
            frames[0].save(dst, save_all=True, append_images=frames[1:],
                           duration=dur, loop=0, disposal=2)
        else:
            frames[0].save(dst, "WEBP", save_all=True, append_images=frames[1:],
                           duration=dur, loop=0, quality=quality)
        return

    img = ImageOps.exif_transpose(img)
    icc = img.info.get("icc_profile")
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)

    def flatten(im):
        if has_alpha:
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            return bg
        return im.convert("RGB")

    def keep(im):
        return im.convert("RGBA" if has_alpha else "RGB")

    extra = {"icc_profile": icc} if icc else {}
    if fmt == "JPG":
        flatten(img).save(dst, "JPEG", quality=quality, optimize=True, **extra)
    elif fmt == "PNG":
        keep(img).save(dst, "PNG", **extra)
    elif fmt == "WEBP":
        keep(img).save(dst, "WEBP", quality=quality, method=4, **extra)
    elif fmt == "HEIC":
        keep(img).save(dst, "HEIF", quality=quality)
    elif fmt == "AVIF":
        keep(img).save(dst, "AVIF", quality=quality)
    elif fmt == "BMP":
        flatten(img).save(dst, "BMP")
    elif fmt == "TIFF":
        keep(img).save(dst, "TIFF", compression="tiff_lzw", **extra)
    elif fmt == "GIF":
        keep(img).save(dst, "GIF")
    elif fmt == "ICO":
        img = img.convert("RGBA")
        side = max(img.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        sizes = [s for s in (16, 24, 32, 48, 64, 128, 256) if s <= side] or [side]
        square.save(dst, "ICO", sizes=[(s, s) for s in sizes])
    elif fmt == "PDF":
        flatten(img).save(dst, "PDF", resolution=150)

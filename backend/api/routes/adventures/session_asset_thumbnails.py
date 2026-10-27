import logging
import os
import shutil

logger = logging.getLogger(__name__)


def copy_session_asset_thumbnail(source_path, target_path, ext):
    from .sessions import _is_svg_file

    # Ensure thumbnail exists in session visuals
    target_stem, target_ext = os.path.splitext(target_path)
    target_thumb_path = f"{target_stem}_thumb{target_ext}"
    source_stem, source_ext = os.path.splitext(source_path)
    source_thumb_path = f"{source_stem}_thumb{source_ext}"
    if os.path.isfile(source_thumb_path):
        try:
            shutil.copy2(source_thumb_path, target_thumb_path)
        except OSError:
            logger.warning(
                "Failed copying asset thumbnail to session folder: %s -> %s",
                source_thumb_path,
                target_thumb_path,
            )
    elif _is_svg_file(target_path, ext):
        try:
            shutil.copy2(target_path, target_thumb_path)
        except OSError:
            logger.warning(
                "Failed copying SVG asset thumbnail to session folder: %s -> %s",
                target_path,
                target_thumb_path,
            )
    else:
        try:
            from PIL import Image

            def _gen_thumb():
                with Image.open(target_path) as img:
                    img.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    output_image = img.convert("RGB") if img.mode in ("RGBA", "P") else img
                    output_image.save(target_thumb_path, optimize=True, quality=80)

            _gen_thumb()
        except Exception as e:
            logger.warning("Could not generate thumbnail for session asset %s: %s", target_path, e)

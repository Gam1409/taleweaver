import logging
import os
import shutil

logger = logging.getLogger(__name__)


def create_session_asset_thumbnail(target_path: str, ext: str) -> None:
    """Derive thumbnails from the validated copy, never an unchecked sibling file."""
    from .sessions import _is_svg_file

    # Ensure thumbnail exists in session visuals
    target_stem, target_ext = os.path.splitext(target_path)
    target_thumb_path = f"{target_stem}_thumb{target_ext}"
    if _is_svg_file(target_path, ext):
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

            def _gen_thumb() -> None:
                with Image.open(target_path) as img:
                    img.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    output_image = img.convert("RGB") if img.mode in ("RGBA", "P") else img
                    output_image.save(target_thumb_path, optimize=True, quality=80)

            _gen_thumb()
        except Exception as e:
            logger.warning("Could not generate thumbnail for session asset %s: %s", target_path, e)

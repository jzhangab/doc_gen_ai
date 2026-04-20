import logging
from . import config

logger = logging.getLogger(__name__)


def _open_folder(folder_id: str):
    import dataiku
    return dataiku.Folder(folder_id)


def load_all_files(folder_id: str) -> list:
    """Return [(filename, bytes)] for every file in a managed folder."""
    try:
        folder = _open_folder(folder_id)
        paths = folder.list_paths_in_partition()
    except Exception as exc:
        logger.warning("Cannot access folder '%s': %s", folder_id, exc)
        return []

    results = []
    for path in paths:
        filename = path.lstrip("/").split("/")[-1]
        if not filename:
            continue
        try:
            with folder.get_download_stream(path) as stream:
                results.append((filename, stream.read()))
        except Exception as exc:
            logger.warning("Cannot read '%s' from '%s': %s", path, folder_id, exc)
    return results


def load_folder_templates(doc_type: str, folder_id: str = None) -> list:
    """Return [(filename, bytes)] for all files under <doc_type>/ in the templates folder."""
    fid = folder_id or config.TEMPLATES_FOLDER
    try:
        folder = _open_folder(fid)
        paths = folder.list_paths_in_partition()
    except Exception as exc:
        logger.warning("Cannot access folder '%s': %s", fid, exc)
        return []

    results = []
    prefix = doc_type + "/"
    for path in paths:
        norm = path.lstrip("/")
        if norm.lower().startswith(prefix.lower()):
            filename = norm.split("/", 1)[-1]
            if not filename:
                continue
            try:
                with folder.get_download_stream(path) as stream:
                    results.append((filename, stream.read()))
            except Exception as exc:
                logger.warning("Cannot read '%s' from '%s': %s", path, fid, exc)
    return results


def save_file(folder_id: str, filename: str, content_bytes: bytes) -> None:
    """Write bytes to a file in a managed folder."""
    try:
        folder = _open_folder(folder_id)
        with folder.get_writer(filename) as writer:
            writer.write(content_bytes)
    except Exception as exc:
        logger.error("Cannot write '%s' to '%s': %s", filename, folder_id, exc)
        raise

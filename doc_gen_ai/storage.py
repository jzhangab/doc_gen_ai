import logging
from . import config

logger = logging.getLogger(__name__)


def load_folder_templates(doc_type: str, folder_id: str = None) -> list:
    """Return [(filename, bytes)] for all files under <doc_type>/ in the managed folder."""
    import dataiku
    fid = folder_id or config.MANAGED_FOLDER_ID
    try:
        folder = dataiku.Folder(fid)
        all_paths = folder.list_paths_in_partition()
    except Exception as exc:
        logger.warning("Could not access managed folder '%s': %s", fid, exc)
        return []

    results = []
    prefix = doc_type + "/"
    for path in all_paths:
        norm = path.lstrip("/")
        if norm.lower().startswith(prefix.lower()):
            filename = norm.split("/", 1)[-1]
            if not filename:
                continue
            try:
                with folder.get_download_stream(path) as stream:
                    results.append((filename, stream.read()))
            except Exception as exc:
                logger.warning("Could not read '%s' from folder '%s': %s", path, fid, exc)

    return results

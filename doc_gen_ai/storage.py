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


def list_folder_filenames(folder_id: str) -> list:
    """Return all filenames (leaf names only) present in a managed folder."""
    try:
        folder = _open_folder(folder_id)
        paths = folder.list_paths_in_partition()
    except Exception as exc:
        logger.warning("Cannot access folder '%s': %s", folder_id, exc)
        return []
    return [path.lstrip("/").split("/")[-1] for path in paths if path.lstrip("/").split("/")[-1]]


def load_files_by_name(folder_id: str, filenames: list) -> list:
    """Return [(filename, bytes)] for the given filenames from a managed folder."""
    try:
        folder = _open_folder(folder_id)
        all_paths = folder.list_paths_in_partition()
    except Exception as exc:
        logger.warning("Cannot access folder '%s': %s", folder_id, exc)
        return []

    name_set = {f.lower() for f in filenames}
    results = []
    for path in all_paths:
        leaf = path.lstrip("/").split("/")[-1]
        if leaf.lower() in name_set:
            try:
                with folder.get_download_stream(path) as stream:
                    results.append((leaf, stream.read()))
            except Exception as exc:
                logger.warning("Cannot read '%s' from '%s': %s", path, folder_id, exc)
    return results


def get_file_url(folder_name: str, filename: str) -> str:
    """Return a direct download URL for a file in a Dataiku managed folder."""
    try:
        import urllib.parse
        import dataiku
        client = dataiku.api_client()
        project_key = dataiku.default_project_key()
        project = client.get_project(project_key)
        folder_list = project.list_managed_folders()
        folder_obj = next((f for f in folder_list if f["name"] == folder_name), None)
        if not folder_obj:
            return ""
        host = client.host.rstrip("/")
        fid = folder_obj["id"]
        path = urllib.parse.quote(f"/{filename}")
        return f"{host}/dip/api/managedfolder/{fid}/download?projectKey={project_key}&path={path}"
    except Exception as exc:
        logger.warning("Could not build download URL: %s", exc)
        return ""


def save_file(folder_id: str, filename: str, content_bytes: bytes) -> None:
    """Write bytes to a file in a managed folder."""
    try:
        folder = _open_folder(folder_id)
        with folder.get_writer(filename) as writer:
            writer.write(content_bytes)
    except Exception as exc:
        logger.error("Cannot write '%s' to '%s': %s", filename, folder_id, exc)
        raise

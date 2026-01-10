import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np

try:
    import h5py

    HDF5_AVAILABLE = True
except ImportError:
    HDF5_AVAILABLE = False
    h5py = None


class LabDaemonJSONEncoder(json.JSONEncoder):
    """
    A JSON encoder that safely handles NumPy arrays.

    This encoder converts NumPy arrays to Python lists, allowing them to be
    serialized into JSON format.
    """

    def default(self, obj: Any) -> Any:
        """
        Override the default JSON encoder to handle NumPy arrays.

        Parameters
        ----------
        obj : Any
            The object to encode.

        Returns
        -------
        Any
            A serializable representation of the object.
        """
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def save_json(
    data: Dict[str, Any],
    filepath: Path,
    indent: int = 4,
    **kwargs: Any,
) -> None:
    """
    Save a dictionary to a JSON file, with support for NumPy arrays.

    Parameters
    ----------
    data : Dict[str, Any]
        The dictionary to save.
    filepath : Path
        The path to the output file.
    indent : int, default 4
        The indentation level for pretty-printing.
    **kwargs : Any
        Additional arguments to pass to json.dump().
    """
    with open(filepath, "w") as f:
        json.dump(data, f, cls=LabDaemonJSONEncoder, indent=indent, **kwargs)


def load_json(filepath: Path) -> Dict[str, Any]:
    """
    Load a dictionary from a JSON file.

    Parameters
    ----------
    filepath : Path
        The path to the JSON file.

    Returns
    -------
    Dict[str, Any]
        The loaded dictionary.
    """
    with open(filepath, "r") as f:
        return json.load(f)


def capture_metadata(**extra_metadata: Any) -> Dict[str, Any]:
    """
    Capture automatic metadata about the current environment.

    This function automatically captures:
    - Timestamp (ISO 8601 UTC format, no microseconds)
    - LabDaemon version
    - Git commit hash (if in a git repository)
    - Python version

    Parameters
    ----------
    **extra_metadata : Any
        Additional metadata to include.

    Returns
    -------
    Dict[str, Any]
        Dictionary containing metadata.
    """
    import sys

    metadata = {
        "timestamp": datetime.utcnow().isoformat(timespec='seconds') + 'Z',
        "python_version": sys.version,
    }

    # Try to get labdaemon version
    try:
        import labdaemon

        metadata["labdaemon_version"] = getattr(labdaemon, "__version__", "unknown")
    except Exception:
        metadata["labdaemon_version"] = "unknown"

    # Try to get git commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        if result.returncode == 0:
            metadata["git_commit"] = result.stdout.strip()
    except Exception:
        pass

    # Add user-provided metadata
    metadata.update(extra_metadata)

    return metadata


def save_hdf5(
    data: Dict[str, Any],
    filepath: Path,
    metadata: Optional[Dict[str, Any]] = None,
    overwrite: bool = False,
) -> None:
    """
    Save a dictionary to an HDF5 file with optional metadata.

    Supported data types:
    - NumPy arrays (stored as datasets)
    - Scalars (int, float, str, bool)
    - Lists (converted to arrays if homogeneous)
    - Nested dictionaries (up to 2 levels: dict of dict of arrays/scalars)

    Data is stored under the '/data' group.
    Metadata is stored as attributes on the '/metadata' group.

    Parameters
    ----------
    data : Dict[str, Any]
        The dictionary to save. Keys become dataset/group names.
    filepath : Path
        The path to the output HDF5 file.
    metadata : Optional[Dict[str, Any]], default None
        Metadata to store. Automatic metadata (timestamp, version) is always added.
    overwrite : bool, default False
        If True, overwrite existing file. If False, raise error if file exists.

    Raises
    ------
    ImportError
        If h5py is not installed.
    FileExistsError
        If file exists and overwrite=False.
    ValueError
        If data contains unsupported types or nesting beyond 2 levels.
    """
    if not HDF5_AVAILABLE:
        raise ImportError(
            "h5py is required for HDF5 support. Install with: pip install h5py"
        )

    filepath = Path(filepath)
    if filepath.exists() and not overwrite:
        raise FileExistsError(
            f"File {filepath} already exists. Use overwrite=True to replace it."
        )

    # Capture metadata
    full_metadata = capture_metadata(**(metadata or {}))

    with h5py.File(filepath, "w") as f:
        # Create data group
        data_group = f.create_group("data")
        _write_dict_to_group(data, data_group, current_depth=0, max_depth=2)

        # Store metadata as attributes
        metadata_group = f.create_group("metadata")
        for key, value in full_metadata.items():
            # Convert to string if not a simple type
            if isinstance(value, (str, int, float, bool)):
                metadata_group.attrs[key] = value
            else:
                metadata_group.attrs[key] = str(value)


def _write_dict_to_group(
    data: Dict[str, Any], group: "h5py.Group", current_depth: int, max_depth: int
) -> None:
    """
    Recursively write dictionary contents to an HDF5 group.

    Parameters
    ----------
    data : Dict[str, Any]
        Dictionary to write.
    group : h5py.Group
        HDF5 group to write to.
    current_depth : int
        Current nesting depth.
    max_depth : int
        Maximum allowed nesting depth.

    Raises
    ------
    ValueError
        If nesting exceeds max_depth or unsupported types encountered.
    """
    for key, value in data.items():
        # Sanitize key for HDF5
        safe_key = str(key).replace("/", "_")

        if isinstance(value, dict):
            if current_depth >= max_depth:
                raise ValueError(
                    f"Dictionary nesting exceeds maximum depth of {max_depth}. "
                    f"Found nested dict at key '{key}' at depth {current_depth + 1}."
                )
            # Create subgroup and recurse
            subgroup = group.create_group(safe_key)
            _write_dict_to_group(value, subgroup, current_depth + 1, max_depth)

        elif isinstance(value, np.ndarray):
            # Store NumPy array as dataset
            group.create_dataset(safe_key, data=value)

        elif isinstance(value, (list, tuple)):
            # Try to convert to NumPy array
            try:
                arr = np.array(value)
                group.create_dataset(safe_key, data=arr)
            except (ValueError, TypeError):
                raise ValueError(
                    f"Cannot convert list/tuple at key '{key}' to NumPy array. "
                    f"Lists must contain homogeneous numeric types."
                )

        elif isinstance(value, (int, float, bool, str, np.integer, np.floating)):
            # Store scalar as dataset
            group.create_dataset(safe_key, data=value)

        elif value is None:
            # Store None as empty dataset with attribute
            ds = group.create_dataset(safe_key, data=h5py.Empty("f"))
            ds.attrs["is_none"] = True

        else:
            raise ValueError(
                f"Unsupported type {type(value)} for key '{key}'. "
                f"Supported types: dict, np.ndarray, list, tuple, int, float, bool, str, None."
            )


def load_hdf5(
    filepath: Path, return_metadata: bool = False
) -> Union[Dict[str, Any], Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Load a dictionary from an HDF5 file.

    Parameters
    ----------
    filepath : Path
        The path to the HDF5 file.
    return_metadata : bool, default False
        If True, return (data, metadata) tuple. If False, return only data.

    Returns
    -------
    Dict[str, Any] or Tuple[Dict[str, Any], Dict[str, Any]]
        The loaded data dictionary, and optionally metadata dictionary.

    Raises
    ------
    ImportError
        If h5py is not installed.
    FileNotFoundError
        If file does not exist.
    """
    if not HDF5_AVAILABLE:
        raise ImportError(
            "h5py is required for HDF5 support. Install with: pip install h5py"
        )

    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"File {filepath} does not exist.")

    with h5py.File(filepath, "r") as f:
        # Load data
        if "data" in f:
            data = _read_group_to_dict(f["data"])
        else:
            # Fallback: read entire file as data
            data = _read_group_to_dict(f)

        # Load metadata
        metadata = {}
        if "metadata" in f:
            metadata_group = f["metadata"]
            for key in metadata_group.attrs.keys():
                metadata[key] = metadata_group.attrs[key]

    if return_metadata:
        return data, metadata
    return data


def _read_group_to_dict(group: "h5py.Group") -> Dict[str, Any]:
    """
    Recursively read an HDF5 group into a dictionary.

    Parameters
    ----------
    group : h5py.Group
        HDF5 group to read.

    Returns
    -------
    Dict[str, Any]
        Dictionary representation of the group.
    """
    result = {}
    for key in group.keys():
        item = group[key]

        if isinstance(item, h5py.Group):
            # Recursively read subgroup
            result[key] = _read_group_to_dict(item)

        elif isinstance(item, h5py.Dataset):
            # Read dataset
            value = item[()]

            # Check if this was stored as None
            if "is_none" in item.attrs and item.attrs["is_none"]:
                result[key] = None
            # Convert bytes to string
            elif isinstance(value, bytes):
                result[key] = value.decode("utf-8")
            # Convert 0-d arrays to scalars
            elif isinstance(value, np.ndarray) and value.ndim == 0:
                result[key] = value.item()
            else:
                result[key] = value

    return result


def save_data(
    data: Dict[str, Any],
    filepath: Path,
    format: str = "auto",
    overwrite: bool = False,
    **metadata: Any,
) -> None:
    """
    Save data to file with automatic format detection and metadata capture.

    Format is detected from file extension if format='auto':
    - '.json' → JSON
    - '.h5', '.hdf5' → HDF5

    Metadata is automatically captured (timestamp, version, git commit) and
    merged with user-provided metadata.

    Parameters
    ----------
    data : Dict[str, Any]
        The dictionary to save.
    filepath : Path
        The path to the output file.
    format : str, default 'auto'
        File format: 'auto', 'json', or 'hdf5'.
    overwrite : bool, default False
        If True, overwrite existing file. If False, raise error if file exists.
    **metadata : Any
        Additional metadata to store (HDF5 only).

    Raises
    ------
    ValueError
        If format cannot be determined or is unsupported.
    FileExistsError
        If file exists and overwrite=False.
    """
    filepath = Path(filepath)

    # Determine format
    if format == "auto":
        suffix = filepath.suffix.lower()
        if suffix == ".json":
            detected_format = "json"
        elif suffix in [".h5", ".hdf5"]:
            detected_format = "hdf5"
        else:
            raise ValueError(
                f"Cannot auto-detect format from extension '{suffix}'. "
                f"Use format='json' or format='hdf5' explicitly."
            )
    else:
        detected_format = format.lower()

    # Check overwrite for JSON (HDF5 handles it internally)
    if detected_format == "json" and filepath.exists() and not overwrite:
        raise FileExistsError(
            f"File {filepath} already exists. Use overwrite=True to replace it."
        )

    # Save with appropriate format
    if detected_format == "json":
        # For JSON, embed metadata in the data
        full_metadata = capture_metadata(**metadata)
        data_with_metadata = {"data": data, "metadata": full_metadata}
        save_json(data_with_metadata, filepath)

    elif detected_format == "hdf5":
        save_hdf5(data, filepath, metadata=metadata, overwrite=overwrite)

    else:
        raise ValueError(
            f"Unsupported format '{format}'. Use 'json' or 'hdf5'."
        )


def load_data(
    filepath: Path, format: str = "auto", return_metadata: bool = False
) -> Union[Dict[str, Any], Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Load data from file with automatic format detection.

    Format is detected from file extension if format='auto':
    - '.json' → JSON
    - '.h5', '.hdf5' → HDF5

    Parameters
    ----------
    filepath : Path
        The path to the file.
    format : str, default 'auto'
        File format: 'auto', 'json', or 'hdf5'.
    return_metadata : bool, default False
        If True, return (data, metadata) tuple. If False, return only data.

    Returns
    -------
    Dict[str, Any] or Tuple[Dict[str, Any], Dict[str, Any]]
        The loaded data dictionary, and optionally metadata dictionary.

    Raises
    ------
    ValueError
        If format cannot be determined or is unsupported.
    FileNotFoundError
        If file does not exist.
    """
    filepath = Path(filepath)

    # Determine format
    if format == "auto":
        suffix = filepath.suffix.lower()
        if suffix == ".json":
            detected_format = "json"
        elif suffix in [".h5", ".hdf5"]:
            detected_format = "hdf5"
        else:
            raise ValueError(
                f"Cannot auto-detect format from extension '{suffix}'. "
                f"Use format='json' or format='hdf5' explicitly."
            )
    else:
        detected_format = format.lower()

    # Load with appropriate format
    if detected_format == "json":
        full_data = load_json(filepath)
        # Extract data and metadata if structured
        if isinstance(full_data, dict) and "data" in full_data and "metadata" in full_data:
            data = full_data["data"]
            metadata = full_data["metadata"]
        else:
            # Fallback: treat entire file as data
            data = full_data
            metadata = {}

        if return_metadata:
            return data, metadata
        return data

    elif detected_format == "hdf5":
        return load_hdf5(filepath, return_metadata=return_metadata)

    else:
        raise ValueError(
            f"Unsupported format '{format}'. Use 'json' or 'hdf5'."
        )

import os


def copy_range(source_path, target_path, offset, size):
    """Copy and fsync a bounded range without loading an entire file in memory."""
    with source_path.open("rb") as source, target_path.open("wb") as destination:
        source.seek(offset)
        remaining = size
        while remaining:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                raise OSError("Source file is shorter than the requested range")
            destination.write(chunk)
            remaining -= len(chunk)
        destination.flush()
        os.fsync(destination.fileno())

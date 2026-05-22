import os
import shutil


def make_unique_path(path):
    root, ext = os.path.splitext(path)
    if not os.path.exists(path):
        return path

    index = 1
    while True:
        candidate = f"{root}({index}){ext}"
        if not os.path.exists(candidate):
            return candidate
        index += 1


def collect_relative_files(folder, extensions, recursive=False):
    normalized_extensions = tuple(ext.lower() for ext in extensions)
    files = []

    if recursive:
        for current_folder, _, filenames in os.walk(folder):
            for filename in filenames:
                if filename.lower().endswith(normalized_extensions):
                    full_path = os.path.join(current_folder, filename)
                    files.append(os.path.relpath(full_path, folder))
    else:
        for filename in os.listdir(folder):
            full_path = os.path.join(folder, filename)
            if os.path.isfile(full_path) and filename.lower().endswith(normalized_extensions):
                files.append(filename)

    return sorted(files, key=lambda value: value.lower())


def resolve_ghostscript_command():
    for command in ("gs", "gswin64c", "gswin32c"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return "gs"

import type { FolderItem } from "./types";

export function folderPath(folder: FolderItem, folders: FolderItem[]): string {
  const names = [folder.name];
  let parent = folder.parent_id;
  const seen = new Set([folder.id]);
  while (parent && !seen.has(parent)) {
    seen.add(parent);
    const ancestor = folders.find((item) => item.id === parent);
    if (!ancestor) break;
    names.unshift(ancestor.name);
    parent = ancestor.parent_id;
  }
  return "/ " + names.join(" / ");
}

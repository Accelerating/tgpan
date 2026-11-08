import { t } from "../i18n";
import { api } from "./api";

export interface UploadTree {
  files: { file: File; directory: string }[];
}

export function selectedTree(files: File[]): UploadTree {
  return {
    files: files.map((file) => ({
      file,
      directory: file.webkitRelativePath.split("/").slice(0, -1).join("/"),
    })),
  };
}

export async function droppedTree(transfer: DataTransfer): Promise<UploadTree> {
  // Capture entries synchronously; the drag data store closes after the drop handler.
  const entries = Array.from(transfer.items).map((item) =>
    item.webkitGetAsEntry?.(),
  );
  const fallback = Array.from(transfer.files);
  const tree: UploadTree = { files: [] };
  const visit = async (entry: FileSystemEntry, directory: string) => {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        (entry as FileSystemFileEntry).file(resolve, reject),
      );
      tree.files.push({ file, directory });
    } else if (entry.isDirectory) {
      const path = directory ? `${directory}/${entry.name}` : entry.name;
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      while (true) {
        const children = await new Promise<FileSystemEntry[]>(
          (resolve, reject) => reader.readEntries(resolve, reject),
        );
        if (!children.length) break;
        for (const child of children) await visit(child, path);
      }
    }
  };
  if (entries.some(Boolean)) {
    for (const entry of entries) if (entry) await visit(entry, "");
  } else return selectedTree(fallback);
  return tree;
}

export async function enqueueTree(
  tree: UploadTree,
  parent: string | null,
  enqueue: (files: File[], parent: string | null) => void,
) {
  if (!tree.files.length) throw new Error(t("空目录不能上传"));
  const paths = [
    ...new Set(tree.files.map((item) => item.directory).filter(Boolean)),
  ];
  if (paths.length > 5000) throw new Error(t("一次最多上传 5000 个目录"));
  const folders = paths.length
    ? await api<Record<string, string>>("/files/folders/resolve", "POST", {
        parent_id: parent,
        paths,
      })
    : {};
  const groups = new Map<string | null, File[]>();
  for (const { file, directory } of tree.files) {
    const destination = directory ? folders[directory] : parent;
    const group = groups.get(destination) || [];
    group.push(file);
    groups.set(destination, group);
  }
  for (const [destination, files] of groups) enqueue(files, destination);
}

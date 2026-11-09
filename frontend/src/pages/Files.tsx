import { t } from "../i18n";
import { useEffect, useRef, useState } from "react";
import { Button, Checkbox, Input } from "@heroui/react";
import {
  ArrowDown,
  ArrowDownToLine,
  ArrowUpDown,
  ChevronRight,
  CloudUpload,
  Folder,
  FolderInput,
  Eye,
  Share2,
  FolderPlus,
  LayoutList,
  Pencil,
  RotateCcw,
  Search,
  Trash2,
  Upload,
  UploadCloud,
  X,
} from "lucide-react";
import { api, date, errorText, formatSize } from "../lib/api";
import { isFileDrag, useItemDrag } from "../lib/dragAndDrop";
import { useData } from "../lib/hooks";
import {
  droppedTree,
  enqueueTree,
  selectedTree,
  type UploadTree,
} from "../lib/folderUpload";
import type { FolderItem, Listing, Node, Notify } from "../lib/types";
import { folderPath } from "../lib/folders";
import {
  Dialog,
  Empty,
  ErrorBanner,
  FileIcon,
  Loading,
  AlertDialog,
} from "../components/Shared";
import ShareDialog from "../components/ShareDialog";
import FilePreview from "../components/FilePreview";
import ActionMenu, { type MenuAction } from "../components/ActionMenu";
export default function Files({
  trash,
  version,
  refresh,
  notify,
  enqueue,
  parent = null,
  onNavigate,
  onOpenTransfers,
  transferCount = 0,
}: {
  trash: boolean;
  version: number;
  refresh: () => void;
  notify: Notify;
  enqueue: (files: File[], parent: string | null) => void;
  parent?: string | null;
  onNavigate?: (parent: string | null) => void;
  onOpenTransfers?: () => void;
  transferCount?: number;
}) {
  const [share, setShare] = useState<Node | null>(null);
  const [preview, setPreview] = useState<Node | null>(null);

  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("name");
  const [descending, setDescending] = useState(false);
  const [selection, setSelection] = useState<string[]>([]);
  const [dialog, setDialog] = useState<
    "folder" | "rename" | "move" | "trash" | "restore" | "purge" | null
  >(null);
  const [value, setValue] = useState("");
  const [destination, setDestination] = useState("");
  const [dragging, setDragging] = useState(false);
  const [moving, setMoving] = useState(false);
  const [moveError, setMoveError] = useState("");
  const [folders, setFolders] = useState<FolderItem[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const [preparing, setPreparing] = useState(false);
  const uploadTree = async (
    tree: Promise<UploadTree> | UploadTree,
    destination: string | null,
  ) => {
    setPreparing(true);
    try {
      const resolved = await tree;
      await enqueueTree(resolved, destination, enqueue);
      notify(t("已添加 {p0} 个上传任务", { p0: resolved.files.length }));
    } catch (error) {
      notify(errorText(error), true);
    } finally {
      setPreparing(false);
      refresh();
    }
  };
  const { data, error } = useData<Listing>(
    `/files?trash=${trash}${parent ? `&parent_id=${parent}` : ""}&q=${encodeURIComponent(search)}&sort=${sort}&descending=${descending}`,
    version,
    5000,
    true,
  );
  // Empty query parameters are omitted for the root directory.
  const items = data?.items || [];
  const itemDrag = useItemDrag(!trash && !moving, async (ids, target) => {
    setMoving(true);
    try {
      await api("/files/batch", "POST", {
        ids,
        action: "move",
        parent_id: target === "root" ? null : target,
      });
      setSelection([]);
      notify(t("已移动 {p0} 个项目", { p0: ids.length }));
    } catch (error) {
      setMoveError(errorText(error));
    } finally {
      setMoving(false);
      refresh();
    }
  });
  useEffect(() => {
    setSelection([]);
  }, [parent, trash, search]);
  useEffect(() => {
    setSearch("");
  }, [parent]);
  useEffect(() => {
    if (data)
      setSelection((old) =>
        old.filter((id) => data.items.some((n) => n.id === id)),
      );
  }, [data]);
  const navigate = (id: string | null) => {
    onNavigate?.(id);
    setSearch("");
  };
  const open = (action: typeof dialog, ids?: string[]) => {
    if (ids) setSelection(ids);
    setValue(
      action === "rename"
        ? items.find((n) => n.id === (ids || selection)[0])?.name || ""
        : "",
    );
    setDialog(action);
  };
  const openMove = async () => {
    try {
      setFolders(await api<FolderItem[]>("/files/folders"));
      setDestination("");
      setDialog("move");
    } catch (e) {
      notify(e instanceof Error ? e.message : t("加载目录失败"), true);
    }
  };
  const run = async () => {
    if (dialog === "folder")
      await api("/files/folders", "POST", { name: value, parent_id: parent });
    else if (dialog === "rename")
      await api(`/files/${selection[0]}`, "PATCH", { name: value });
    else
      await api("/files/batch", "POST", {
        ids: selection,
        action: dialog,
        parent_id: destination || null,
      });
    setSelection([]);
    refresh();
    notify(
      dialog === "purge"
        ? t("已永久删除，Telegram 原文件将在后台尝试清理")
        : t("操作完成"),
    );
  };
  const download = (node: Node) => {
    const anchor = document.createElement("a");
    anchor.href = `/api/files/${node.id}/download`;
    anchor.download = node.name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  };
  const actionsFor = (node: Node): MenuAction[] => {
    if (trash)
      return [
        {
          key: "restore",
          label: t("恢复"),
          icon: <RotateCcw size={16} />,
          onPress: () => open("restore", [node.id]),
        },
      ];
    const actions: MenuAction[] = [];
    if (node.status === "ready")
      actions.push({
        key: "share",
        label: t("分享"),
        icon: <Share2 size={16} />,
        onPress: () => setShare(node),
      });
    if (node.preview_kind)
      actions.push({
        key: "preview",
        label: t("预览"),
        icon: <Eye size={16} />,
        onPress: () => setPreview(node),
      });
    if (node.kind === "file")
      actions.push({
        key: "download",
        label: t("下载"),
        icon: <ArrowDownToLine size={16} />,
        disabled: node.status !== "ready",
        onPress: () => download(node),
      });
    actions.push({
      key: "rename",
      label: t("重命名"),
      icon: <Pencil size={15} />,
      onPress: () => open("rename", [node.id]),
    });
    return actions;
  };
  const pathName = (folder: FolderItem) => folderPath(folder, folders);
  const folderCount = items.filter((n) => n.kind === "folder").length;
  const total = items
    .filter((n) => n.kind === "file")
    .reduce((sum, n) => sum + n.size, 0);
  return (
    <div
      className={`files-page ${dragging ? "is-dragging" : ""}`}
      onDragOver={(e) => {
        if (!trash && isFileDrag(e.dataTransfer)) {
          e.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as globalThis.Node))
          setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!trash && !preparing && isFileDrag(e.dataTransfer))
          void uploadTree(droppedTree(e.dataTransfer), parent);
      }}
    >
      <div className="page-heading">
        <div>
          <h1>{trash ? t("回收站") : t("我的文件")}</h1>
        </div>
        <div className="heading-actions">
          {trash ? (
            <Button
              color="danger"
              variant="flat"
              startContent={<Trash2 size={17} />}
              isDisabled={!items.length}
              onPress={() =>
                open(
                  "purge",
                  items.map((n) => n.id),
                )
              }
            >
              {t("清空回收站")}
            </Button>
          ) : (
            <>
              <Button
                variant="bordered"
                startContent={<UploadCloud size={17} />}
                onPress={onOpenTransfers}
              >
                {t("传输任务")}
                {transferCount > 0 && (
                  <span className="transfer-count">{transferCount}</span>
                )}
              </Button>
              <Button
                variant="bordered"
                startContent={<FolderPlus size={17} />}
                onPress={() => open("folder")}
              >
                {t("新建目录")}
              </Button>
              <Button
                color="primary"
                startContent={<Upload size={17} />}
                onPress={() => input.current?.click()}
              >
                {t("上传文件")}
              </Button>
              <Button
                variant="bordered"
                startContent={<FolderPlus size={17} />}
                isLoading={preparing}
                onPress={() => folderInput.current?.click()}
              >
                {t("上传文件夹")}
              </Button>
            </>
          )}
        </div>
      </div>
      <ErrorBanner message={error} />
      <section className="file-panel" aria-busy={moving}>
        <div className="file-toolbar">
          <div className="breadcrumbs">
            <Button
              size="sm"
              variant="light"
              onPress={() => navigate(null)}
              {...itemDrag.targetProps("root", parent !== null)}
              className={itemDrag.target === "root" ? "drop-target" : ""}
            >
              {trash ? t("回收站") : t("全部文件")}
            </Button>
            {!trash &&
              data?.breadcrumbs.map((crumb) => (
                <span key={crumb.id}>
                  <ChevronRight size={14} />
                  <Button
                    size="sm"
                    variant="light"
                    onPress={() => navigate(crumb.id)}
                    {...itemDrag.targetProps(crumb.id, crumb.id !== parent)}
                    className={
                      itemDrag.target === crumb.id ? "drop-target" : ""
                    }
                  >
                    {crumb.name}
                  </Button>
                </span>
              ))}
          </div>
          <Input
            className="search-input"
            size="sm"
            variant="flat"
            aria-label={t("搜索当前目录")}
            placeholder={t("搜索当前目录")}
            startContent={<Search size={17} />}
            value={search}
            onValueChange={setSearch}
            endContent={
              search && (
                <button
                  type="button"
                  aria-label={t("清除搜索")}
                  onClick={() => setSearch("")}
                >
                  <X size={16} />
                </button>
              )
            }
          />
        </div>
        <div className="selection-bar">
          {selection.length ? (
            <>
              <Checkbox
                aria-label={t("取消所有选择")}
                isSelected
                onValueChange={() => setSelection([])}
              />
              <span>{t("已选择 {p0} 项", { p0: selection.length })}</span>
              {trash ? (
                <>
                  <Button
                    size="sm"
                    variant="light"
                    startContent={<RotateCcw size={15} />}
                    onPress={() => open("restore")}
                  >
                    {t("恢复")}
                  </Button>
                  <Button
                    size="sm"
                    color="danger"
                    variant="light"
                    startContent={<Trash2 size={15} />}
                    onPress={() => open("purge")}
                  >
                    {t("永久删除")}
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    variant="light"
                    startContent={<FolderInput size={15} />}
                    onPress={() => void openMove()}
                  >
                    {t("移动")}
                  </Button>
                  <Button
                    size="sm"
                    variant="light"
                    isDisabled={selection.length !== 1}
                    startContent={<Pencil size={15} />}
                    onPress={() => open("rename")}
                  >
                    {t("重命名")}
                  </Button>
                  <Button
                    size="sm"
                    color="danger"
                    variant="light"
                    startContent={<Trash2 size={15} />}
                    onPress={() => open("trash")}
                  >
                    {t("删除")}
                  </Button>
                </>
              )}
              <Button
                size="sm"
                isIconOnly
                variant="light"
                aria-label={t("取消选择")}
                onPress={() => setSelection([])}
              >
                <X size={15} />
              </Button>
            </>
          ) : (
            <>
              <span className="items-caption">
                {trash
                  ? t("项目数量：{p0}", { p0: items.length })
                  : t("项目数量：{p0} · 目录数量：{p1}", {
                      p0: items.length,
                      p1: folderCount,
                    })}
              </span>
              <div className="sort-control">
                <ArrowUpDown size={14} />
                <label>
                  <span className="sr-only">{t("排序方式")}</span>
                  <select
                    value={sort}
                    onChange={(e) => setSort(e.target.value)}
                  >
                    <option value="name">{t("名称排序")}</option>
                    <option value="updated_at">{t("修改时间")}</option>
                    <option value="size">{t("文件大小")}</option>
                  </select>
                </label>
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  aria-label={descending ? t("切换为升序") : t("切换为降序")}
                  onPress={() => setDescending(!descending)}
                >
                  <ArrowDown
                    size={14}
                    style={{ transform: descending ? "rotate(180deg)" : "" }}
                  />
                </Button>
                <LayoutList size={17} />
              </div>
            </>
          )}
        </div>
        {!data && !error ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty
            icon={
              trash ? (
                <Trash2 size={32} />
              ) : search ? (
                <Search size={32} />
              ) : (
                <Folder size={34} />
              )
            }
            title={
              search
                ? t("没有找到相关文件")
                : trash
                  ? t("回收站为空")
                  : t("暂无文件")
            }
          ></Empty>
        ) : (
          <div className="table-scroll">
            <table className="file-table">
              <thead>
                <tr>
                  <th className="checkbox-cell">
                    <Checkbox
                      aria-label={t("选择全部")}
                      isSelected={
                        selection.length === items.length && !!items.length
                      }
                      isIndeterminate={
                        selection.length > 0 && selection.length < items.length
                      }
                      onValueChange={(selected) =>
                        setSelection(selected ? items.map((n) => n.id) : [])
                      }
                    />
                  </th>
                  <th>{t("名称")}</th>
                  <th className="size-column">{t("大小")}</th>
                  <th className="date-column">
                    {trash ? t("删除时间") : t("修改时间")}
                  </th>
                  <th className="row-actions-heading">{t("操作")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((node) => (
                  <tr
                    key={node.id}
                    className={[
                      selection.includes(node.id) ? "selected-row" : "",
                      itemDrag.ids.includes(node.id) ? "drag-source" : "",
                      itemDrag.target === node.id ? "drop-target" : "",
                    ].join(" ")}
                    {...(node.kind === "folder"
                      ? itemDrag.targetProps(node.id)
                      : {})}
                  >
                    <td className="checkbox-cell">
                      <Checkbox
                        aria-label={t("选择 {p0}", { p0: node.name })}
                        isSelected={selection.includes(node.id)}
                        onValueChange={(checked) =>
                          setSelection((old) =>
                            checked
                              ? [...old, node.id]
                              : old.filter((id) => id !== node.id),
                          )
                        }
                      />
                    </td>
                    <td>
                      <button
                        className="file-name"
                        {...itemDrag.sourceProps(
                          selection.includes(node.id) ? selection : [node.id],
                        )}
                        onClick={() => {
                          if (!trash) {
                            if (node.kind === "folder") navigate(node.id);
                            else if (node.status === "ready") {
                              if (node.preview_kind) setPreview(node);
                              else download(node);
                            }
                          }
                        }}
                      >
                        <span className="file-icon-box">
                          <FileIcon node={node} />
                        </span>
                        <span className="file-name-details">
                          <span className="file-name-text" title={node.name}>
                            {node.name}
                          </span>
                          <small className="file-mobile-size">
                            {node.kind === "folder"
                              ? t("目录")
                              : formatSize(node.size)}
                          </small>
                          {node.status === "uploading" && (
                            <small>{t("上传中")}</small>
                          )}
                          {node.status === "cancelled" && (
                            <small>{t("未完成")}</small>
                          )}
                        </span>
                      </button>
                    </td>
                    <td className="size-column">
                      {node.kind === "folder" ? "—" : formatSize(node.size)}
                    </td>
                    <td className="date-column">
                      {date(trash ? node.deleted_at! : node.updated_at)}
                    </td>
                    <td className="row-actions">
                      <ActionMenu
                        label={node.name}
                        actions={actionsFor(node)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!trash && (
          <div className="file-panel-footer">
            <span>{t("合计 {p0}", { p0: formatSize(total) })}</span>
          </div>
        )}
      </section>
      <input
        ref={folderInput}
        type="file"
        multiple
        {...{ webkitdirectory: "" }}
        className="sr-only"
        aria-label={t("选择上传文件夹")}
        onChange={(e) => {
          void uploadTree(
            selectedTree(Array.from(e.target.files || [])),
            parent,
          );
          e.target.value = "";
        }}
      />
      <input
        ref={input}
        type="file"
        multiple
        className="sr-only"
        aria-label={t("选择上传文件")}
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          if (files.length) void uploadTree(selectedTree(files), parent);
          e.target.value = "";
        }}
      />
      {dragging && (
        <div className="drop-overlay">
          <CloudUpload size={56} />
          <h2>{t("松开以上传")}</h2>
          <p>{t("上传到当前目录")}</p>
        </div>
      )}
      {moveError && (
        <AlertDialog title={t("无法移动")} onClose={() => setMoveError("")}>
          <p>{moveError}</p>
        </AlertDialog>
      )}
      {share && (
        <ShareDialog
          node={share}
          onClose={() => setShare(null)}
          notify={notify}
        />
      )}
      {preview && (
        <FilePreview
          key={preview.id}
          node={preview}
          onClose={() => setPreview(null)}
          onDownload={() => download(preview)}
        />
      )}
      {dialog && (
        <Dialog
          title={
            {
              folder: t("新建目录"),
              rename: t("重命名"),
              move: t("移动到"),
              trash: t("移入回收站"),
              restore: t("恢复项目"),
              purge: t("永久删除"),
            }[dialog]
          }
          onClose={() => setDialog(null)}
          onConfirm={run}
          danger={dialog === "purge"}
          confirmLabel={dialog === "purge" ? t("永久删除") : t("确认")}
        >
          {(dialog === "folder" || dialog === "rename") && (
            <Input
              autoFocus
              label={t("名称")}
              value={value}
              onValueChange={setValue}
              maxLength={255}
              isRequired
            />
          )}
          {dialog === "move" && (
            <label className="form-label">
              {t("目标目录")}
              <select
                className="native-select"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
              >
                <option value="">{t("/ 全部文件")}</option>
                {folders
                  .filter((f) => !selection.includes(f.id))
                  .map((f) => (
                    <option key={f.id} value={f.id}>
                      {pathName(f)}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {dialog === "trash" && (
            <p>
              {t("将选中的 {p0} 个项目移入回收站？之后可以恢复。", {
                p0: selection.length,
              })}
            </p>
          )}
          {dialog === "restore" && (
            <p>
              {t(
                "恢复选中的 {p0} 个项目。原目录不可用时恢复到根目录；遇到重名时会保留在回收站，请先调整同名项目。",
                { p0: selection.length },
              )}
            </p>
          )}
          {dialog === "purge" && (
            <p>
              {t(
                "永久删除选中的 {p0} 个项目及目录内容，此操作无法撤销。Telegram 原文件将在后台尝试删除；超过 48 小时的消息可能需要在频道中手动清理。",
                { p0: selection.length },
              )}
            </p>
          )}
        </Dialog>
      )}
    </div>
  );
}

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { Button, Progress } from "@heroui/react";
import { Download, FolderOpen, Plus, RefreshCw } from "lucide-react";
import { t } from "../../i18n";
import { api, errorText, formatSize } from "../../lib/api";
import { useData } from "../../lib/hooks";
import type { Notify, OfflineSettings, OfflineTask } from "../../lib/types";
import { AlertDialog, Dialog, Empty, ErrorBanner, Loading } from "../Shared";

const labels: Record<string, string> = {
  queued: t("排队中"),
  resolving: t("解析下载信息"),
  selecting: t("等待选择文件"),
  downloading: t("下载到服务器"),
  storing: t("正在转存 Telegram"),
  paused: t("已暂停"),
  error: t("失败"),
  complete: t("已完成"),
  cancelled: t("已取消"),
};

export type TaskPageProps = {
  version: number;
  refresh: () => void;
  notify: Notify;
  onOpenFolder: (parent: string | null) => void;
};
type CreateProps = {
  onClose: () => void;
  onCreated: (tasks?: OfflineTask[] | string[]) => void;
  maxFileSize: number;
};
type SelectionProps = {
  task: OfflineTask;
  onClose: () => void;
  onSelected: () => void;
  maxFileSize: number;
};
export default function TaskPage({
  version,
  refresh,
  notify,
  onOpenFolder,
  base,
  title,
  emptyTitle,
  unavailableMessage,
  selectLabel,
  headerActions,
  renderActions,
  renderCreate,
  renderSelection,
}: TaskPageProps & {
  base: string;
  title: string;
  emptyTitle: string;
  unavailableMessage: string;
  selectLabel: string;
  headerActions?: ReactNode;
  renderActions?: (task: OfflineTask) => ReactNode;
  renderCreate: (props: CreateProps) => ReactNode;
  renderSelection: (props: SelectionProps) => ReactNode;
}) {
  const { data, error } = useData<OfflineTask[]>(base, version, 1500);
  const { data: settings } = useData<OfflineSettings>(
    `${base}/settings`,
    version,
    5000,
  );
  const [creating, setCreating] = useState(false);
  const [selecting, setSelecting] = useState<OfflineTask>();
  const [cancelling, setCancelling] = useState<OfflineTask>();
  const [failure, setFailure] = useState("");
  const awaitingSelection = useRef(new Set<string>());
  const seen = useRef(new Set<string>());
  useEffect(() => {
    if (selecting) return;
    const ready = data?.find(
      (task) =>
        task.state === "selecting" && awaitingSelection.current.has(task.id),
    );
    if (ready) {
      awaitingSelection.current.delete(ready.id);
      setSelecting(ready);
    }
  }, [data, selecting]);
  const busy = useRef(new Set<string>());
  useEffect(() => {
    const failures = (data || []).filter(
      (task) =>
        task.state === "error" &&
        task.error &&
        !seen.current.has(`${task.id}:${task.updated_at}`),
    );
    failures.forEach((task) =>
      seen.current.add(`${task.id}:${task.updated_at}`),
    );
    if (failures.length)
      setFailure(
        failures.map((task) => `${task.name}: ${task.error}`).join("\n"),
      );
  }, [data]);
  const action = async (task: OfflineTask, operation: string) => {
    if (busy.current.has(task.id)) return;
    busy.current.add(task.id);
    try {
      await api(`${base}/${task.id}/${operation}`, "POST");
      refresh();
    } catch (error) {
      notify(errorText(error), true);
    } finally {
      busy.current.delete(task.id);
    }
  };
  const percent = (current: number, total: number) =>
    total ? Math.min(100, (current / total) * 100) : 0;
  return (
    <div className="offline-page">
      <div className="page-heading">
        <h1>{title}</h1>
        <div className="heading-actions">
          {headerActions}
          <Button
            variant="bordered"
            isIconOnly
            aria-label={t("刷新")}
            onPress={refresh}
          >
            <RefreshCw size={16} />
          </Button>
          <Button
            color="primary"
            startContent={<Plus size={16} />}
            onPress={() => setCreating(true)}
          >
            {t("新建下载")}
          </Button>
        </div>
      </div>
      <ErrorBanner message={error} />
      {settings && !settings.available && (
        <ErrorBanner message={unavailableMessage} />
      )}
      {settings && (
        <div className="offline-summary muted">
          <span>
            {t("单文件上限 {p0}", { p0: formatSize(settings.max_file_size) })}
          </span>
          <span hidden={settings.free_bytes === undefined}>
            {t("磁盘可用 {p0}", { p0: formatSize(settings.free_bytes) })}
          </span>
        </div>
      )}
      <section className="settings-panel">
        {!data && !error ? (
          <Loading />
        ) : !data?.length ? (
          <Empty icon={<Download size={32} />} title={emptyTitle} />
        ) : (
          data.map((task) => (
            <div className="offline-task" key={task.id}>
              <div className="transfer-title">
                <strong>{task.name}</strong>
                <span className={`status-pill ${task.state}`}>
                  {task.phase === "processing" && task.state === "downloading"
                    ? t("合并处理中")
                    : labels[task.state] || task.state}
                </span>
              </div>
              <div className="two-progress">
                <div>
                  <span>
                    {t("下载到服务器")}
                    <b>{Math.floor(percent(task.downloaded, task.total))}%</b>
                  </span>
                  <Progress
                    size="sm"
                    aria-label={t("下载到服务器")}
                    value={percent(task.downloaded, task.total)}
                    isIndeterminate={
                      task.state === "resolving" ||
                      (task.state === "downloading" && !task.total)
                    }
                  />
                </div>
                <div>
                  <span>
                    {t("存入 Telegram")}
                    <b>{Math.floor(percent(task.stored, task.total))}%</b>
                  </span>
                  <Progress
                    size="sm"
                    color="success"
                    aria-label={t("存入 Telegram")}
                    value={percent(task.stored, task.total)}
                  />
                </div>
              </div>
              <div className="transfer-meta offline-meta">
                <span>
                  {formatSize(
                    task.state === "storing" || task.state === "complete"
                      ? task.stored
                      : task.downloaded,
                  )}{" "}
                  / {task.total ? formatSize(task.total) : t("大小未知")}
                </span>
                <span>
                  {formatSize(
                    Math.round(
                      task.state === "storing"
                        ? task.store_speed
                        : task.download_speed,
                    ),
                  )}
                  /s
                </span>
                {(() => {
                  const speed =
                    task.state === "storing"
                      ? task.store_speed
                      : task.download_speed;
                  const current =
                    task.state === "storing" ? task.stored : task.downloaded;
                  return speed > 0 && task.total > current ? (
                    <span>
                      {t("预计剩余 {p0} 分钟", {
                        p0: Math.max(
                          1,
                          Math.ceil((task.total - current) / speed / 60),
                        ),
                      })}
                    </span>
                  ) : null;
                })()}
              </div>
              {task.error && <p className="inline-error">{task.error}</p>}
              <div className="offline-actions">
                {renderActions?.(task)}
                {task.state === "selecting" && (
                  <Button
                    size="sm"
                    color="primary"
                    onPress={() => setSelecting(task)}
                  >
                    {selectLabel}
                  </Button>
                )}
                {["queued", "resolving", "downloading", "storing"].includes(
                  task.state,
                ) && (
                  <Button
                    size="sm"
                    variant="flat"
                    onPress={() => void action(task, "pause")}
                  >
                    {t("暂停")}
                  </Button>
                )}
                {task.state === "paused" && (
                  <Button
                    size="sm"
                    variant="flat"
                    onPress={() => void action(task, "resume")}
                  >
                    {t("继续")}
                  </Button>
                )}
                {task.state === "error" && (
                  <Button
                    size="sm"
                    variant="flat"
                    onPress={() => void action(task, "retry")}
                  >
                    {t("重试")}
                  </Button>
                )}
                {!["complete", "cancelled"].includes(task.state) && (
                  <Button
                    size="sm"
                    variant="light"
                    color="danger"
                    onPress={() => setCancelling(task)}
                  >
                    {t("取消任务")}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="light"
                  startContent={<FolderOpen size={14} />}
                  onPress={() => onOpenFolder(task.parent_id)}
                >
                  {t("打开目标目录")}
                </Button>
                {["complete", "cancelled"].includes(task.state) && (
                  <Button
                    size="sm"
                    variant="light"
                    onPress={() => {
                      void api(`${base}/${task.id}`, "DELETE")
                        .then(refresh)
                        .catch((error) => notify(errorText(error), true));
                    }}
                  >
                    {t("删除记录")}
                  </Button>
                )}
              </div>
              {!!task.files.length && (
                <details className="offline-details">
                  <summary>
                    {t("{p0} 个文件", {
                      p0: task.files.filter((file) => file.selected).length,
                    })}
                  </summary>
                  {task.files
                    .filter((file) => file.selected)
                    .map((file) => (
                      <div className="offline-file-choice" key={file.id}>
                        <span className="offline-file-path">{file.path}</span>
                        <small className="muted">
                          {formatSize(file.size)} ·{" "}
                          {file.complete ? t("已完成") : t("未完成")}
                        </small>
                      </div>
                    ))}
                </details>
              )}
            </div>
          ))
        )}
      </section>
      {creating &&
        renderCreate({
          maxFileSize: settings?.max_file_size || 5_000_000_000,
          onClose: () => setCreating(false),
          onCreated: (tasks) => {
            refresh();
            tasks?.forEach((task) =>
              awaitingSelection.current.add(
                typeof task === "string" ? task : task.id,
              ),
            );
          },
        })}
      {selecting &&
        renderSelection({
          task: selecting,
          maxFileSize: settings?.max_file_size || 5_000_000_000,
          onClose: () => setSelecting(undefined),
          onSelected: refresh,
        })}
      {cancelling && (
        <Dialog
          title={t("取消任务")}
          danger
          confirmLabel={t("取消任务")}
          onClose={() => setCancelling(undefined)}
          onConfirm={async () => {
            await api(`${base}/${cancelling.id}/cancel`, "POST");
            refresh();
          }}
        >
          <p>
            {t("取消下载并清理未完成的本地文件？已经转存成功的文件会保留。")}
          </p>
        </Dialog>
      )}
      {failure && (
        <AlertDialog title={t("下载任务失败")} onClose={() => setFailure("")}>
          <p className="offline-error-text">{failure}</p>
        </AlertDialog>
      )}
    </div>
  );
}

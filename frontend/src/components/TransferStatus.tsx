import { useEffect, useRef } from "react";
import { Button, Progress } from "@heroui/react";
import { t } from "../i18n";
import type { LocalJob } from "../lib/hooks";
import type { Notify, Upload } from "../lib/types";
import type { transferSummary } from "../lib/transfers";

export default function TransferStatus({
  summary,
  uploads,
  jobs,
  visible,
  onOpen,
  notify,
  refresh,
}: {
  summary: ReturnType<typeof transferSummary>;
  uploads: Upload[];
  jobs: LocalJob[];
  visible: boolean;
  onOpen: () => void;
  notify: Notify;
  refresh: () => void;
}) {
  const previous = useRef(new Set<string>());
  useEffect(() => {
    const completed = uploads.filter(
      (task) => task.state === "complete" && previous.current.has(task.id),
    );
    previous.current = new Set([
      ...uploads
        .filter((task) =>
          ["receiving", "sending", "error"].includes(task.state),
        )
        .map((task) => task.id),
      ...jobs.flatMap((job) =>
        job.taskId && !uploads.some((task) => task.id === job.taskId)
          ? [job.taskId]
          : [],
      ),
    ]);
    if (completed.length) {
      notify(t("{p0} 个文件已存入 Telegram", { p0: completed.length }));
      refresh();
    }
  }, [uploads, jobs, notify, refresh]);
  if (!visible || !summary.count) return null;
  return (
    <aside className="transfer-status" aria-label={t("上传进度")}>
      <div className="transfer-status-heading">
        <span>
          {t("{p0} 个传输任务进行中", { p0: summary.count })}
          {summary.attention && (
            <small> · {t("部分任务已暂停或需要重试")}</small>
          )}
        </span>
        <Button size="sm" variant="light" onPress={onOpen}>
          {t("查看传输")}
        </Button>
      </div>
      <div className="two-progress">
        <div>
          <span>
            {t("上传到服务器")}
            <b>{Math.floor(summary.received)}%</b>
          </span>
          <Progress
            size="sm"
            aria-label={t("上传到服务器")}
            value={summary.received}
          />
        </div>
        <div>
          <span>
            {t("存入 Telegram")}
            <b>{Math.floor(summary.stored)}%</b>
          </span>
          <Progress
            size="sm"
            color="success"
            aria-label={t("存入 Telegram")}
            value={summary.stored}
          />
        </div>
      </div>
    </aside>
  );
}

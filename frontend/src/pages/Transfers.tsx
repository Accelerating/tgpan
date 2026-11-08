import { t } from "../i18n";
import { useRef, useState } from "react";
import { Button, Progress } from "@heroui/react";
import {
  CheckCircle2,
  Clock3,
  Pause,
  RefreshCw,
  UploadCloud,
  X,
} from "lucide-react";
import { api, errorText, formatSize } from "../lib/api";
import { useData } from "../lib/hooks";
import type { LocalJob } from "../lib/hooks";
import type { Notify, Transfers as TransferData, Upload } from "../lib/types";
import {
  Dialog,
  Empty,
  ErrorBanner,
  FileIcon,
  Loading,
} from "../components/Shared";
const labels: Record<string, string> = {
  receiving: t("等待文件上传"),
  sending: t("正在转存 Telegram"),
  complete: t("已完成"),
  error: t("需要重试"),
  cancelled: t("已取消"),
  expired: t("已过期"),
};
const localLabels: Record<LocalJob["state"], string> = {
  queued: t("排队中"),
  checking: t("正在校验文件"),
  uploading: t("上传到服务器"),
  waiting: t("等待转存释放空间"),
  retrying: t("连接中断，正在重试"),
  uploaded: t("已传到服务器"),
  paused: t("已暂停"),
  error: t("失败"),
};
export default function Transfers({
  version,
  refresh,
  notify,
  jobs,
  enqueue,
  pause,
  clear,
}: {
  version: number;
  refresh: () => void;
  notify: Notify;
  jobs: LocalJob[];
  enqueue: (files: File[], parent: string | null, resume?: Upload) => void;
  pause: (id: number) => void;
  clear: () => void;
}) {
  const { data, error } = useData<TransferData>("/transfers", version, 2000);
  const [resume, setResume] = useState<Upload>();
  const [cancel, setCancel] = useState<Upload>();
  const input = useRef<HTMLInputElement>(null);
  const action = async (path: string) => {
    try {
      await api(path, "POST");
      refresh();
      notify(t("操作已提交"));
    } catch (e) {
      notify(errorText(e), true);
    }
  };
  const uploads = data?.uploads || [];
  const activeJobs = jobs.filter((job) => job.state !== "uploaded");
  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>{t("传输任务")}</h1>
        </div>
        <Button
          variant="bordered"
          startContent={<RefreshCw size={16} />}
          onPress={refresh}
        >
          {t("刷新")}
        </Button>
      </div>
      <ErrorBanner message={error} />
      {activeJobs.length > 0 && (
        <section className="settings-panel">
          <div className="section-heading">
            <h2>{t("浏览器上传队列")}</h2>
            <Button size="sm" variant="light" onPress={clear}>
              {t("清理已结束的本地记录")}
            </Button>
          </div>
          {activeJobs.map((job) => (
            <div className="transfer-row" key={job.id}>
              <span className="file-icon-box">
                <FileIcon node={{ name: job.file.name, kind: "file" }} />
              </span>
              <div className="transfer-info">
                <strong>{job.file.name}</strong>
                <div className="transfer-meta">
                  <span>{localLabels[job.state]}</span>
                  <span>
                    {formatSize(job.received)} / {formatSize(job.file.size)}
                  </span>
                </div>
                <Progress
                  aria-label={t("{p0} 上传进度", { p0: job.file.name })}
                  size="sm"
                  value={
                    job.file.size ? (job.received / job.file.size) * 100 : 0
                  }
                />
                {job.error && <p className="inline-error">{job.error}</p>}
              </div>
              {!["error", "paused"].includes(job.state) && (
                <Button
                  isIconOnly
                  variant="light"
                  size="sm"
                  aria-label={t("暂停 {p0}", { p0: job.file.name })}
                  onPress={() => pause(job.id)}
                >
                  <Pause size={17} />
                </Button>
              )}
            </div>
          ))}
        </section>
      )}
      <section className="settings-panel">
        <div className="section-heading">
          <h2>{t("上传与存储")}</h2>
          <span className="muted">
            {t("{p0} 个任务", { p0: uploads.length })}
          </span>
        </div>
        {!data && !error ? (
          <Loading />
        ) : !uploads.length ? (
          <Empty icon={<UploadCloud size={33} />} title={t("暂无传输任务")} />
        ) : (
          uploads.map((task) => {
            const local = jobs.find(
              (job) =>
                job.taskId === task.id &&
                !["paused", "error", "uploaded"].includes(job.state),
            );
            const stored = Math.min(
              task.size,
              task.stored + task.sending_bytes,
            );
            return (
              <div className="transfer-row" key={task.id}>
                <span className="file-icon-box">
                  <FileIcon node={{ name: task.name, kind: "file" }} />
                </span>
                <div className="transfer-info">
                  <div className="transfer-title">
                    <strong>{task.name}</strong>
                    <span className={`status-pill ${task.state}`}>
                      {task.state === "complete" && <CheckCircle2 size={12} />}{" "}
                      {labels[task.state] || task.state}
                    </span>
                  </div>
                  <div className="two-progress">
                    <div>
                      <span>
                        {t("上传到服务器")}
                        <b>
                          {task.size
                            ? Math.floor((task.received / task.size) * 100)
                            : 100}
                          %
                        </b>
                      </span>
                      <Progress
                        size="sm"
                        aria-label={t("{p0} 上传到服务器", { p0: task.name })}
                        value={
                          task.size ? (task.received / task.size) * 100 : 100
                        }
                      />
                    </div>
                    <div>
                      <span>
                        {t("存入 Telegram")}
                        <b>
                          {task.size
                            ? Math.floor((stored / task.size) * 100)
                            : 100}
                          %
                        </b>
                      </span>
                      <Progress
                        size="sm"
                        color="success"
                        aria-label={t("{p0} 存入 Telegram", { p0: task.name })}
                        value={task.size ? (stored / task.size) * 100 : 100}
                      />
                    </div>
                  </div>
                  <div className="transfer-meta">
                    <span>{formatSize(task.size)}</span>
                    {task.error && (
                      <span className="inline-error">{task.error}</span>
                    )}
                  </div>
                </div>
                <div className="transfer-actions">
                  {task.state === "error" && (
                    <Button
                      size="sm"
                      variant="flat"
                      onPress={() => void action(`/uploads/${task.id}/retry`)}
                    >
                      {t("重试转存")}
                    </Button>
                  )}
                  {task.received < task.size &&
                    !["cancelled", "complete", "expired"].includes(
                      task.state,
                    ) &&
                    !local && (
                      <Button
                        size="sm"
                        variant="flat"
                        startContent={<RefreshCw size={13} />}
                        onPress={() => {
                          setResume(task);
                          input.current?.click();
                        }}
                      >
                        {t("选择原文件续传")}
                      </Button>
                    )}
                  {!["complete", "cancelled", "expired"].includes(
                    task.state,
                  ) && (
                    <Button
                      size="sm"
                      isIconOnly
                      variant="light"
                      aria-label={t("取消 {p0}", { p0: task.name })}
                      onPress={() => setCancel(task)}
                    >
                      <X size={16} />
                    </Button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </section>
      {!!data?.cleanup.length && (
        <section className="settings-panel">
          <div className="section-heading">
            <h2>{t("Telegram 原文件清理")}</h2>
            <Button
              size="sm"
              variant="flat"
              onPress={() => void action("/cleanup/retry")}
            >
              {t("重试失败的清理")}
            </Button>
          </div>
          {data.cleanup.map((task) => (
            <div key={task.id} className="cleanup-row">
              <Clock3 size={17} />
              <span>
                {task.state === "error"
                  ? task.error
                  : t("正在排队清理原始消息")}
              </span>
            </div>
          ))}
        </section>
      )}
      <input
        ref={input}
        type="file"
        className="sr-only"
        aria-label={t("选择原文件续传")}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file && resume) enqueue([file], resume.parent_id, resume);
          e.target.value = "";
        }}
      />
      {cancel && (
        <Dialog
          title={t("取消上传")}
          danger
          confirmLabel={t("取消上传")}
          onClose={() => setCancel(undefined)}
          onConfirm={async () => {
            jobs
              .filter((j) => j.taskId === cancel.id)
              .forEach((j) => pause(j.id));
            await api(`/uploads/${cancel.id}/cancel`, "POST");
            refresh();
          }}
        >
          <p>
            {t("取消「{p0}」的上传？已存入 Telegram 的部分会进入后台清理。", {
              p0: cancel.name,
            })}
          </p>
        </Dialog>
      )}
    </div>
  );
}

import { t } from "../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, errorText, fingerprint } from "./api";
import type { System, Upload } from "./types";
export function useData<T>(
  path: string,
  version = 0,
  interval = 0,
  keepData = false,
) {
  const previousPath = useRef(path);
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let busy = false;
    const load = async () => {
      if (busy) return;
      busy = true;
      try {
        const value = await api<T>(path, "GET", undefined, controller.signal);
        if (!controller.signal.aborted) {
          setData(value);
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(errorText(e));
      } finally {
        busy = false;
      }
    };
    if (!keepData || previousPath.current !== path) setData(undefined);
    previousPath.current = path;
    void load();
    const timer = interval
      ? window.setInterval(() => {
          if (!document.hidden) void load();
        }, interval)
      : undefined;
    return () => {
      controller.abort();
      if (timer) window.clearInterval(timer);
    };
  }, [path, version, interval, keepData]);
  return { data, error };
}
export interface LocalJob {
  id: number;
  file: File;
  parent: string | null;
  taskId?: string;
  configId?: string;
  state:
    | "queued"
    | "checking"
    | "uploading"
    | "waiting"
    | "retrying"
    | "uploaded"
    | "paused"
    | "error";
  received: number;
  error?: string;
}
export function useUploader(system: System | undefined, onChange: () => void) {
  const [jobs, setJobs] = useState<LocalJob[]>([]);
  const [conflict, setConflict] = useState<{
    name: string;
    resolve: (keep: boolean) => void;
  }>();
  const queue = useRef<LocalJob[]>([]);
  const busy = useRef(false);
  const controllers = useRef(new Map<number, AbortController>());
  const nextId = useRef(0);
  const alive = useRef(true);
  const patch = useCallback((id: number, value: Partial<LocalJob>) => {
    if (alive.current)
      setJobs((old) =>
        old.map((job) => (job.id === id ? { ...job, ...value } : job)),
      );
  }, []);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      queue.current = [];
      controllers.current.forEach((c) => c.abort());
    };
  }, []);
  const process = async () => {
    if (busy.current || !system) return;
    busy.current = true;
    while (queue.current.length) {
      const job = queue.current.shift()!;
      const control = new AbortController();
      controllers.current.set(job.id, control);
      try {
        patch(job.id, { state: "checking", error: undefined });
        if (job.file.size > system.max_file_size)
          throw new Error(t("单个文件不能超过 5GB"));
        const stamp = await fingerprint(job.file);
        const createBody = {
          name: job.file.name,
          size: job.file.size,
          fingerprint: stamp,
          parent_id: job.parent,
          config_id: job.configId,
        };
        let task: Upload;
        try {
          task = job.taskId
            ? await api<Upload>(
                `/uploads/${job.taskId}`,
                "GET",
                undefined,
                control.signal,
              )
            : await api<Upload>("/uploads", "POST", createBody, control.signal);
        } catch (e) {
          if (job.taskId || !(e instanceof ApiError) || e.status !== 409)
            throw e;
          const keep = await new Promise<boolean>((resolve) => {
            const abort = () => {
              setConflict(undefined);
              resolve(false);
            };
            control.signal.addEventListener("abort", abort, { once: true });
            setConflict({
              name: job.file.name,
              resolve: (value) => {
                control.signal.removeEventListener("abort", abort);
                setConflict(undefined);
                resolve(value);
              },
            });
          });
          if (!keep) throw e;
          task = await api<Upload>(
            "/uploads",
            "POST",
            { ...createBody, conflict: "keep_both" },
            control.signal,
          );
        }
        job.taskId = task.id;
        patch(job.id, { taskId: task.id });
        if (task.fingerprint !== stamp || task.size !== job.file.size)
          throw new Error(t("所选文件与原上传任务不一致，请选择原文件"));
        if (task.state === "error") {
          await api(`/uploads/${task.id}/retry`, "POST");
          task = await api<Upload>(`/uploads/${task.id}`);
        }
        let offset = task.received;
        let failures = 0;
        while (offset < job.file.size) {
          if (control.signal.aborted)
            throw new DOMException(t("已暂停"), "AbortError");
          patch(job.id, { state: "uploading", received: offset });
          try {
            const response = await api<{
              received: number;
            }>(
              `/uploads/${task.id}/chunks?offset=${offset}`,
              "PUT",
              job.file.slice(offset, offset + system.chunk_size),
              control.signal,
            );
            offset = response.received;
            failures = 0;
          } catch (e) {
            if (control.signal.aborted) throw e;
            const retryable =
              e instanceof ApiError
                ? [409, 429, 502, 503, 504].includes(e.status)
                : e instanceof TypeError;
            if (
              !retryable ||
              (++failures > 8 && !(e instanceof ApiError && e.status === 429))
            )
              throw e;
            patch(job.id, {
              state:
                e instanceof ApiError && e.status === 429
                  ? "waiting"
                  : "retrying",
            });
            await new Promise<void>((resolve, reject) => {
              const abort = () => {
                clearTimeout(timer);
                reject(new DOMException(t("已暂停"), "AbortError"));
              };
              const timer = setTimeout(() => {
                control.signal.removeEventListener("abort", abort);
                resolve();
              }, 3000);
              control.signal.addEventListener("abort", abort, { once: true });
            });
            task = await api<Upload>(
              `/uploads/${task.id}`,
              "GET",
              undefined,
              control.signal,
            );
            if (task.state === "error")
              throw new Error(task.error || t("Telegram 转存失败，请重试"));
            offset = task.received;
          }
        }
        patch(job.id, { state: "uploaded", received: job.file.size });
        onChange();
      } catch (e) {
        patch(job.id, {
          state: control.signal.aborted ? "paused" : "error",
          error: control.signal.aborted ? undefined : errorText(e),
        });
      } finally {
        controllers.current.delete(job.id);
      }
    }
    busy.current = false;
    onChange();
  };
  const enqueue = (files: File[], parent: string | null, resume?: Upload) => {
    if (!system) return;
    const items: LocalJob[] = files.map((file) => ({
      id: ++nextId.current,
      file,
      parent,
      taskId: resume?.id,
      configId: resume?.config_id,
      state: "queued",
      received: resume?.received || 0,
    }));
    queue.current.push(...items);
    setJobs((old) => [...items, ...old]);
    void process();
  };
  const pause = (id: number) => {
    queue.current = queue.current.filter((job) => job.id !== id);
    controllers.current.get(id)?.abort();
    patch(id, { state: "paused" });
  };
  const clear = () =>
    setJobs((old) =>
      old.filter(
        (job) =>
          controllers.current.has(job.id) ||
          queue.current.some((q) => q.id === job.id),
      ),
    );
  return { jobs, enqueue, pause, clear, conflict };
}

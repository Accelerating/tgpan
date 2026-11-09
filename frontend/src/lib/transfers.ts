import type { LocalJob } from "./hooks";
import type { Upload } from "./types";

export function transferSummary(jobs: LocalJob[], uploads: Upload[]) {
  const pending = uploads.filter((task) =>
    ["receiving", "sending", "error"].includes(task.state),
  );
  const local = jobs.filter(
    (job) =>
      job.state !== "uploaded" &&
      !uploads.some((task) => task.id === job.taskId),
  );
  const size =
    pending.reduce((sum, task) => sum + task.size, 0) +
    local.reduce((sum, job) => sum + job.file.size, 0);
  const received =
    pending.reduce((sum, task) => {
      const job = jobs.find((item) => item.taskId === task.id);
      return (
        sum + Math.min(task.size, Math.max(task.received, job?.received || 0))
      );
    }, 0) + local.reduce((sum, job) => sum + job.received, 0);
  const stored = pending.reduce(
    (sum, task) => sum + Math.min(task.size, task.stored + task.sending_bytes),
    0,
  );
  return {
    count: pending.length + local.length,
    attention:
      pending.some((task) => task.state === "error") ||
      [
        ...local,
        ...jobs.filter((job) => pending.some((task) => task.id === job.taskId)),
      ].some((job) => ["paused", "error"].includes(job.state)),
    received: size ? (received / size) * 100 : 0,
    stored: size ? (stored / size) * 100 : 0,
  };
}

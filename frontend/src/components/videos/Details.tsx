import { formatSize } from "../../lib/api";
import { t } from "../../i18n";
import { AlertDialog } from "../Shared";
import type { VideoTask, VideoMetadata } from "./types";

export default function VideoDetails({
  task,
  metadata,
  onClose,
}: {
  task?: VideoTask;
  metadata?: VideoMetadata;
  onClose: () => void;
}) {
  return (
    <AlertDialog title={t("视频详情")} onClose={onClose}>
      <div className="video-details">
        {(task?.entries || (metadata ? [{ id: "file", metadata }] : [])).map(
          (entry) => (
            <article key={entry.id}>
              {entry.metadata.thumbnail && (
                <img
                  className="video-thumbnail"
                  src={entry.metadata.thumbnail}
                  alt=""
                  loading="lazy"
                  referrerPolicy="no-referrer"
                />
              )}
              <strong>{entry.metadata.title}</strong>
              {entry.metadata.id && (
                <p className="muted">
                  {t("视频 ID")}：{entry.metadata.id}
                </p>
              )}
              <p className="muted">
                {[
                  entry.metadata.site,
                  entry.metadata.uploader || entry.metadata.channel,
                  entry.metadata.upload_date,
                  entry.metadata.duration != null
                    ? `${Math.ceil(entry.metadata.duration / 60)} ${t("分钟")}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <p className="muted">
                {[
                  entry.metadata.height ? `${entry.metadata.height}p` : null,
                  entry.metadata.vcodec,
                  entry.metadata.acodec,
                  entry.metadata.ext,
                  entry.metadata.size != null
                    ? formatSize(entry.metadata.size)
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              {entry.metadata.webpage_url && (
                <a
                  className="video-source"
                  href={entry.metadata.webpage_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("打开原视频")}
                </a>
              )}
              {!!Object.keys(entry.metadata.subtitles || {}).length && (
                <p className="muted">
                  {t("字幕语言")}：
                  {Object.keys(entry.metadata.subtitles || {}).join(", ")}
                </p>
              )}
              {entry.metadata.description && (
                <details>
                  <summary>{t("简介")}</summary>
                  <p className="video-description">
                    {entry.metadata.description}
                  </p>
                </details>
              )}
            </article>
          ),
        )}
      </div>
    </AlertDialog>
  );
}

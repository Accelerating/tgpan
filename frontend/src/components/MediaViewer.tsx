import { t } from "../i18n";
import { useEffect, useRef, useState } from "react";
import { Button, Spinner } from "@heroui/react";
import { RefreshCw } from "lucide-react";
import { ErrorBanner } from "./Shared";
export default function MediaViewer({
  source,
  kind,
  name,
  onAccessError,
}: {
  source: string;
  kind: "image" | "video";
  name: string;
  onAccessError?: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const player = video.current;
    if (player && !player.getAttribute("src")) {
      player.src = source;
      player.load();
    }
    return () => {
      if (player) {
        player.pause();
        player.removeAttribute("src");
        player.load();
      }
    };
  }, [source, version]);
  const failed = (message: string) => {
    setLoading(false);
    setError(message);
    onAccessError?.();
  };
  return (
    <div className="preview-stage">
      {!error &&
        (kind === "image" ? (
          <img
            key={version}
            src={source}
            alt={name}
            className="preview-image"
            onLoad={() => setLoading(false)}
            onError={() => failed(t("图片加载失败，请重试或下载查看。"))}
          />
        ) : (
          <video
            key={version}
            ref={video}
            src={source}
            className="preview-video"
            controls
            playsInline
            preload="metadata"
            onLoadedMetadata={() => setLoading(false)}
            onCanPlay={() => setLoading(false)}
            onSeeking={() => setLoading(true)}
            onSeeked={() => setLoading(false)}
            onWaiting={() => setLoading(true)}
            onPlaying={() => setLoading(false)}
            onError={() =>
              failed(
                t(
                  "视频无法播放，请检查网络或下载查看。当前浏览器可能不支持此编码，推荐 H.264/AAC 的 MP4 或 WebM。",
                ),
              )
            }
          />
        ))}
      {loading && !error && (
        <div className="preview-loading" role="status">
          <Spinner color="white" />
          <span>{t("正在加载…")}</span>
        </div>
      )}
      {error && (
        <div className="preview-error">
          <ErrorBanner message={error} />
          <Button
            size="sm"
            variant="flat"
            startContent={<RefreshCw size={15} />}
            onPress={() => {
              setError("");
              setLoading(true);
              setVersion((n) => n + 1);
            }}
          >
            {t("重新加载")}
          </Button>
        </div>
      )}
    </div>
  );
}

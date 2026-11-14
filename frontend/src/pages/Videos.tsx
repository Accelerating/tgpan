import { useState } from "react";
import { Button } from "@heroui/react";
import { t } from "../i18n";
import TaskPage, { type TaskPageProps } from "../components/downloads/TaskPage";
import Cookies from "../components/videos/Cookies";
import CreateVideo from "../components/videos/CreateTask";
import SelectVideos from "../components/videos/SelectVideos";
import VideoDetails from "../components/videos/Details";
import type { VideoTask } from "../components/videos/types";

export default function Videos(props: TaskPageProps) {
  const [cookiesOpen, setCookiesOpen] = useState(false);
  const [details, setDetails] = useState<VideoTask>();
  return (
    <>
      <TaskPage
        {...props}
        base="/videos"
        title={t("视频下载")}
        emptyTitle={t("暂无视频下载")}
        unavailableMessage={t("请先联系管理员在设置中安装 yt-dlp 和 ffmpeg")}
        selectLabel={t("选择视频和画质")}
        headerActions={
          <Button variant="bordered" onPress={() => setCookiesOpen(true)}>
            {t("Cookie 管理")}
          </Button>
        }
        renderActions={(task) =>
          !!(task as VideoTask).entries.length && (
            <Button
              size="sm"
              variant="light"
              onPress={() => setDetails(task as VideoTask)}
            >
              {t("视频详情")}
            </Button>
          )
        }
        renderCreate={(p) => (
          <CreateVideo
            {...p}
            onCreated={(identities) => p.onCreated(identities)}
          />
        )}
        renderSelection={(p) => (
          <SelectVideos {...p} task={p.task as VideoTask} />
        )}
      />
      {cookiesOpen && <Cookies onClose={() => setCookiesOpen(false)} />}
      {details && (
        <VideoDetails task={details} onClose={() => setDetails(undefined)} />
      )}
    </>
  );
}

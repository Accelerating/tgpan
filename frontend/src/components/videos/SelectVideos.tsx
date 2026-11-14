import { useState } from "react";
import { Checkbox } from "@heroui/react";
import { t } from "../../i18n";
import { api } from "../../lib/api";
import { Dialog } from "../Shared";
import type { VideoTask } from "./types";

export default function SelectVideos({
  task,
  onClose,
  onSelected,
}: {
  task: VideoTask;
  onClose: () => void;
  onSelected: () => void;
}) {
  const [positions, setPositions] = useState(
    task.entries.map((e) => e.position),
  );
  const [quality, setQuality] = useState("best");
  const [audio, setAudio] = useState(false);
  const heights =
    task.entries.length === 1 ? task.entries[0].metadata.qualities : undefined;
  return (
    <Dialog
      title={t("选择视频和画质")}
      confirmLabel={t("开始下载")}
      onClose={onClose}
      onConfirm={async () => {
        await api(`/videos/${task.id}/select`, "POST", {
          positions,
          quality,
          audio_only: audio,
        });
        onSelected();
      }}
    >
      <strong>{task.name}</strong>
      <Checkbox isSelected={audio} onValueChange={setAudio}>
        {t("仅下载音频")}
      </Checkbox>
      <label className="field-label">
        {t("画质")}
        <select
          className="native-select"
          value={quality}
          disabled={audio}
          onChange={(e) => setQuality(e.target.value)}
        >
          <option value="best">{t("最佳画质")}</option>
          {[2160, 1440, 1080, 720, 480, 360]
            .filter((h) => !heights?.length || heights.some((v) => v <= h))
            .map((h) => (
              <option key={h} value={h}>
                {h}p
              </option>
            ))}
        </select>
      </label>
      <p className="muted">
        {t("选择不超过目标分辨率的最佳版本；实际可用画质取决于源站和 Cookie。")}
      </p>
      <Checkbox
        isSelected={positions.length === task.entries.length}
        onValueChange={(selected) =>
          setPositions(selected ? task.entries.map((e) => e.position) : [])
        }
      >
        {t("全选")}
      </Checkbox>
      <div className="video-selection">
        {task.entries.map((entry) => (
          <Checkbox
            key={entry.id}
            isSelected={positions.includes(entry.position)}
            onValueChange={(checked) =>
              setPositions((old) =>
                checked
                  ? [...old, entry.position]
                  : old.filter((p) => p !== entry.position),
              )
            }
          >
            <span>
              {entry.position}. {entry.metadata.title}
            </span>
            {entry.metadata.duration != null && (
              <small className="muted">
                {" "}
                · {Math.ceil(entry.metadata.duration / 60)} {t("分钟")}
              </small>
            )}
          </Checkbox>
        ))}
      </div>
    </Dialog>
  );
}

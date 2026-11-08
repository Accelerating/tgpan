import { useState } from "react";
import { Button, Textarea } from "@heroui/react";
import { t } from "../../i18n";
import { api, errorText, formatSize } from "../../lib/api";
import { useData } from "../../lib/hooks";
import type { OfflineTask, StorageConfig } from "../../lib/types";
import FolderSelect from "../FolderSelect";
import { AlertDialog, Dialog } from "../Shared";

export default function CreateTask({
  onClose,
  onCreated,
  maxFileSize,
}: {
  onClose: () => void;
  onCreated: (tasks: OfflineTask[]) => void;
  maxFileSize: number;
}) {
  const [sources, setSources] = useState("");
  const [torrent, setTorrent] = useState<File>();
  const [parent, setParent] = useState("");
  const [config, setConfig] = useState("");
  const [failure, setFailure] = useState("");
  const { data: configs } = useData<StorageConfig[]>("/storage");
  return (
    <>
      <Dialog
        title={t("新建离线下载")}
        confirmLabel={t("创建任务")}
        onClose={onClose}
        onConfirm={async () => {
          try {
            let encoded: string | undefined;
            if (torrent) {
              if (torrent.size > 8 * 1024 ** 2)
                throw new Error(t("种子无效或超过 8MiB"));
              const bytes = new Uint8Array(await torrent.arrayBuffer());
              let binary = "";
              for (const byte of bytes) binary += String.fromCharCode(byte);
              encoded = btoa(binary);
            }
            const tasks = await api<OfflineTask[]>("/offline", "POST", {
              sources: encoded
                ? []
                : sources
                    .split(/\r?\n/)
                    .map((line) => line.trim())
                    .filter(Boolean),
              torrent: encoded,
              parent_id: parent || null,
              config_id: config || null,
            });
            onCreated(tasks);
          } catch (error) {
            setFailure(errorText(error));
            throw error;
          }
        }}
      >
        <Textarea
          label={t("下载链接")}
          placeholder={t("每行一个 HTTP、HTTPS、磁力或种子地址")}
          minRows={4}
          value={sources}
          onValueChange={setSources}
          isDisabled={!!torrent}
        />
        <label className="field-label">
          {t("或上传 BT 种子")}
          <input
            type="file"
            accept=".torrent,application/x-bittorrent"
            onChange={(event) => setTorrent(event.target.files?.[0])}
          />
        </label>
        {torrent && (
          <Button
            size="sm"
            variant="light"
            onPress={() => setTorrent(undefined)}
          >
            {t("清除种子")}
          </Button>
        )}
        <FolderSelect value={parent} onChange={setParent} />
        <label className="field-label">
          {t("Telegram 存储")}
          <select
            className="native-select"
            value={config}
            onChange={(event) => setConfig(event.target.value)}
          >
            <option value="">{t("默认")}</option>
            {(configs || []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <p className="muted">
          {t("单文件最大 {p0}；BT 文件解析后可勾选。", {
            p0: formatSize(maxFileSize),
          })}
        </p>
      </Dialog>
      {failure && (
        <AlertDialog title={t("无法创建下载")} onClose={() => setFailure("")}>
          <p>{failure}</p>
        </AlertDialog>
      )}
    </>
  );
}

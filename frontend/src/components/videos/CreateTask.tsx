import { useState } from "react";
import { Textarea } from "@heroui/react";
import { t } from "../../i18n";
import { api } from "../../lib/api";
import { useData } from "../../lib/hooks";
import type { StorageConfig } from "../../lib/types";
import { Dialog } from "../Shared";
import FolderSelect from "../FolderSelect";
import type { VideoCookie } from "./types";

export default function CreateVideo({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (identities: string[]) => void;
}) {
  const [sources, setSources] = useState("");
  const [parent, setParent] = useState("");
  const [config, setConfig] = useState("");
  const [cookie, setCookie] = useState("");
  const { data: cookies } = useData<VideoCookie[]>("/videos/cookies");
  const { data: configs } = useData<StorageConfig[]>("/storage");
  return (
    <Dialog
      title={t("新建视频下载")}
      confirmLabel={t("解析视频")}
      onClose={onClose}
      onConfirm={async () => {
        const identities = await api<string[]>("/videos", "POST", {
          sources: sources
            .split(/\r?\n/)
            .map((s) => s.trim())
            .filter(Boolean),
          cookie_id: cookie || null,
          parent_id: parent || null,
          config_id: config || null,
        });
        onCreated(identities);
      }}
    >
      <Textarea
        label={t("视频链接")}
        placeholder={t("每行一个视频或播放列表链接，最多 20 个")}
        value={sources}
        onValueChange={setSources}
        minRows={4}
      />
      <label className="field-label">
        {t("使用 Cookie")}
        <select
          className="native-select"
          value={cookie}
          onChange={(e) => setCookie(e.target.value)}
        >
          <option value="">{t("不使用 Cookie")}</option>
          {cookies?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} · {c.domain}
            </option>
          ))}
        </select>
      </label>
      <FolderSelect value={parent} onChange={setParent} />
      <label className="field-label">
        {t("Telegram 存储")}
        <select
          className="native-select"
          value={config}
          onChange={(e) => setConfig(e.target.value)}
        >
          <option value="">{t("默认")}</option>
          {configs?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
    </Dialog>
  );
}

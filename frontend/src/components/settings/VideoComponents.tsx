import { useState } from "react";
import { Button, Progress } from "@heroui/react";
import { t } from "../../i18n";
import { api, errorText } from "../../lib/api";
import { useData } from "../../lib/hooks";
import type { Aria2Info, Notify } from "../../lib/types";
import { ErrorBanner } from "../Shared";

function Component({ name, notify }: { name: string; notify: Notify }) {
  const [version, setVersion] = useState(0);
  const { data, error } = useData<Aria2Info>(
    `/components/${name}`,
    version,
    3000,
  );
  const [busy, setBusy] = useState(false);
  return (
    <div className="aria2-body">
      <ErrorBanner message={error || data?.error || undefined} />
      <div className="aria2-card">
        <div>
          <strong>{name}</strong>
          <p className="muted">
            {data?.installed
              ? `${data.version} · ${data.managed ? t("应用管理") : t("系统安装")}`
              : t("未安装或不可用")}
          </p>
        </div>
        <Button
          size="sm"
          color="primary"
          isLoading={busy || data?.state === "installing"}
          onPress={async () => {
            setBusy(true);
            try {
              await api(`/components/${name}/install`, "POST");
              setVersion((v) => v + 1);
            } catch (e) {
              notify(errorText(e), true);
            } finally {
              setBusy(false);
            }
          }}
        >
          {data?.managed ? t("更新组件") : t("安装应用管理版本")}
        </Button>
      </div>
      {data?.state === "installing" && (
        <>
          <p>{data.message}</p>
          <Progress isIndeterminate size="sm" aria-label={t("安装进度")} />
        </>
      )}
      {data?.installed && (
        <details>
          <summary>{t("组件信息")}</summary>
          <code className="component-path">{data.path}</code>
        </details>
      )}
    </div>
  );
}
export default function VideoComponents({ notify }: { notify: Notify }) {
  return (
    <section className="settings-panel">
      <div className="section-heading">
        <h2>{t("视频下载组件")}</h2>
      </div>
      {["yt-dlp", "ffmpeg"].map((name) => (
        <Component key={name} name={name} notify={notify} />
      ))}
    </section>
  );
}

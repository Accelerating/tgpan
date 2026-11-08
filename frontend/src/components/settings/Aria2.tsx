import { useEffect, useState } from "react";
import { Button, Input, Progress } from "@heroui/react";
import { Download, RefreshCw } from "lucide-react";
import { t } from "../../i18n";
import { api, errorText } from "../../lib/api";
import { useData } from "../../lib/hooks";
import type { Aria2Info, Notify, OfflineSettings } from "../../lib/types";
import { ErrorBanner } from "../Shared";

export default function Aria2({ notify }: { notify: Notify }) {
  const [version, setVersion] = useState(0);
  const refresh = () => setVersion((old) => old + 1);
  const { data, error } = useData<Aria2Info>(
    "/components/aria2",
    version,
    3000,
  );
  const { data: settings, error: settingsError } = useData<OfflineSettings>(
    "/offline/settings",
    version,
  );
  const [concurrency, setConcurrency] = useState("1");
  const [capacity, setCapacity] = useState("10");
  const [reserve, setReserve] = useState("512");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (settings) {
      setConcurrency(String(settings.concurrency));
      setCapacity(String(settings.max_bytes / 1024 ** 3));
      setReserve(String(settings.reserve_bytes / 1024 ** 2));
    }
  }, [settings]);
  return (
    <section className="settings-panel">
      <div className="section-heading">
        <h2>{t("离线下载组件")}</h2>
        <Button
          size="sm"
          variant="light"
          startContent={<RefreshCw size={14} />}
          onPress={refresh}
        >
          {t("检查组件")}
        </Button>
      </div>
      <div className="aria2-body">
        <ErrorBanner
          message={error || settingsError || data?.error || undefined}
        />
        <div className="aria2-card">
          <div>
            <strong>aria2</strong>
            <p className="muted">
              {data?.installed
                ? `v${data.version} · ${data.managed ? t("应用管理") : t("系统安装")}`
                : t("未安装或不可用")}
            </p>
          </div>
          <Button
            color="primary"
            size="sm"
            startContent={<Download size={14} />}
            isLoading={busy || data?.state === "installing"}
            onPress={async () => {
              setBusy(true);
              try {
                await api("/components/aria2/install", "POST");
                refresh();
              } catch (error) {
                notify(errorText(error), true);
              } finally {
                setBusy(false);
              }
            }}
          >
            {data?.managed ? t("更新 aria2") : t("安装应用管理版本")}
          </Button>
        </div>
        {data?.state === "installing" && (
          <div className="aria2-install-progress">
            <p>{data.message}</p>
            <Progress size="sm" isIndeterminate aria-label={t("安装进度")} />
          </div>
        )}
        {data?.installed && (
          <details className="offline-details">
            <summary>{t("组件信息")}</summary>
            <p className="muted">{data.platform}</p>
            <code className="component-path">{data.path}</code>
          </details>
        )}
        <p className="muted">
          {t("安装和更新保存到应用数据目录，无需 root；已有系统版本也可使用。")}
        </p>
        <form
          className="offline-settings-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            try {
              await api("/offline/settings", "PATCH", {
                concurrency: Number(concurrency),
                max_bytes: Math.round(Number(capacity) * 1024 ** 3),
                reserve_bytes: Math.round(Number(reserve) * 1024 ** 2),
              });
              notify(t("离线下载设置已保存"));
              refresh();
            } catch (error) {
              notify(errorText(error), true);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Input
            label={t("同时下载任务数")}
            type="number"
            min="1"
            max="4"
            step="1"
            required
            value={concurrency}
            onValueChange={setConcurrency}
          />
          <Input
            label={t("离线空间上限（GiB）")}
            type="number"
            min="0.001"
            step="any"
            required
            value={capacity}
            onValueChange={setCapacity}
          />
          <Input
            label={t("磁盘保留空间（MiB）")}
            type="number"
            min="0"
            step="any"
            required
            value={reserve}
            onValueChange={setReserve}
          />
          <Button type="submit" variant="flat" isLoading={busy}>
            {t("保存设置")}
          </Button>
        </form>
      </div>
    </section>
  );
}

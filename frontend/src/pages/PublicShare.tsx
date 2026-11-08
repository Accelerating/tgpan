import { t } from "../i18n";
import { useEffect, useState } from "react";
import { Button, Input } from "@heroui/react";
import { ArrowDownToLine, Cloud, LockKeyhole, RefreshCw } from "lucide-react";
import { api, errorText, formatSize, dateTime } from "../lib/api";
import type { PublicShareInfo } from "../lib/types";
import { ErrorBanner, Loading, FileIcon } from "../components/Shared";
import MediaViewer from "../components/MediaViewer";
import CloudBackdrop from "../components/CloudBackdrop";
export default function PublicShare({ token }: { token: string }) {
  const path = `/public/shares/${encodeURIComponent(token)}`;
  const [info, setInfo] = useState<PublicShareInfo>();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [fatal, setFatal] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try {
      setInfo(await api<PublicShareInfo>(path));
      setFatal("");
    } catch (e) {
      setFatal(errorText(e));
      setInfo(undefined);
    }
  };
  useEffect(() => {
    let alive = true;
    api<PublicShareInfo>(path)
      .then((value) => {
        if (alive) setInfo(value);
      })
      .catch((e) => {
        if (alive) setFatal(errorText(e));
      });
    return () => {
      alive = false;
    };
  }, [path]);
  useEffect(() => {
    document.title = info?.title || t("好东西");
  }, [info?.title]);
  const unlock = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      setInfo(
        await api<PublicShareInfo>(`${path}/unlock`, "POST", { password }),
      );
      setPassword("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <main
      className={`public-share-page cloud-page${info?.requires_password ? " public-share-locked" : ""}`}
    >
      <CloudBackdrop />
      <div className="public-share-card">
        <div className="public-share-brand">
          <Cloud size={23} />
          <span>Pan</span>
        </div>
        <h1 className="public-share-title">{info?.title || t("好东西")}</h1>
        {fatal ? (
          <>
            <ErrorBanner message={fatal} />
            <Button
              variant="flat"
              startContent={<RefreshCw size={15} />}
              onPress={() => void load()}
            >
              {t("重新加载")}
            </Button>
          </>
        ) : !info ? (
          <Loading />
        ) : info.requires_password ? (
          <form className="share-password-form" onSubmit={unlock}>
            <Input
              label={t("分享密码")}
              type="password"
              autoComplete="off"
              value={password}
              onValueChange={setPassword}
              startContent={<LockKeyhole size={16} />}
              isRequired
              maxLength={128}
            />
            <ErrorBanner message={error} />
            <Button type="submit" color="primary" isLoading={busy}>
              {t("查看文件")}
            </Button>
          </form>
        ) : (
          <>
            <div className="public-share-file">
              <FileIcon node={{ name: info.name!, kind: "file" }} />
              <span>{info.name}</span>
              <span className="muted">{formatSize(info.size!)}</span>
            </div>
            {info.preview_kind && (
              <MediaViewer
                key={`${token}-${info.requires_password}`}
                source={`/api${path}/preview`}
                kind={info.preview_kind}
                name={info.name!}
                onAccessError={() => void load()}
              />
            )}
            <div className="public-share-actions">
              <span className="muted">
                {info.expires_at
                  ? t("有效期至 {p0}", { p0: dateTime(info.expires_at) })
                  : t("永久有效")}
              </span>
              <Button
                as="a"
                href={`/api${path}/download`}
                download={info.name}
                color="primary"
                startContent={<ArrowDownToLine size={16} />}
              >
                {t("下载文件")}
              </Button>
            </div>
          </>
        )}
      </div>
    </main>
  );
}

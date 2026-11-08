import { t } from "../i18n";
import { useState } from "react";
import { Button, Chip } from "@heroui/react";
import { Copy, Link2, X } from "lucide-react";
import { api, dateTime, errorText } from "../lib/api";
import { absoluteShareUrl, copyText } from "../lib/clipboard";
import { useData } from "../lib/hooks";
import type { Share, Notify } from "../lib/types";
import { Dialog, Empty, ErrorBanner, Loading } from "../components/Shared";
export default function Shares({
  version,
  refresh,
  notify,
}: {
  version: number;
  refresh: () => void;
  notify: Notify;
}) {
  const { data, error } = useData<Share[]>("/shares", version, 5000);
  const [target, setTarget] = useState<Share>();
  const copy = async (share: Share) => {
    try {
      await copyText(absoluteShareUrl(share.path));
      notify(t("已复制分享链接"));
    } catch (e) {
      notify(errorText(e), true);
    }
  };
  return (
    <div>
      <div className="page-heading">
        <h1>{t("我的分享")}</h1>
        <Button variant="bordered" onPress={refresh}>
          {t("刷新")}
        </Button>
      </div>
      <ErrorBanner message={error} />
      <section className="settings-panel">
        {!data && !error ? (
          <Loading />
        ) : !data?.length ? (
          <Empty icon={<Link2 size={30} />} title={t("暂无分享")} />
        ) : (
          data.map((share) => (
            <div className="share-row" key={share.id}>
              <div className="share-row-info">
                <strong>{share.title}</strong>
                <span>{share.name}</span>
                <small>
                  {share.expires_at
                    ? t("有效期至 {p0}", { p0: dateTime(share.expires_at) })
                    : t("永久有效")}
                  {share.has_password ? t(" · 有密码") : ""}
                </small>
              </div>
              <Chip
                size="sm"
                variant="flat"
                color={share.status === "active" ? "success" : "default"}
              >
                {
                  {
                    active: t("有效"),
                    expired: t("已过期"),
                    revoked: t("已取消"),
                  }[share.status]
                }
              </Chip>
              <Button
                isIconOnly
                size="sm"
                variant="light"
                aria-label={t("复制分享 {p0}", { p0: share.title })}
                onPress={() => void copy(share)}
                isDisabled={share.status !== "active"}
              >
                <Copy size={16} />
              </Button>
              {share.status === "active" && (
                <Button
                  isIconOnly
                  size="sm"
                  color="danger"
                  variant="light"
                  aria-label={t("取消分享 {p0}", { p0: share.title })}
                  onPress={() => setTarget(share)}
                >
                  <X size={16} />
                </Button>
              )}
            </div>
          ))
        )}
      </section>
      {target && (
        <Dialog
          title={t("取消分享")}
          danger
          confirmLabel={t("取消分享")}
          onClose={() => setTarget(undefined)}
          onConfirm={async () => {
            await api(`/shares/${target.id}`, "DELETE");
            refresh();
            notify(t("分享已取消"));
          }}
        >
          <p>{t("取消「{p0}」的分享？链接将失效。", { p0: target.title })}</p>
        </Dialog>
      )}
    </div>
  );
}

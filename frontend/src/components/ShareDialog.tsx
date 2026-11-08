import { t } from "../i18n";
import { useState } from "react";
import {
  Button,
  Input,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/react";
import { Copy, Link2 } from "lucide-react";
import { api, errorText } from "../lib/api";
import { absoluteShareUrl, copyText } from "../lib/clipboard";
import type { Node, Notify, Share } from "../lib/types";
import { ErrorBanner } from "./Shared";
import Modal from "./LocalizedModal";
export default function ShareDialog({
  node,
  onClose,
  notify,
}: {
  node: Node;
  onClose: () => void;
  notify: Notify;
}) {
  const [title, setTitle] = useState("");
  const [password, setPassword] = useState("");
  const [period, setPeriod] = useState("604800");
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [share, setShare] = useState<Share>();
  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const expiry =
        period === "never"
          ? null
          : period === "custom"
            ? new Date(custom)
            : new Date(Date.now() + Number(period) * 1000);
      if (
        expiry &&
        (!Number.isFinite(expiry.getTime()) || expiry.getTime() <= Date.now())
      )
        throw new Error(t("请选择未来的有效期"));
      setShare(
        await api<Share>("/shares", "POST", {
          node_id: node.id,
          title,
          password: password || null,
          expires_at: expiry?.toISOString() ?? null,
        }),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    try {
      await copyText(
        absoluteShareUrl(share!.path) +
          (password ? t("\n密码：{p0}", { p0: password }) : ""),
      );
      notify(t("已复制分享链接"));
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <Modal
      isOpen
      onClose={() => {
        if (!busy) onClose();
      }}
      isDismissable={!busy}
      placement="center"
    >
      <ModalContent>
        <form onSubmit={create}>
          <ModalHeader>
            {node.kind === "folder" ? t("分享目录") : t("分享文件")}
          </ModalHeader>
          <ModalBody>
            <div className="share-file-name">{node.name}</div>
            {node.kind === "folder" && (
              <p className="muted">
                {t(
                  "分享内容随目录实时更新，访问者可浏览和下载其中已完成的文件。",
                )}
              </p>
            )}
            {!share ? (
              <>
                <Input
                  label={t("分享标题")}
                  placeholder={t("好东西")}
                  value={title}
                  onValueChange={setTitle}
                  maxLength={200}
                />
                <Input
                  label={t("分享密码（可选）")}
                  placeholder={t("不设置密码")}
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onValueChange={setPassword}
                  minLength={4}
                  maxLength={128}
                  description={t("设置时至少 4 位")}
                />
                <label className="form-label">
                  {t("有效期")}
                  <select
                    className="native-select"
                    value={period}
                    onChange={(e) => setPeriod(e.target.value)}
                  >
                    <option value="3600">{t("1 小时")}</option>
                    <option value="86400">{t("1 天")}</option>
                    <option value="604800">{t("7 天")}</option>
                    <option value="2592000">{t("30 天")}</option>
                    <option value="custom">{t("自定义")}</option>
                    <option value="never">{t("永久有效")}</option>
                  </select>
                </label>
                {period === "custom" && (
                  <Input
                    type="datetime-local"
                    label={t("到期时间")}
                    value={custom}
                    onValueChange={setCustom}
                    isRequired
                  />
                )}
              </>
            ) : (
              <>
                <Input
                  label={t("分享链接")}
                  value={absoluteShareUrl(share.path)}
                  isReadOnly
                  endContent={<Link2 size={16} />}
                />
                <Button
                  color="primary"
                  startContent={<Copy size={16} />}
                  onPress={() => void copy()}
                >
                  {password ? t("复制链接及密码") : t("复制链接")}
                </Button>
              </>
            )}
            <ErrorBanner message={error} />
          </ModalBody>
          <ModalFooter>
            {share ? (
              <Button onPress={onClose}>{t("完成")}</Button>
            ) : (
              <>
                <Button variant="light" onPress={onClose} isDisabled={busy}>
                  {t("取消")}
                </Button>
                <Button color="primary" type="submit" isLoading={busy}>
                  {t("创建分享")}
                </Button>
              </>
            )}
          </ModalFooter>
        </form>
      </ModalContent>
    </Modal>
  );
}

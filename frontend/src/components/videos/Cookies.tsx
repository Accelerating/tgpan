import { useState } from "react";
import { Button, Input, Textarea } from "@heroui/react";
import { api } from "../../lib/api";
import { useData } from "../../lib/hooks";
import { t } from "../../i18n";
import { AlertDialog, Dialog, Empty, ErrorBanner } from "../Shared";
import type { VideoCookie } from "./types";

export default function Cookies({ onClose }: { onClose: () => void }) {
  const [version, setVersion] = useState(0);
  const { data, error } = useData<VideoCookie[]>("/videos/cookies", version);
  const [editing, setEditing] = useState<VideoCookie | "new">();
  const [removing, setRemoving] = useState<VideoCookie>();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [value, setValue] = useState("");
  const edit = (item: VideoCookie | "new") => {
    setName(item === "new" ? "" : item.name);
    setDomain(item === "new" ? "" : item.domain);
    setValue("");
    setEditing(item);
  };
  if (editing)
    return (
      <Dialog
        title={editing === "new" ? t("添加 Cookie") : t("更新 Cookie")}
        onClose={() => {
          setEditing(undefined);
          setValue("");
        }}
        onConfirm={async () => {
          await api(
            editing === "new"
              ? "/videos/cookies"
              : `/videos/cookies/${editing.id}`,
            editing === "new" ? "POST" : "PUT",
            { name, domain, value },
          );
          setVersion((v) => v + 1);
          setValue("");
        }}
      >
        <Input
          label={t("配置名称")}
          value={name}
          onValueChange={setName}
          maxLength={64}
          isRequired
        />
        <Input
          label={t("网站域名")}
          placeholder="bilibili.com / youtube.com"
          value={domain}
          onValueChange={setDomain}
          isRequired
        />
        <Textarea
          label="Cookie"
          value={value}
          onValueChange={setValue}
          minRows={5}
          maxLength={131072}
          autoComplete="off"
          description={t(
            "粘贴 Cookie 请求头或 Netscape 格式内容。保存后不再回显；更新时重新填写。",
          )}
        />
      </Dialog>
    );
  return (
    <>
      <AlertDialog title={t("Cookie 管理")} onClose={onClose}>
        <ErrorBanner message={error} />
        <Button color="primary" onPress={() => edit("new")}>
          {t("添加 Cookie")}
        </Button>
        {!data?.length && <Empty icon={null} title={t("暂无 Cookie 配置")} />}
        {data?.map((item) => (
          <div className="video-cookie-row" key={item.id}>
            <div>
              <strong>{item.name}</strong>
              <p className="muted">{item.domain}</p>
            </div>
            <Button size="sm" variant="light" onPress={() => edit(item)}>
              {t("编辑")}
            </Button>
            <Button
              size="sm"
              variant="light"
              color="danger"
              onPress={() => setRemoving(item)}
            >
              {t("删除")}
            </Button>
          </div>
        ))}
      </AlertDialog>
      {removing && (
        <Dialog
          title={t("删除 Cookie")}
          danger
          onClose={() => setRemoving(undefined)}
          onConfirm={async () => {
            await api(`/videos/cookies/${removing.id}`, "DELETE");
            setVersion((v) => v + 1);
          }}
        >
          <p>{t("删除「{p0}」？", { p0: removing.name })}</p>
        </Dialog>
      )}
    </>
  );
}

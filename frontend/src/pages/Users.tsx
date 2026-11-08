import { t } from "../i18n";
import { useState } from "react";
import { Button, Chip, Input } from "@heroui/react";
import {
  KeyRound,
  Plus,
  ShieldCheck,
  UserRound,
  UsersRound,
} from "lucide-react";
import { api, date } from "../lib/api";
import { useData } from "../lib/hooks";
import type { Notify, User } from "../lib/types";
import { Dialog, ErrorBanner, Loading } from "../components/Shared";
export default function Users({
  version,
  refresh,
  notify,
}: {
  version: number;
  refresh: () => void;
  notify: Notify;
}) {
  const { data, error } = useData<User[]>("/users", version);
  const [dialog, setDialog] = useState<
    "create" | "password" | "disable" | null
  >(null);
  const [target, setTarget] = useState<User>();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const submit = async () => {
    if (dialog === "create")
      await api("/users", "POST", { username, password });
    else
      await api(
        `/users/${target!.id}`,
        "PATCH",
        dialog === "password" ? { password } : { disabled: !target!.disabled },
      );
    setPassword("");
    refresh();
    notify(t("帐号已更新"));
  };
  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>{t("用户管理")}</h1>
        </div>
        <Button
          color="primary"
          startContent={<Plus size={17} />}
          onPress={() => {
            setUsername("");
            setPassword("");
            setDialog("create");
          }}
        >
          {t("创建帐号")}
        </Button>
      </div>
      <ErrorBanner message={error} />
      <section className="settings-panel">
        <div className="section-heading">
          <h2>
            <UsersRound size={18} />
            {t("帐号列表")}
          </h2>
        </div>
        {!data && !error ? (
          <Loading />
        ) : (
          data?.map((user) => (
            <div className="user-row" key={user.id}>
              <span className="user-avatar">
                {user.admin ? (
                  <ShieldCheck size={21} />
                ) : (
                  <UserRound size={21} />
                )}
              </span>
              <div className="user-info">
                <strong>{user.username}</strong>
                <span>{t("创建于 {p0}", { p0: date(user.created_at) })}</span>
              </div>
              <Chip
                variant="flat"
                size="sm"
                color={
                  user.disabled ? "default" : user.admin ? "primary" : "success"
                }
              >
                {user.disabled
                  ? t("已禁用")
                  : user.admin
                    ? t("管理员")
                    : t("正常")}
              </Chip>
              <Button
                size="sm"
                variant="light"
                startContent={<KeyRound size={14} />}
                onPress={() => {
                  setTarget(user);
                  setPassword("");
                  setDialog("password");
                }}
              >
                {t("重置密码")}
              </Button>
              {!user.admin && (
                <Button
                  size="sm"
                  color={user.disabled ? "primary" : "danger"}
                  variant="light"
                  onPress={() => {
                    setTarget(user);
                    setDialog("disable");
                  }}
                >
                  {user.disabled ? t("启用") : t("禁用")}
                </Button>
              )}
            </div>
          ))
        )}
      </section>
      {dialog && (
        <Dialog
          title={
            dialog === "create"
              ? t("创建帐号")
              : dialog === "password"
                ? t("重置密码")
                : target?.disabled
                  ? t("启用帐号")
                  : t("禁用帐号")
          }
          danger={dialog === "disable" && !target?.disabled}
          onClose={() => {
            setDialog(null);
            setPassword("");
          }}
          onConfirm={submit}
        >
          {dialog === "create" && (
            <Input
              label={t("用户名")}
              value={username}
              onValueChange={setUsername}
              description={t("字母、数字、下划线、点或连字符")}
              maxLength={64}
              isRequired
            />
          )}
          {dialog !== "disable" ? (
            <Input
              label={t("新密码")}
              type="password"
              autoComplete="new-password"
              value={password}
              onValueChange={setPassword}
              minLength={10}
              maxLength={128}
              description={t("至少 10 位字符")}
              isRequired
            />
          ) : (
            <p>
              {target?.disabled
                ? t("启用「{p0}」的帐号？", { p0: target.username })
                : t(
                    "禁用「{p0}」？禁用后现有会话立即失效，未完成的上传会暂停转存，已有文件保留。",
                    { p0: target?.username },
                  )}
            </p>
          )}
        </Dialog>
      )}
    </div>
  );
}

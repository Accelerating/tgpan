import { t } from "../i18n";
import { useState } from "react";
import { Button, Chip, Input } from "@heroui/react";
import {
  CheckCircle2,
  KeyRound,
  Pencil,
  Plus,
  Radio,
  Send,
  Star,
  Trash2,
  XCircle,
} from "lucide-react";
import { api, errorText } from "../lib/api";
import { useData } from "../lib/hooks";
import type { Notify, StorageConfig } from "../lib/types";
import { Dialog, Empty, ErrorBanner, Loading } from "../components/Shared";
import VideoComponents from "../components/settings/VideoComponents";
import Aria2 from "../components/settings/Aria2";
export default function Settings({
  version,
  refresh,
  notify,
  onPasswordChanged,
  admin,
}: {
  version: number;
  refresh: () => void;
  notify: Notify;
  onPasswordChanged: () => void;
  admin: boolean;
}) {
  const { data, error } = useData<StorageConfig[]>("/storage", version);
  const [dialog, setDialog] = useState<"add" | "delete" | "rename" | null>(
    null,
  );
  const [target, setTarget] = useState<StorageConfig>();
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [channel, setChannel] = useState("");
  const [testing, setTesting] = useState<string>();
  const [results, setResults] = useState<
    Record<
      string,
      {
        ok: boolean;
        error?: string;
        steps: {
          step: string;
          ok: boolean;
          detail: string;
        }[];
      }
    >
  >({});
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [saving, setSaving] = useState(false);
  const openAdd = () => {
    setName("");
    setToken("");
    setChannel("");
    setDialog("add");
  };
  const test = async (config: StorageConfig) => {
    setTesting(config.id);
    try {
      const result = await api<{
        ok: boolean;
        error?: string;
        steps: {
          step: string;
          ok: boolean;
          detail: string;
        }[];
      }>(`/storage/${config.id}/test`, "POST");
      setResults((old) => ({ ...old, [config.id]: result }));
    } catch (e) {
      notify(errorText(e), true);
    } finally {
      setTesting(undefined);
    }
  };
  const makeDefault = async (config: StorageConfig) => {
    try {
      await api(`/storage/${config.id}`, "PATCH", { is_default: true });
      refresh();
      notify(t("已设为默认存储"));
    } catch (e) {
      notify(errorText(e), true);
    }
  };
  const submit = async () => {
    if (dialog === "add")
      await api("/storage", "POST", { name, token, channel });
    else if (dialog === "delete") await api(`/storage/${target!.id}`, "DELETE");
    else await api(`/storage/${target!.id}`, "PATCH", { name });
    setToken("");
    refresh();
    notify(t("存储配置已更新"));
  };
  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== repeat) {
      notify(t("两次新密码不一致"), true);
      return;
    }
    setSaving(true);
    try {
      await api("/auth/password", "POST", {
        current_password: current,
        password,
      });
      notify(t("密码已修改，请重新登录"));
      onPasswordChanged();
    } catch (e) {
      notify(errorText(e), true);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>{t("设置")}</h1>
        </div>
      </div>
      <ErrorBanner message={error} />
      {admin && (
        <>
          <Aria2 notify={notify} />
          <VideoComponents notify={notify} />
        </>
      )}
      <section className="settings-panel">
        <div className="section-heading">
          <div className="section-heading-title">
            <span className="section-icon">
              <Send size={19} />
            </span>
            <div>
              <h2>{t("Telegram 存储")}</h2>
            </div>
          </div>
          <Button
            color="primary"
            size="sm"
            startContent={<Plus size={16} />}
            onPress={openAdd}
          >
            {t("添加配置")}
          </Button>
        </div>
        {!data && !error ? (
          <Loading />
        ) : !data?.length ? (
          <Empty icon={<Send size={30} />} title={t("暂无存储配置")} />
        ) : (
          <div className="config-list">
            {data.map((config) => (
              <div className="config-card" key={config.id}>
                <div className="config-top">
                  <span className="telegram-icon">
                    <Send size={23} />
                  </span>
                  <div className="config-name">
                    <h3>
                      {config.name}{" "}
                      {!!config.is_default && (
                        <Chip size="sm" color="primary" variant="flat">
                          {t("默认")}
                        </Chip>
                      )}
                    </h3>
                    <p>{config.channel}</p>
                  </div>
                  <div className="config-actions">
                    <Button
                      size="sm"
                      variant="flat"
                      startContent={!testing && <Radio size={15} />}
                      isLoading={testing === config.id}
                      isDisabled={!!testing && testing !== config.id}
                      onPress={() => void test(config)}
                    >
                      {t("测试连接")}
                    </Button>
                    {!config.is_default && (
                      <Button
                        size="sm"
                        variant="light"
                        startContent={<Star size={14} />}
                        onPress={() => void makeDefault(config)}
                      >
                        {t("设为默认")}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      isIconOnly
                      variant="light"
                      aria-label={t("重命名配置 {p0}", { p0: config.name })}
                      onPress={() => {
                        setTarget(config);
                        setName(config.name);
                        setDialog("rename");
                      }}
                    >
                      <Pencil size={15} />
                    </Button>
                    <Button
                      size="sm"
                      isIconOnly
                      variant="light"
                      aria-label={t("删除配置 {p0}", { p0: config.name })}
                      onPress={() => {
                        setTarget(config);
                        setDialog("delete");
                      }}
                    >
                      <Trash2 size={15} />
                    </Button>
                  </div>
                </div>
                {results[config.id] && (
                  <div
                    className={`test-results ${results[config.id].ok ? "test-success" : "test-error"}`}
                    role="status"
                  >
                    {results[config.id].steps.map((step) => (
                      <div key={step.step}>
                        <CheckCircle2 size={14} />
                        <strong>{step.step}</strong>
                        <span>{step.detail}</span>
                      </div>
                    ))}
                    {results[config.id].error && (
                      <div>
                        <XCircle size={15} />
                        {results[config.id].error}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="settings-panel">
        <div className="section-heading">
          <div className="section-heading-title">
            <span className="section-icon">
              <KeyRound size={19} />
            </span>
            <div>
              <h2>{t("帐号安全")}</h2>
              <p>{t("修改密码将退出所有设备。")}</p>
            </div>
          </div>
        </div>
        <form className="password-form" onSubmit={changePassword}>
          <Input
            label={t("当前密码")}
            type="password"
            autoComplete="current-password"
            value={current}
            onValueChange={setCurrent}
            isRequired
            variant="bordered"
          />
          <Input
            label={t("新密码")}
            description={t("10～128 位字符")}
            type="password"
            autoComplete="new-password"
            value={password}
            onValueChange={setPassword}
            minLength={10}
            maxLength={128}
            isRequired
            variant="bordered"
          />
          <Input
            label={t("确认新密码")}
            type="password"
            autoComplete="new-password"
            value={repeat}
            onValueChange={setRepeat}
            isRequired
            variant="bordered"
          />
          <Button
            type="submit"
            variant="flat"
            color="primary"
            isLoading={saving}
          >
            {t("更新密码")}
          </Button>
        </form>
      </section>
      {dialog && (
        <Dialog
          title={
            dialog === "add"
              ? t("添加存储配置")
              : dialog === "delete"
                ? t("删除存储配置")
                : t("重命名配置")
          }
          danger={dialog === "delete"}
          onClose={() => {
            setDialog(null);
            setToken("");
          }}
          onConfirm={submit}
        >
          {dialog === "delete" ? (
            <p>
              {t("删除「{p0}」？仍被文件或清理任务引用的配置无法删除。", {
                p0: target?.name,
              })}
            </p>
          ) : (
            <>
              <Input
                label={t("配置名称")}
                value={name}
                onValueChange={setName}
                isRequired
                maxLength={64}
              />
              {dialog === "add" && (
                <>
                  <Input
                    label="Bot Token"
                    type="password"
                    autoComplete="off"
                    value={token}
                    onValueChange={setToken}
                    isRequired
                    placeholder="123456:ABC…"
                  />
                  <Input
                    label={t("频道 ID")}
                    description={t("私有频道 ID 为 -100 开头的数字")}
                    value={channel}
                    onValueChange={setChannel}
                    isRequired
                    placeholder="-1001234567890"
                  />
                  <p className="muted small">
                    {t("机器人需为频道管理员，并具有发布消息、删除消息权限。")}
                  </p>
                </>
              )}
            </>
          )}
        </Dialog>
      )}
    </div>
  );
}

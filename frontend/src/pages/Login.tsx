import { t } from "../i18n";
import { useState } from "react";
import { Button, Input } from "@heroui/react";
import { ArrowRight, Cloud } from "lucide-react";
import { api, errorText, setCSRF } from "../lib/api";
import type { User } from "../lib/types";
import { ErrorBanner } from "../components/Shared";
import CloudBackdrop from "../components/CloudBackdrop";
export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{
        user: User;
        csrf: string;
      }>("/auth/login", "POST", { username, password });
      setCSRF(result.csrf);
      onLogin(result.user);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login-page cloud-page">
      <CloudBackdrop />
      <main className="login-main">
        <form className="login-form" onSubmit={submit}>
          <span className="welcome-icon">
            <Cloud size={27} />
          </span>
          <h2>{t("登录 Pan")}</h2>
          <Input
            label={t("用户名")}
            labelPlacement="outside"
            placeholder={t("输入用户名")}
            autoComplete="username"
            value={username}
            onValueChange={setUsername}
            isRequired
            variant="bordered"
          />
          <Input
            label={t("密码")}
            labelPlacement="outside"
            placeholder={t("输入密码")}
            type="password"
            autoComplete="current-password"
            value={password}
            onValueChange={setPassword}
            isRequired
            variant="bordered"
          />
          <ErrorBanner message={error} />
          <Button
            type="submit"
            color="primary"
            size="lg"
            isLoading={busy}
            endContent={!busy && <ArrowRight size={18} />}
          >
            {t("登录网盘")}
          </Button>
        </form>
      </main>
    </div>
  );
}

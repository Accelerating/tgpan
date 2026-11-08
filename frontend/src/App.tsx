import { t } from "./i18n";
import { useCallback, useEffect, useState } from "react";
import { Button, Spinner } from "@heroui/react";
import {
  CheckCircle2,
  ChevronRight,
  Cloud,
  Files as FilesIcon,
  FolderClosed,
  LogOut,
  Link2,
  Menu,
  Settings as SettingsIcon,
  Trash2,
  UploadCloud,
  UsersRound,
  X,
  AlertCircle,
} from "lucide-react";
import { api, errorText, setCSRF } from "./lib/api";
import { useData, useUploader } from "./lib/hooks";
import type { System, User } from "./lib/types";
import Files from "./pages/Files";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import Transfers from "./pages/Transfers";
import Users from "./pages/Users";
import PublicShare from "./pages/PublicShare";
import Shares from "./pages/Shares";
import { Dialog } from "./components/Shared";
type Page = "files" | "transfers" | "trash" | "shares" | "settings" | "users";
const pages = {
  files: t("我的文件"),
  transfers: t("传输任务"),
  trash: t("回收站"),
  shares: t("我的分享"),
  settings: t("设置"),
  users: t("用户管理"),
};
export default function App() {
  if (window.location.pathname.startsWith("/s/"))
    return <PublicShare token={window.location.pathname.split("/")[2] || ""} />;
  return <AccountApp />;
}
function AccountApp() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [bootError, setBootError] = useState("");
  const [page, setPage] = useState<Page>("files");
  const [version, setVersion] = useState(0);
  const [mobile, setMobile] = useState(false);
  const [notice, setNotice] = useState<{
    text: string;
    error: boolean;
  }>();
  const refresh = useCallback(() => setVersion((n) => n + 1), []);
  const notify = useCallback(
    (text: string, error = false) => setNotice({ text, error }),
    [],
  );
  useEffect(() => {
    let alive = true;
    api<{
      user: User;
      csrf: string;
    }>("/auth/me")
      .then((result) => {
        if (alive) {
          setCSRF(result.csrf);
          setUser(result.user);
        }
      })
      .catch((e) => {
        if (alive && e?.status !== 401) setBootError(errorText(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    const expired = () => {
      setUser(null);
      setCSRF("");
    };
    window.addEventListener("session-expired", expired);
    return () => {
      alive = false;
      window.removeEventListener("session-expired", expired);
    };
  }, []);
  if (loading)
    return (
      <div className="boot">
        <Cloud size={36} />
        <Spinner size="sm" />
        <p>{t("加载中…")}</p>
      </div>
    );
  if (bootError)
    return (
      <div className="boot">
        <AlertCircle size={30} />
        <p>{bootError}</p>
        <Button onPress={() => window.location.reload()}>
          {t("重新连接")}
        </Button>
      </div>
    );
  if (!user)
    return (
      <>
        <Login
          onLogin={(u) => {
            setUser(u);
            setPage("files");
            refresh();
          }}
        />
        {notice && <Toast notice={notice} close={() => setNotice(undefined)} />}
      </>
    );
  return (
    <Drive
      key={user.id}
      user={user}
      page={page}
      navigate={(next) => {
        setPage(next);
        setMobile(false);
      }}
      version={version}
      refresh={refresh}
      notify={notify}
      logout={() => {
        setUser(null);
        setCSRF("");
      }}
      mobile={mobile}
      setMobile={setMobile}
      notice={notice}
      closeNotice={() => setNotice(undefined)}
    />
  );
}
function Toast({
  notice,
  close,
}: {
  notice: {
    text: string;
    error: boolean;
  };
  close: () => void;
}) {
  return (
    <div
      className={`toast ${notice.error ? "toast-error" : ""}`}
      role={notice.error ? "alert" : "status"}
    >
      {notice.error ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
      <span>{notice.text}</span>
      <button onClick={close} aria-label={t("关闭提示")}>
        <X size={16} />
      </button>
    </div>
  );
}
function Drive({
  user,
  page,
  navigate,
  version,
  refresh,
  notify,
  logout,
  mobile,
  setMobile,
  notice,
  closeNotice,
}: {
  user: User;
  page: Page;
  navigate: (page: Page) => void;
  version: number;
  refresh: () => void;
  notify: (text: string, error?: boolean) => void;
  logout: () => void;
  mobile: boolean;
  setMobile: (value: boolean) => void;
  notice?: {
    text: string;
    error: boolean;
  };
  closeNotice: () => void;
}) {
  const { data: system, error: systemError } = useData<System>("/system");
  const uploader = useUploader(system, refresh);
  const nav = [
    { id: "files", label: t("我的文件"), icon: FolderClosed },
    { id: "transfers", label: t("传输任务"), icon: UploadCloud },
    { id: "trash", label: t("回收站"), icon: Trash2 },
    { id: "shares", label: t("我的分享"), icon: Link2 },
    { id: "settings", label: t("设置"), icon: SettingsIcon },
    ...(user.admin
      ? [{ id: "users", label: t("用户管理"), icon: UsersRound }]
      : []),
  ];
  const enqueue: typeof uploader.enqueue = (...args) => {
    if (!system) {
      notify(systemError || t("正在读取上传配置，请稍后重试"), true);
      return;
    }
    uploader.enqueue(...args);
    navigate("transfers");
  };
  const signOut = async () => {
    try {
      await api("/auth/logout", "POST");
      logout();
    } catch (e) {
      notify(errorText(e), true);
    }
  };
  return (
    <div className="app-shell">
      {mobile && (
        <div className="sidebar-scrim" onClick={() => setMobile(false)} />
      )}
      <aside className={`sidebar ${mobile ? "sidebar-open" : ""}`}>
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate("files");
          }}
        >
          <span className="brand-icon">
            <Cloud size={25} />
          </span>
          TG Pan
        </a>
        <nav>
          {nav.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? "active" : ""}`}
              onClick={() => navigate(item.id as Page)}
            >
              <item.icon size={19} />
              <span>{item.label}</span>
              {page === item.id && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button className="account-button" onClick={() => void signOut()}>
            <span className="account-avatar">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <span>
              <strong>{user.username}</strong>
              <small>{user.admin ? t("管理员") : t("私人帐号")}</small>
            </span>
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <Button
              className="mobile-menu"
              size="sm"
              isIconOnly
              variant="light"
              aria-label={t("打开导航")}
              onPress={() => setMobile(true)}
            >
              <Menu size={21} />
            </Button>
            <FilesIcon size={16} />
            <span>{t("私人网盘")}</span>
            <ChevronRight size={14} />
            <strong>{pages[page]}</strong>
          </div>
        </header>
        <main className="main-content">
          {page === "files" || page === "trash" ? (
            <Files
              key={page}
              trash={page === "trash"}
              version={version}
              refresh={refresh}
              notify={notify}
              enqueue={enqueue}
            />
          ) : page === "transfers" ? (
            <Transfers
              version={version}
              refresh={refresh}
              notify={notify}
              {...uploader}
              enqueue={enqueue}
            />
          ) : page === "shares" ? (
            <Shares version={version} refresh={refresh} notify={notify} />
          ) : page === "settings" ? (
            <Settings
              version={version}
              refresh={refresh}
              notify={notify}
              onPasswordChanged={logout}
            />
          ) : (
            <Users version={version} refresh={refresh} notify={notify} />
          )}
        </main>
      </div>
      {notice && <Toast notice={notice} close={closeNotice} />}
      {uploader.conflict && (
        <Dialog
          title={t("同目录已有同名项目")}
          confirmLabel={t("保留两份")}
          onClose={() => uploader.conflict?.resolve(false)}
          onConfirm={async () => {
            uploader.conflict?.resolve(true);
          }}
        >
          <p>
            {t("「{p0}」已存在。保留两份将自动为新文件添加编号。", {
              p0: uploader.conflict.name,
            })}
          </p>
        </Dialog>
      )}
    </div>
  );
}

import { t } from "../i18n";
import { useState } from "react";
import type { ReactNode } from "react";
import {
  Button,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Spinner,
} from "@heroui/react";
import {
  AlertCircle,
  File,
  FileArchive,
  FileImage,
  FileText,
  Folder,
  Music2,
  Video,
} from "lucide-react";
import type { Node } from "../lib/types";
import { errorText } from "../lib/api";
import Modal from "./LocalizedModal";
export function FileIcon({
  node,
  size = 20,
}: {
  node: Pick<Node, "name" | "kind">;
  size?: number;
}) {
  if (node.kind === "folder")
    return (
      <Folder
        size={size}
        className="file-icon folder-icon"
        fill="currentColor"
        fillOpacity={0.16}
      />
    );
  const extension = node.name.split(".").pop()?.toLowerCase() || "";
  const [Icon, className] = /^(png|jpg|jpeg|webp|gif|svg|heic)$/.test(extension)
    ? [FileImage, "image-icon"]
    : /^(mp4|mkv|mov|webm)$/.test(extension)
      ? [Video, "video-icon"]
      : /^(mp3|flac|wav|aac)$/.test(extension)
        ? [Music2, "music-icon"]
        : /^(zip|rar|7z|tar|gz)$/.test(extension)
          ? [FileArchive, "archive-icon"]
          : /^(txt|pdf|docx|md|csv|xlsx)$/.test(extension)
            ? [FileText, "text-icon"]
            : [File, "generic-icon"];
  return <Icon size={size} className={`file-icon ${className}`} />;
}
export function Empty({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading">
      <Spinner size="sm" />
      <span>{t("正在加载…")}</span>
    </div>
  );
}
export function ErrorBanner({ message }: { message?: string }) {
  return message ? (
    <div className="error-banner" role="alert">
      <AlertCircle size={17} />
      {message}
    </div>
  ) : null;
}
export function AlertDialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <Modal isOpen onClose={onClose} placement="center" backdrop="blur">
      <ModalContent>
        <ModalHeader>{title}</ModalHeader>
        <ModalBody>{children}</ModalBody>
        <ModalFooter>
          <Button color="primary" onPress={onClose}>
            {t("知道了")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
export function Dialog({
  title,
  children,
  onClose,
  onConfirm,
  confirmLabel = t("确认"),
  danger = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  onConfirm: () => Promise<void>;
  confirmLabel?: string;
  danger?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen
      onClose={() => {
        if (!busy) onClose();
      }}
      isDismissable={!busy}
      hideCloseButton={busy}
      placement="center"
      backdrop="blur"
    >
      <ModalContent>
        <ModalHeader>{title}</ModalHeader>
        <ModalBody>
          {children}
          <ErrorBanner message={error} />
        </ModalBody>
        <ModalFooter>
          <Button variant="light" onPress={onClose} isDisabled={busy}>
            {t("取消")}
          </Button>
          <Button
            color={danger ? "danger" : "primary"}
            isLoading={busy}
            onPress={() => void submit()}
          >
            {confirmLabel}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

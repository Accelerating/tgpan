import type { ComponentProps } from "react";
import { Modal as HeroModal, type ModalProps } from "@heroui/react";
import { X } from "lucide-react";
import { t } from "../i18n";

function CloseButton(props: ComponentProps<"button">) {
  return (
    <button {...props} aria-label={t("关闭")}>
      <X size={18} />
    </button>
  );
}

export default function Modal(props: ModalProps) {
  return <HeroModal closeButton={<CloseButton />} {...props} />;
}

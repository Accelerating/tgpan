import { t } from "../i18n";
import {
  Button,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/react";
import { ArrowDownToLine } from "lucide-react";
import type { Node } from "../lib/types";
import MediaViewer from "./MediaViewer";
import Modal from "./LocalizedModal";
export default function FilePreview({
  node,
  onClose,
  onDownload,
}: {
  node: Node;
  onClose: () => void;
  onDownload: () => void;
}) {
  return (
    <Modal
      isOpen
      onClose={onClose}
      size="5xl"
      placement="center"
      scrollBehavior="inside"
      backdrop="blur"
      classNames={{ base: "file-preview-modal" }}
    >
      <ModalContent>
        <ModalHeader>
          <span className="preview-title">{node.name}</span>
        </ModalHeader>
        <ModalBody>
          <MediaViewer
            source={`/api/files/${node.id}/preview`}
            kind={node.preview_kind!}
            name={node.name}
          />
        </ModalBody>
        <ModalFooter className="preview-footer">
          <Button
            variant="flat"
            startContent={<ArrowDownToLine size={16} />}
            onPress={onDownload}
          >
            {t("下载原文件")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

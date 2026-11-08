import { useState } from "react";
import { Button } from "@heroui/react";
import {
  ArrowDownToLine,
  ChevronRight,
  Eye,
  Folder,
  RefreshCw,
  X,
} from "lucide-react";
import { t } from "../../i18n";
import { formatSize } from "../../lib/api";
import { useData } from "../../lib/hooks";
import type { PublicListing, PublicNode } from "../../lib/types";
import { Empty, ErrorBanner, FileIcon, Loading } from "../Shared";
import MediaViewer from "../MediaViewer";

export default function SharedFolder({
  path,
  onAccessError,
}: {
  path: string;
  onAccessError: () => void;
}) {
  const [parent, setParent] = useState<string | null>(null);
  const [preview, setPreview] = useState<PublicNode>();
  const { data, error } = useData<PublicListing>(
    `${path}/files${parent ? `?parent_id=${encodeURIComponent(parent)}` : ""}`,
  );
  const navigate = (id: string) => {
    setPreview(undefined);
    setParent(id);
  };
  const filePath = (node: PublicNode, action: string) =>
    `/api${path}/files/${encodeURIComponent(node.id)}/${action}`;
  return (
    <section className="shared-folder">
      <div className="breadcrumbs shared-folder-path">
        {data?.breadcrumbs.map((crumb, index) => (
          <span key={crumb.id}>
            {index > 0 && <ChevronRight size={14} />}
            <Button
              size="sm"
              variant="light"
              onPress={() => navigate(crumb.id)}
            >
              {crumb.name}
            </Button>
          </span>
        ))}
      </div>
      <ErrorBanner message={error} />
      {error ? (
        <Button
          variant="flat"
          startContent={<RefreshCw size={15} />}
          onPress={onAccessError}
        >
          {t("重新加载")}
        </Button>
      ) : !data ? (
        <Loading />
      ) : !data.items.length ? (
        <Empty icon={<Folder size={30} />} title={t("目录为空")} />
      ) : (
        <ul className="shared-folder-list">
          {data.items.map((node) => (
            <li key={node.id}>
              <button
                className="file-name"
                onClick={() => {
                  if (node.kind === "folder") navigate(node.id);
                  else if (node.preview_kind) setPreview(node);
                }}
                disabled={node.kind === "file" && !node.preview_kind}
              >
                <span className="file-icon-box">
                  <FileIcon node={node} />
                </span>
                <span className="file-name-details">
                  <span className="file-name-text" title={node.name}>
                    {node.name}
                  </span>
                  <small className="muted">
                    {node.kind === "folder" ? t("目录") : formatSize(node.size)}
                  </small>
                </span>
              </button>
              {node.kind === "file" && (
                <div className="shared-folder-actions">
                  {node.preview_kind && (
                    <Button
                      isIconOnly
                      size="sm"
                      variant="light"
                      aria-label={t("预览 {p0}", { p0: node.name })}
                      onPress={() => setPreview(node)}
                    >
                      <Eye size={16} />
                    </Button>
                  )}
                  <Button
                    as="a"
                    isIconOnly
                    size="sm"
                    variant="light"
                    href={filePath(node, "download")}
                    download={node.name}
                    aria-label={t("下载 {p0}", { p0: node.name })}
                  >
                    <ArrowDownToLine size={16} />
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {preview && (
        <div className="shared-folder-preview">
          <div className="shared-folder-preview-heading">
            <strong>{preview.name}</strong>
            <Button
              isIconOnly
              size="sm"
              variant="light"
              aria-label={t("关闭预览")}
              onPress={() => setPreview(undefined)}
            >
              <X size={16} />
            </Button>
          </div>
          <MediaViewer
            key={preview.id}
            source={filePath(preview, "preview")}
            kind={preview.preview_kind!}
            name={preview.name}
            onAccessError={onAccessError}
          />
        </div>
      )}
    </section>
  );
}
